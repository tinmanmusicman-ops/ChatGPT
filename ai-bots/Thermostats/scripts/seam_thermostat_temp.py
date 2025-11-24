#!/usr/bin/env python3
"""High-level overview (plain English):

This script watches a Gmail inbox for AC requests, talks to the Seam thermostat API,
applies cooling/fan changes when requested, and logs readings to a Google Sheet.
It remembers active requests for a short time window, then resets to the regular schedule.
Configuration lives in config.json (API keys, Gmail creds, sheet IDs, etc).
"""

from __future__ import annotations

import argparse
import email  # For parsing raw messages fetched via IMAP
import imaplib  # IMAP client using Gmail UID commands
import json
import re
import sys
from contextlib import suppress
from datetime import datetime, timedelta
from email.header import decode_header, make_header  # Properly decode MIME-encoded subjects
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import gspread  # For Google Sheets logging
import pytz  # For timezone-aware timestamps
import requests  # For Seam API calls

SA_KEY_PATH = Path(__file__).resolve().parents[2] / "shared" / "Glocal.json"
SHARED_FIELDS = {"gmail_user", "gmail_app_password", "spreadsheet_id"}


def _load_shared_values() -> Dict[str, Any]:
    try:
        with open(SA_KEY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return {field: data[field] for field in SHARED_FIELDS if field in data}


def parse_args() -> argparse.Namespace:
    # CLI switches: where to find config, whether to be verbose, show capabilities, prompt setpoint.
    script_dir = Path(__file__).resolve().parent
    assets_dir = script_dir.parent / "bot-assets"
    parser = argparse.ArgumentParser(
        description="Print the current thermostat temperature from Seam."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=assets_dir / "config.json",
        help="Path to the config file (default: config.json next to this script).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Emit debug details about API calls.",
    )
    parser.add_argument(
        "--show-capabilities",
        action="store_true",
        help="Print capabilities_supported and property keys returned for the device.",
    )
    parser.add_argument(
        "--prompt-setpoint",
        action="store_true",
        help="Ask for a cooling set point when temperature exceeds the threshold.",
    )
    return parser.parse_args()


def load_config(path: Path) -> Dict[str, Any]:
    # Load config JSON and derive defaults (API endpoints, thresholds, test flags, time zone).
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    shared_values = _load_shared_values()
    for key, value in shared_values.items():
        cfg.setdefault(key, value)

    required = ["thermostat_id", "base_url"]
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise KeyError(f"Missing required config keys: {missing}")
    if not cfg.get("api_key") and not (cfg.get("client_id") and cfg.get("client_secret")):
        raise KeyError("Provide either api_key or both client_id and client_secret")

    base = cfg["base_url"].rstrip("/")
    cfg.setdefault("token_url", f"{base}/oauth/token")
    cfg.setdefault("thermostat_endpoint", f"{base}/v1/devices/get")
    cfg.setdefault("cool_endpoint", f"{base}/v1/thermostats/cool")
    cfg.setdefault("fan_endpoint", f"{base}/v1/thermostats/set_fan_mode")
    cfg.setdefault("timeout_seconds", 25)
    cfg.setdefault("cool_threshold_f", 75)
    cfg.setdefault("fan_circulate_below_f", 70)
    cfg.setdefault("fan_on_above_f", 78)
    cfg.setdefault("temp_adjust", 0)
    cfg.setdefault("request_timeout_minutes", 60)
    cfg.setdefault("request_state_file", "request_state.json")
    cfg.setdefault("timezone", "America/Los_Angeles")
    cfg.setdefault("test_mode", False)
    return cfg


def request_token(cfg: Dict[str, Any], verbose: bool = False) -> str:
    # OAuth client_credentials flow (only used if api_key is not provided).
    data = {"grant_type": "client_credentials"}
    token_url = cfg["token_url"]
    if verbose:
        print(f"Requesting OAuth token from {token_url}")
    resp = requests.post(
        token_url,
        data=data,
        auth=(cfg["client_id"], cfg["client_secret"]),
        timeout=cfg["timeout_seconds"],
    )
    resp.raise_for_status()
    parsed = resp.json()
    token = parsed.get("access_token")
    if not token:
        raise RuntimeError(f"Token response missing access_token: {parsed}")
    return token


def fetch_temperature(cfg: Dict[str, Any], headers: Dict[str, str], verbose: bool = False) -> Dict[str, Any]:
    # Ask Seam for the thermostat status.
    endpoint = cfg["thermostat_endpoint"]
    payload = {"device_id": cfg["thermostat_id"]}
    if verbose:
        print(f"Requesting thermostat status from {endpoint} with payload {payload}")
    resp = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=cfg["timeout_seconds"],
    )
    resp.raise_for_status()
    return resp.json()


def set_cooling_setpoint(cfg: Dict[str, Any], headers: Dict[str, str], setpoint_f: float, verbose: bool = False) -> None:
    # Tell Seam to change the cooling target temperature (in Fahrenheit).
    endpoint = cfg["cool_endpoint"]
    payload = {"device_id": cfg["thermostat_id"], "cooling_set_point_fahrenheit": setpoint_f}
    if verbose:
        print(f"Setting cooling set point to {setpoint_f} F via {endpoint}")
    resp = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=cfg["timeout_seconds"],
    )
    resp.raise_for_status()


def set_fan_mode(cfg: Dict[str, Any], headers: Dict[str, str], mode: str, verbose: bool = False) -> None:
    # Tell Seam to change the fan mode.
    endpoint = cfg["fan_endpoint"]
    payload = {"device_id": cfg["thermostat_id"], "fan_mode": mode}
    if verbose:
        print(f"Setting fan mode to {mode} via {endpoint}")
    resp = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=cfg["timeout_seconds"],
    )
    resp.raise_for_status()


def prompt_setpoint(default_f: float) -> float:
    # Ask the user for a custom cooling set point (used only with --prompt-setpoint).
    raw = input(f"Enter cooling set point in F (default {default_f}): ").strip()
    if not raw:
        return default_f
    try:
        return float(raw)
    except ValueError:
        print(f"Invalid number '{raw}', using default {default_f}")
        return default_f


def _pick_temp(props: Dict[str, Any], candidates: Tuple[Tuple[str, str], ...]) -> Tuple[Optional[Any], Optional[str]]:
    # Helper to choose the first available temperature value and its unit from the device properties.
    for key, unit in candidates:
        if key in props and props[key] is not None:
            return props[key], unit
    return None, None


def print_capabilities(device: Dict[str, Any]) -> None:
    # Show what the device can do and which property keys are present (debug helper).
    caps = device.get("capabilities_supported") or []
    props = device.get("properties") or device
    print("Capabilities:", ", ".join(caps) if caps else "none")
    print("Property keys:", ", ".join(sorted(props.keys())))


def _extract_clean_body(msg: email.message.Message) -> str:
    """Return the best-effort plain body: prefer text/plain, fallback to stripped HTML."""
    def decode_part(part) -> str:
        charset = part.get_content_charset() or "utf-8"
        try:
            return part.get_payload(decode=True).decode(charset, errors="ignore")
        except Exception:
            return part.get_payload(decode=True).decode(errors="ignore")

    # Prefer text/plain parts that are not attachments.
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                return decode_part(part)
        # Fallback: pick first html part and strip tags crudely.
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = decode_part(part)
                # Strip HTML tags crudely to plain text.
                text = re.sub(r"<br\\s*/?>", "\n", html, flags=re.I)
                text = re.sub(r"<[^>]+>", "", text)
                return text
    else:
        return decode_part(msg)
    return ""


def _extract_user_text(body: str) -> str:
    """Pull the likely user-entered line (e.g., SMS text) from a noisy body."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # Prefer a line that starts with AC (case-insensitive).
    for ln in lines:
        if ln.upper().startswith("AC"):
            return ln
    # Fallback: first non-URL, non-disclaimer line.
    stop_markers = (
        "to respond to this text message",
        "this email was sent to you because",
    )
    for ln in lines:
        low = ln.lower()
        if low.startswith("http://") or low.startswith("https://"):
            continue
        if any(low.startswith(mark) for mark in stop_markers):
            break
        return ln
    return lines[0] if lines else ""


def fetch_primary_ac_emails(cfg: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Fetch unread Primary emails; return list of dicts with subject/body/user-text for messages starting with AC."""
    user = cfg.get("gmail_user") or cfg.get("user")
    password = cfg.get("gmail_app_password") or cfg.get("app_password")
    results: list[Dict[str, str]] = []
    test_mode = bool(cfg.get("test") or cfg.get("test_mode"))  # When True, do not mark/move emails.
    if not user or not password:
        print("[email] Missing Gmail credentials; skipping email scan.")
        return results

    folder = cfg.get("gmail_folder", "INBOX")
    # Unseen messages in Primary (via X-GM-RAW); subjects filtered locally for AC*.
    search_terms = ["UNSEEN", "X-GM-RAW", '"category:primary"']

    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(user, password)
        typ, _ = imap.select(folder)
        if typ != "OK":
            print(f"[email] Failed to select {folder}: {typ}")
            return results
        typ, data = imap.uid("SEARCH", None, *search_terms)
        print(f"[email] UID search status={typ}, response entries={len(data)}")
        if typ != "OK" or not data or not data[0]:
            print("[email] No messages found in INBOX.")
            return results
        for uid in data[0].split():
            typ, msg_data = imap.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK = do not mark as read
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subj = str(make_header(decode_header(msg.get("Subject", "")))).strip()
            body = _extract_clean_body(msg)
            user_text = _extract_user_text(body)
            ac_candidate = user_text or body or subj
            if (ac_candidate or "").upper().startswith("AC"):
                if not test_mode:
                    imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Seen)")
                    imap.create("Thermostats")
                    imap.uid("COPY", uid, "Thermostats")
                    imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)")
                    imap.expunge()
            else:
                if not test_mode:
                    imap.uid("STORE", uid, "-FLAGS.SILENT", "(\\Seen)")
            results.append({"subject": subj, "body": body, "text": user_text})
    finally:
        with suppress(Exception):
            imap.logout()
    return results


def _parse_iso_timestamp(ts: str) -> datetime:
    """Parse ISO 8601 timestamps, tolerating a trailing Z."""
    if ts.endswith("Z"):
        ts = ts[:-1]
    return datetime.fromisoformat(ts)


def request_state_path(cfg: Dict[str, Any]) -> Path:
    """Resolve where to persist the active request window."""
    raw_path = cfg.get("request_state_file", "request_state.json")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def load_request_state(path: Path) -> Optional[Dict[str, Any]]:
    """Load persisted request state if present and valid."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        print(f"[request-state] Failed to read {path}: {exc}")
        return None


def save_request_state(path: Path, state: Dict[str, Any]) -> None:
    """Persist request state for future runs."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except Exception as exc:
        print(f"[request-state] Failed to save {path}: {exc}")


def clear_request_state(path: Path) -> None:
    """Remove saved request state when expired or cleared."""
    with suppress(Exception):
        path.unlink()


def is_request_active(state: Optional[Dict[str, Any]]) -> bool:
    """Return True if request state has a future expiration."""
    if not state or "expires_at" not in state:
        return False
    try:
        expires = _parse_iso_timestamp(str(state["expires_at"]))
    except Exception:
        return False
    return datetime.utcnow() < expires


def parse_request_timeout_minutes(subject: str, default_minutes: float) -> float:
    """Extract an override timeout (in minutes) from the subject after the studio number, if present."""
    numbers = re.findall(r"\d+", subject)
    if len(numbers) >= 2:
        try:
            minutes = float(numbers[1])
            if minutes > 0:
                return minutes
        except Exception:
            pass
    return default_minutes


def resolve_zone_thermostat(subject: str, cfg: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[int]]:
    """Parse ACNN from subject, map to zone, and return (thermostat_id, zone_name, studio_num)."""
    subj_upper = subject.upper()
    studio_num = None
    m = re.search(r"AC\s*(\d{1,2})", subj_upper)
    if m:
        try:
            studio_num = int(m.group(1))
        except ValueError:
            studio_num = None

    zone_map = {
        "zone1": [4, 6, 8],
        "zone2": [3, 5, 7, 2, 9, 20, 21],
        "zone3": [10, 11, 12, 13],
        "zone4": [16, 17, 18, 19],
    }
    zone_name = None
    for name, studios in zone_map.items():
        if studio_num in studios:
            zone_name = name
            break

    zone_key = f"{zone_name}_thermostat_id" if zone_name else None
    selected_tid = cfg.get(zone_key) if zone_key else None
    if not selected_tid:
        selected_tid = cfg.get("thermostat_id")
    return selected_tid, zone_name, studio_num


def resolve_service_account_path(cfg: Dict[str, Any]) -> Path:
    sa_value = cfg.get("service_account_json") or cfg.get("service_account")
    if sa_value:
        sa_path = Path(sa_value)
        if not sa_path.is_absolute():
            shared_candidate = Path(__file__).resolve().parents[2] / "shared" / sa_path.name
            if shared_candidate.exists():
                sa_path = shared_candidate
            else:
                sa_path = Path(__file__).resolve().parent / sa_path
    else:
        sa_path = SA_KEY_PATH
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account file not found: {sa_path}")
    return sa_path


def now_local_iso(tz_name: str) -> str:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime("%A %b %d %Y %I:%M %p")


def format_expiration_local(expires_iso: Optional[str], tz_name: str) -> str:
    """Format expiration ISO timestamp into local time (hh:mm AM/PM)."""
    if not expires_iso:
        return ""
    try:
        expires_utc = _parse_iso_timestamp(str(expires_iso))
        expires_utc = expires_utc.replace(tzinfo=pytz.utc)
        tz = pytz.timezone(tz_name)
        local_dt = expires_utc.astimezone(tz)
        return local_dt.strftime("%I:%M %p")
    except Exception:
        return ""


def ensure_thermostat_sheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    """Ensure Thermostats worksheet exists with headers."""
    try:
        ws = spreadsheet.worksheet("Thermostats")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="Thermostats", rows=1000, cols=10)
    headers = [
        "Timestamp",
        "Type",
        "Current Temperature",
        "Cooling Set Point",
        "Climate Setting",
        "Fan Setting",
        "Equipment Status",
        "Studio",
        "Request Expires (local time)",
    ]
    existing = ws.row_values(1)
    if existing != headers:
        ws.update("A1:I1", [headers], value_input_option="USER_ENTERED")
    return ws


def append_thermostat_row(cfg: Dict[str, Any], reading: Dict[str, Any], payload: Dict[str, Any], entry_type: str = "system", studio: Optional[int] = None, expiration_local: str = "") -> None:
    """Append one row of thermostat data into the Google Sheet."""
    try:
        sa_path = resolve_service_account_path(cfg)
        client = gspread.service_account(filename=str(sa_path))
        spreadsheet = client.open_by_key(cfg["spreadsheet_id"])
        ws = ensure_thermostat_sheet(spreadsheet)

        props = payload.get("properties") or payload.get("device", {}).get("properties") or payload.get("device", {})
        climate_props = props.get("current_climate_setting") or {}
        climate = (
            climate_props.get("hvac_mode_setting")
            or props.get("hvac_mode_setting")
            or props.get("mode")
            or props.get("hvac_mode")
            or ""
        )
        fan = (
            climate_props.get("fan_mode_setting")
            or props.get("fan_mode_setting")
            or props.get("fan_mode")
            or ""
        )
        cool_set_point_f = climate_props.get("cooling_set_point_fahrenheit")
        if cool_set_point_f is None:
            c_val = climate_props.get("cooling_set_point_celsius")
            if c_val is not None:
                cool_set_point_f = c_val * 9.0 / 5.0 + 32
        if cool_set_point_f is None:
            cool_set_point_f = props.get("target_temperature_fahrenheit") or props.get("cooling_set_point_fahrenheit")
        if cool_set_point_f is None:
            c_val = props.get("target_temperature_celsius") or props.get("cooling_set_point_celsius")
            if c_val is not None:
                cool_set_point_f = c_val * 9.0 / 5.0 + 32

        equipment = props.get("equipment_status")
        if not equipment:
            if props.get("is_cooling"):
                equipment = "cooling"
            elif props.get("is_heating"):
                equipment = "heating"
            elif props.get("is_fan_running"):
                equipment = "fan"
            else:
                equipment = "idle"

        tz_name = cfg.get("timezone", "America/Los_Angeles")
        timestamp = now_local_iso(tz_name)
        row = [
            timestamp,
            entry_type,
            reading.get("current_temperature", ""),
            cool_set_point_f if cool_set_point_f is not None else "",
            climate,
            fan,
            equipment,
            studio or "",
            expiration_local,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as exc:
        print(f"[sheet] Failed to append thermostat row: {exc}")


def extract_temp_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    device = response.get("device")
    if not device and isinstance(response.get("thermostats"), list) and response["thermostats"]:
        device = response["thermostats"][0]
    if not device:
        device = response

    props = device.get("properties", device)

    current, unit = _pick_temp(
        props,
        (
            ("current_temperature_fahrenheit", "F"),
            ("temperature_fahrenheit", "F"),
            ("current_temperature_celsius", "C"),
            ("temperature_celsius", "C"),
            ("current_temperature", ""),
            ("temperature", ""),
        ),
    )
    if current is None:
        raise RuntimeError("Response does not include a temperature value")

    target, target_unit = _pick_temp(
        props,
        (
            ("target_temperature_fahrenheit", "F"),
            ("target_temperature_celsius", "C"),
            ("target_temperature", unit or ""),
        ),
    )
    mode = props.get("mode") or props.get("hvac_mode")

    return {
        "current_temperature": current,
        "target_temperature": target,
        "mode": mode,
        "unit": target_unit or unit or "",
        "_device": device,
    }


def main() -> None:
    args = parse_args()
    # Step 1: read config (API keys, Gmail creds, Google Sheet info, time zones).
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"Unable to load config: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 2: restore any previously active request (for honoring timeouts).
    state_path = request_state_path(cfg)
    saved_state = load_request_state(state_path)
    had_state = saved_state is not None
    state_expired = had_state and not is_request_active(saved_state)
    if state_expired:
        exp_val = saved_state.get("expires_at", "")
        print(f"[request] Previous request expired at {exp_val}; clearing state.")
        clear_request_state(state_path)
        saved_state = None

    # Step 3: read Gmail for AC requests (from body or subject).
    emails = fetch_primary_ac_emails(cfg)
    body = emails[0].get("text") or emails[0].get("body", "") if emails else ""
    # Set a breakpoint here if you need to inspect the raw body before filtering.
    # breakpoint()
    matched = [
        em
        for em in emails
        if (em.get("text") or em.get("body") or em.get("subject", "")).upper().startswith("AC")
    ]
    entry_type = "system"
    selected_tid = cfg.get("thermostat_id")
    request_studio = None
    active_request = saved_state if saved_state else None
    new_request = False
    request_minutes = None
    expiration_local = ""
    if matched:
        # Use the first matched AC text (from body or subject) to determine zone/thermostat mapping.
        ac_text = matched[0].get("text") or matched[0].get("body") or matched[0].get("subject", "")
        body = matched[0].get("body", "")
        if args.verbose:
            print(f"[email] Body preview: {body[:120]!r}")
        selected_tid, zone_name, studio_num = resolve_zone_thermostat(ac_text, cfg)
        cfg["thermostat_id"] = selected_tid or cfg["thermostat_id"]
        zone_label = zone_name or "unknown"
        default_timeout = float(cfg.get("request_timeout_minutes", 60))
        timeout_min = parse_request_timeout_minutes(ac_text, default_timeout)
        request_minutes = timeout_min
        expires_at = (datetime.utcnow() + timedelta(minutes=timeout_min)).isoformat() + "Z"
        active_request = {
            "subject": ac_text,
            "studio": studio_num,
            "zone": zone_name,
            "thermostat_id": cfg["thermostat_id"],
            "expires_at": expires_at,
            "timeout_minutes": timeout_min,
        }
        save_request_state(state_path, active_request)
        new_request = True
        print(f"[email] Message: {ac_text} -> studio {studio_num}, zone {zone_label}, thermostat {cfg['thermostat_id']}")
        print(f"[email] AC match passed. Request window {timeout_min} min, expires at {expires_at}")
    elif active_request:
        try:
            exp_ts = _parse_iso_timestamp(str(active_request.get("expires_at")))
            remaining = (exp_ts - datetime.utcnow()).total_seconds() / 60.0
            remaining_str = f"{remaining:.1f} min" if remaining > 0 else "expired"
        except Exception:
            remaining_str = "unknown"
        print(f"[email] Continuing active request from subject '{active_request.get('subject', '')}' (expires in {remaining_str}).")
        cfg["thermostat_id"] = active_request.get("thermostat_id", cfg["thermostat_id"])
        selected_tid = cfg["thermostat_id"]
        request_studio = active_request.get("studio")
    else:
        print("[email] AC match failed (no subject starting with AC).")

    # At this point we know whether a request is active (still inside its time window).
    request_active = active_request is not None  # True when a request is within its timeout window.
    request_expired_now = state_expired and not request_active and not new_request
    if request_active:
        request_studio = active_request.get("studio")
        request_zone = active_request.get("zone")
        if request_minutes is None:
            request_minutes = active_request.get("timeout_minutes") or cfg.get("request_timeout_minutes", 60)
        # Format minutes nicely (avoid trailing .0).
        minutes_label = None
        try:
            mins_val = float(request_minutes)
            if mins_val.is_integer():
                minutes_label = f"{int(mins_val)}m"
            else:
                minutes_label = f"{mins_val}m"
        except Exception:
            minutes_label = f"{request_minutes}m" if request_minutes is not None else None
        parts = ["request"]
        if request_studio is not None:
            parts.append(f"studio {request_studio}")
        if request_zone:
            parts.append(f"{request_zone}")
        if minutes_label:
            parts.append(minutes_label)
        if len(parts) > 1:
            entry_type = parts[0] + " (" + ", ".join(parts[1:]) + ")"
        else:
            entry_type = parts[0]
        expiration_local = format_expiration_local(
            active_request.get("expires_at"),
            cfg.get("timezone", "America/Los_Angeles"),
        )

    try:
        if cfg.get("api_key"):
            headers = {
                "Authorization": f"Bearer {cfg['api_key']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        else:
            token = request_token(cfg, verbose=args.verbose)
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        # If a previous request expired, revert to schedule defaults.
        if request_expired_now:
            try:
                base_setpoint = float(cfg.get("cool_threshold_f", 75))
                print(f"[request] Expired request -> reverting set point to {base_setpoint} F and fan to auto.")
                set_cooling_setpoint(cfg, headers=headers, setpoint_f=base_setpoint, verbose=args.verbose)
                set_fan_mode(cfg, headers=headers, mode="auto", verbose=args.verbose)
            except Exception as exc:
                print(f"[request] Failed to revert after expiration: {exc}", file=sys.stderr)

        payload = fetch_temperature(cfg, headers=headers, verbose=args.verbose)
        reading = extract_temp_payload(payload)

        if args.show_capabilities:
            print_capabilities(reading.get("_device", {}))

        # Request handling: set to current temp minus 2F (converted if needed) and fan on.
        # This is the "do it now" path driven by an email/text request.
        if request_active:
            try:
                current_temp = float(reading["current_temperature"])
                unit = (reading.get("unit") or "").upper()
                if unit == "C":
                    setpoint_c = current_temp - 2.0
                    setpoint_f = setpoint_c * 9.0 / 5.0 + 32.0
                else:
                    setpoint_f = current_temp - 2.0
                set_cooling_setpoint(cfg, headers=headers, setpoint_f=setpoint_f, verbose=args.verbose)
                set_fan_mode(cfg, headers=headers, mode="on", verbose=args.verbose)
            except Exception as exc:
                print(f"[email] Failed to apply request actions: {exc}", file=sys.stderr)

        # Auto-adjust only for system runs (skip if request already active).
        # This is the normal safety behavior: if the room is too warm/cool, adjust set point or fan.
        if not request_active:
            temp_adjust = float(cfg.get("temp_adjust", 0))
            adjusted_current = float(reading["current_temperature"]) + temp_adjust
            if args.verbose and temp_adjust != 0:
                print(f"Applied temp_adjust {temp_adjust}: raw={reading['current_temperature']} -> adjusted={adjusted_current}")
            reading["current_temperature"] = adjusted_current

            threshold_f = float(cfg.get("cool_threshold_f", 75))
            unit = reading.get("unit", "").upper()
            current_temp = adjusted_current
            threshold_to_use = threshold_f
            if unit == "C":
                threshold_to_use = (threshold_f - 32) * (5.0 / 9.0)
            if current_temp > threshold_to_use:
                setpoint_f = threshold_f
                if args.prompt_setpoint:
                    setpoint_f = prompt_setpoint(default_f=threshold_f)
                if args.verbose:
                    print(f"Cooling trigger: current={current_temp}{unit}, setting to {setpoint_f} F")
                set_cooling_setpoint(cfg, headers=headers, setpoint_f=setpoint_f, verbose=args.verbose)
            # Fan on when temp above threshold (uses adjusted temp).
            fan_on_threshold_f = float(cfg.get("fan_on_above_f", 78))
            fan_on_threshold = fan_on_threshold_f if unit != "C" else (fan_on_threshold_f - 32) * (5.0 / 9.0)
            if current_temp > fan_on_threshold:
                set_fan_mode(cfg, headers=headers, mode="on", verbose=args.verbose)
            # Fan circulate when temp drops below threshold.
            fan_threshold_f = float(cfg.get("fan_circulate_below_f", 70))
            fan_threshold_to_use = fan_threshold_f if unit != "C" else (fan_threshold_f - 32) * (5.0 / 9.0)
            if current_temp <= fan_threshold_to_use:
                set_fan_mode(cfg, headers=headers, mode="circulate", verbose=args.verbose)
    except Exception as exc:
        print(f"Failed to read thermostat temperature: {exc}", file=sys.stderr)
        sys.exit(1)

    unit = f" {reading['unit']}" if reading.get("unit") else ""
    print("Seam Thermostat Reading")
    print("------------------------")
    print(f"Current: {reading['current_temperature']}{unit} ({payload.get('reported_at', 'unknown time')})")
    target = reading.get("target_temperature")
    if target is not None:
        print(f"Target : {target}{unit}")
    mode = reading.get("mode")
    if mode:
        print(f"Mode   : {mode}")

    # Append telemetry to sheet at the very end.
    try:
        append_thermostat_row(
            cfg,
            reading,
            payload,
            entry_type=entry_type,
            studio=request_studio,
            expiration_local=expiration_local,
        )
    except Exception as exc:
        print(f"[sheet] Failed to log telemetry: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
