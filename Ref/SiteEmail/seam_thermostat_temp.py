#!/usr/bin/env python3
"""Connect to Seam and report the current thermostat temperature using API key auth."""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import sys
from contextlib import suppress
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Print the current thermostat temperature from Seam."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=script_dir / "config.json",
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
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

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
    return cfg


def request_token(cfg: Dict[str, Any], verbose: bool = False) -> str:
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
    raw = input(f"Enter cooling set point in F (default {default_f}): ").strip()
    if not raw:
        return default_f
    try:
        return float(raw)
    except ValueError:
        print(f"Invalid number '{raw}', using default {default_f}")
        return default_f


def _pick_temp(props: Dict[str, Any], candidates: Tuple[Tuple[str, str], ...]) -> Tuple[Optional[Any], Optional[str]]:
    for key, unit in candidates:
        if key in props and props[key] is not None:
            return props[key], unit
    return None, None


def print_capabilities(device: Dict[str, Any]) -> None:
    caps = device.get("capabilities_supported") or []
    props = device.get("properties") or device
    print("Capabilities:", ", ".join(caps) if caps else "none")
    print("Property keys:", ", ".join(sorted(props.keys())))


def fetch_primary_ac_emails(cfg: Dict[str, Any]) -> list[Dict[str, str]]:
    """Fetch unread Primary emails; return list of dicts with subject/body for messages starting with AC."""
    user = cfg.get("gmail_user") or cfg.get("user")
    password = cfg.get("gmail_app_password") or cfg.get("app_password")
    results: list[Dict[str, str]] = []
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
            typ, msg_data = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subj = str(make_header(decode_header(msg.get("Subject", "")))).strip()
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            body = part.get_payload(decode=True).decode(charset, errors="ignore")
                        except Exception:
                            body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    body = msg.get_payload(decode=True).decode(charset, errors="ignore")
                except Exception:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
            # If subject starts with AC, mark seen and move; otherwise leave unread.
            if subj.upper().startswith("AC"):
                imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Seen)")
                imap.create("Thermostats")
                imap.uid("COPY", uid, "Thermostats")
                imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)")
                imap.expunge()
            else:
                imap.uid("STORE", uid, "-FLAGS.SILENT", "(\\Seen)")
            results.append({"subject": subj, "body": body})
    finally:
        with suppress(Exception):
            imap.logout()
    return results


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
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"Unable to load config: {exc}", file=sys.stderr)
        sys.exit(1)

    emails = fetch_primary_ac_emails(cfg)
    if emails:
        passed = False
        for em in emails:
            subj = em.get("subject", "")
            if len(subj) >= 2 and subj[:2].upper() == "AC":
                passed = True
            print(f"[email] Subject: {subj}")
        if passed:
            print("[email] AC match passed.")
        else:
            print("[email] AC match failed (no subject starting with AC).")
    else:
        print("[email] AC match failed (no matching unread Primary subjects).")

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
        payload = fetch_temperature(cfg, headers=headers, verbose=args.verbose)
        reading = extract_temp_payload(payload)

        if args.show_capabilities:
            print_capabilities(reading.get("_device", {}))

        # Auto-adjust cooling set point if above threshold.
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


if __name__ == "__main__":
    main()
