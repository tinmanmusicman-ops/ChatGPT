from  __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import json
import os
import logging
import math
import mimetypes
import re
import shutil
from datetime import datetime

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from googleapiclient.http import MediaInMemoryUpload

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR_NAME = "chart hist"
ARCHIVE_DIR = SCRIPT_DIR.parent / "Web" / ARCHIVE_DIR_NAME
INLINE_CLIENT_SCRIPT_DEFAULT = False
NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")
DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m-%d-%Y %H:%M:%S",
    "%A %m/%d/%Y %H:%M",
)


def _col_to_index(col: str) -> int:
    idx = 0
    for char in col.upper():
        if "A" <= char <= "Z":
            idx = idx * 26 + (ord(char) - ord("A") + 1)
    return idx


def _extract_letters(cell: str) -> str:
    return "".join(ch for ch in cell if ch.isalpha())


def _ensure_range_includes(range_value: str, column: str) -> str:
    if not range_value:
        return range_value
    if "!" in range_value:
        sheet, part = range_value.split("!", 1)
        prefix = f"{sheet}!"
    else:
        part = range_value
        prefix = ""
    if ":" in part:
        start_cell, end_cell = part.split(":", 1)
    else:
        start_cell = part
        end_cell = part
    end_letters = _extract_letters(end_cell) or _extract_letters(start_cell) or "A"
    target_idx = _col_to_index(column)
    if _col_to_index(end_letters) < target_idx:
        digit_part = "".join(ch for ch in end_cell if ch.isdigit())
        end_cell = f"{column}{digit_part}"
    new_part = f"{start_cell}:{end_cell}" if ":" in part else end_cell
    return f"{prefix}{new_part}"


def _load_global_root() -> Path:
    shared_config = SCRIPT_DIR.parents[1] / "shared" / "Global.json"
    if not shared_config.exists():
        return SCRIPT_DIR.parents[3]
    payload = json.loads(shared_config.read_text(encoding="utf-8"))
    install_dir = payload.get("InstallDir")
    if install_dir:
        return Path(install_dir)
    return SCRIPT_DIR.parents[3]


WORKSPACE_ROOT = _load_global_root()
AI_BOTS_ROOT = WORKSPACE_ROOT / "ai-bots"
GLOBAL_CONFIG_PATH = AI_BOTS_ROOT / "shared" / "Global.json"
TOKEN_PATH = AI_BOTS_ROOT / "shared" / "Tokens.json"
TEMP_DIR = AI_BOTS_ROOT / "Temp"
DRIVE_FOLDER_NAME = "Thermostat Dashboards"


def _load_shared_config() -> dict:
    if not GLOBAL_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing shared config at {GLOBAL_CONFIG_PATH}")
    payload = json.loads(GLOBAL_CONFIG_PATH.read_text(encoding="utf-8"))
    return payload


def _normalize_flag(value, default=True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered in ("1", "true", "t", "yes", "y", "on")
    if value is None:
        return bool(default)
    return bool(value)


def _load_float(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


GLOBAL_SHARED_CONFIG = _load_shared_config()
GIT_TEST_FLAG = _normalize_flag(GLOBAL_SHARED_CONFIG.get("GitTestFlag"), True)

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = base_dir / "config.json"
BOT_ASSETS_CONFIG = base_dir.parent / "bot-assets" / "config.json"
_DEFAULTS = {
    "spreadsheet_id": "",
    "spreadsheet_name": "",
    "sheet_tab": "Sheet1",
    "data_range": "A:J",  # columns range within the sheet tab
    "delete_temp_files": False,
    "cost_per_minute": 0.05,
}

def _load_dash_config() -> dict:
    """Load sheet config from Thermostats config.json, then bot-assets/config.json, then defaults."""
    cfg_candidates = [
        ("local", CONFIG_PATH),
        ("bot-assets", BOT_ASSETS_CONFIG),
    ]
    for label, path in cfg_candidates:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                logger.info("Loaded dashboard config from [%s] %s", label, path)
                return payload
            except Exception as exc:
                logger.warning("Unable to read %s (%s); trying next option", path, exc)
    logger.warning("No config found; using defaults")
    return {}

cfg_payload = _load_dash_config()

GOOGLE_SHEET_ID = cfg_payload.get("spreadsheet_id", _DEFAULTS["spreadsheet_id"])
GOOGLE_SHEET_NAME = (
    cfg_payload.get("spreadsheet_name")
    or cfg_payload.get("google_sheet_name")
    or _DEFAULTS["spreadsheet_name"]
)
SHEET_TAB = cfg_payload.get("sheet_tab", _DEFAULTS["sheet_tab"])
DATA_RANGE = cfg_payload.get("data_range", _DEFAULTS["data_range"])
DATA_RANGE = _ensure_range_includes(DATA_RANGE, "J")
DATA_RANGE = _ensure_range_includes(DATA_RANGE, "L")
DELETE_TEMP_FILES = bool(cfg_payload.get("delete_temp_files", _DEFAULTS["delete_temp_files"]))
COST_PER_MINUTE_CANDIDATE = cfg_payload.get("cost_per_minute")
if COST_PER_MINUTE_CANDIDATE is None:
    COST_PER_MINUTE_CANDIDATE = cfg_payload.get("CostPerMinute")
COST_PER_MINUTE = _load_float(COST_PER_MINUTE_CANDIDATE, _DEFAULTS["cost_per_minute"])
# Allow debugging with inline JS via config or env; defaults to external script.
inline_flag_cfg = cfg_payload.get("inline_client_script", cfg_payload.get("InlineClientScript"))
INLINE_CLIENT_SCRIPT = _normalize_flag(
    os.environ.get("INLINE_CLIENT_SCRIPT", inline_flag_cfg),
    default=INLINE_CLIENT_SCRIPT_DEFAULT,
)

HISTORY_WINDOW = 24
CHART_METRIC_INDEX = 1  # Fallback index; overridden to "Current Temperature" if present


def _load_credentials() -> Credentials:
    info = GLOBAL_SHARED_CONFIG
    logger.info("Loaded service account credentials from %s", GLOBAL_CONFIG_PATH)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return creds


def get_sheets_service():
    creds = _load_credentials()
    logger.info("Building Sheets service client")
    return build("sheets", "v4", credentials=creds)


def get_drive_service():
    creds = _load_credentials()
    logger.info("Building Drive service client")
    return build("drive", "v3", credentials=creds)


def resolve_sheet_id() -> str:
    """Prefer explicit ID; otherwise resolve by file name."""
    if GOOGLE_SHEET_ID:
        logger.info("Using sheet ID from config: %s", GOOGLE_SHEET_ID)
        return GOOGLE_SHEET_ID
    if not GOOGLE_SHEET_NAME:
        raise SystemExit("Set either google_sheet_id or google_sheet_name in config.json")
    drive = get_drive_service()
    escaped = GOOGLE_SHEET_NAME.replace("'", "\\'")
    query = f"name = '{escaped}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    resp = (
        drive.files()
        .list(q=query, spaces="drive", fields="files(id,name)", pageSize=1)
        .execute()
    )
    files = resp.get("files", [])
    if not files:
        raise SystemExit(f"No spreadsheet found with name '{GOOGLE_SHEET_NAME}'")
    logger.info("Resolved sheet name '%s' to ID %s", GOOGLE_SHEET_NAME, files[0]["id"])
    return files[0]["id"]


def _load_drive_credentials() -> Credentials:
    """Load user OAuth credentials from shared Tokens.json for Drive uploads."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"Missing OAuth token file at {TOKEN_PATH}")
    token_info = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(token_info, scopes=DRIVE_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            logger.info("Refreshing Drive access token")
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise FileNotFoundError(
                f"Token at {TOKEN_PATH} is invalid/expired and has no refresh token"
            )
    return creds


def get_drive_upload_service():
    creds = _load_drive_credentials()
    logger.info("Building Drive upload service client")
    return build("drive", "v3", credentials=creds)


def get_or_create_drive_folder(service, folder_name: str) -> str:
    escaped = folder_name.replace("'", "\\'")
    query = (
        f"name = '{escaped}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id,name)", pageSize=5)
        .execute()
    )
    files = resp.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logger.info("Found existing folder %s (%s)", folder_name, folder_id)
        return folder_id

    metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    created = service.files().create(body=metadata, fields="id,name").execute()
    folder_id = created["id"]
    logger.info("Created folder %s (%s)", folder_name, folder_id)
    return folder_id


def _next_version_name(desired: str, existing_names: List[str]) -> str:
    if desired not in existing_names:
        return desired
    stem = Path(desired).stem
    suffix = Path(desired).suffix
    counter = 2
    candidate = f"{stem}_v{counter}{suffix}"
    while candidate in existing_names:
        counter += 1
        candidate = f"{stem}_v{counter}{suffix}"
    return candidate


def upload_or_version_file(
    service,
    folder_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
) -> Tuple[str, str]:
    escaped = filename.replace("'", "\\'")
    query = f"'{folder_id}' in parents and name = '{escaped}' and trashed = false"
    resp = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id,name)", pageSize=1)
        .execute()
    )
    existing = resp.get("files", [])
    media = MediaInMemoryUpload(content, mimetype=mime_type, resumable=False)
    body = {"name": filename, "parents": [folder_id]}
    if existing:
        file_id = existing[0]["id"]
        updated = (
            service.files()
            .update(fileId=file_id, media_body=media, fields="id,name")
            .execute()
        )
        logger.info("Replaced %s (file id %s)", filename, updated.get("id"))
        return updated.get("id"), filename
    created = service.files().create(body=body, media_body=media, fields="id,name").execute()
    file_id = created["id"]
    logger.info("Uploaded %s (file id %s)", filename, file_id)
    return file_id, filename


def push_dashboard_to_drive(html_path: Path, timestamp_suffix: Optional[str] = None) -> str:
    service = get_drive_upload_service()
    folder_id = get_or_create_drive_folder(service, DRIVE_FOLDER_NAME)
    mime_type, _enc = mimetypes.guess_type(html_path.name)
    mime_type = mime_type or "text/html"
    content = html_path.read_bytes()
    drive_name = html_path.name
    if timestamp_suffix:
        drive_name = f"{timestamp_suffix}{html_path.suffix}"
    file_id, target_name = upload_or_version_file(
        service, folder_id, drive_name, content, mime_type
    )
    logger.info(
        "Drive link: https://drive.google.com/file/d/%s/view (stored as %s)",
        file_id,
        target_name,
    )
    return file_id


def git_autopush(html_path: Path, extra_paths: Optional[List[Path]] = None) -> None:
    """Stage, commit, and push the generated dashboard copy."""
    if not GIT_TEST_FLAG:
        logger.info("Skipping git autopush because GitTestFlag is false")
        return
    repo_root = Path(__file__).resolve().parents[2]
    html_rel = html_path.relative_to(repo_root)
    paths_to_add = [html_rel]
    if extra_paths:
        for extra in extra_paths:
            paths_to_add.append(extra.relative_to(repo_root))
    for target in paths_to_add:
        subprocess.run(["git", "add", str(target)], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Auto-update: {html_rel.name}", "--allow-empty"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(["git", "push", "origin", "develop"], cwd=repo_root, check=True)


def fetch_sheet_data() -> Tuple[List[str], List[str], List[List[str]]]:
    """Return headers, latest row, and history rows."""
    sheet_id = resolve_sheet_id()
    service = get_sheets_service()
    range_ref = f"{SHEET_TAB}!{DATA_RANGE}"
    logger.info("Fetching range %s from sheet %s", range_ref, sheet_id)
    try:
        data = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=range_ref)
            .execute()
        )
    except HttpError as exc:
        # Help the user diagnose bad tab/range issues by showing available sheet tabs.
        try:
            meta = (
                service.spreadsheets()
                .get(spreadsheetId=sheet_id, fields="sheets.properties.title")
                .execute()
            )
            titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
            logger.error(
                "Sheets API error for range %s: %s. Available tabs: %s",
                range_ref,
                exc,
                ", ".join(titles),
            )
        except Exception:
            logger.error("Sheets API error for range %s: %s", range_ref, exc)
        raise
    values = data.get("values", [])
    if not values:
        logger.warning("Sheet returned no values")
        return [], [], []
    headers = values[0]
    rows = values[1:]
    latest_row = rows[-1] if rows else []
    history_rows = rows[-HISTORY_WINDOW:] if rows else []
    logger.info("Retrieved %d headers, %d total rows", len(headers), len(rows))
    return headers, latest_row, history_rows


def _filter_hourly_rows(rows: List[List[str]], step: int = 12) -> List[List[str]]:
    """Keep roughly hourly samples (every `step` rows) plus the latest row."""
    if not rows or step <= 0:
        return rows
    filtered: List[List[str]] = []
    for idx, row in enumerate(rows):
        if idx % step == 0 or idx == len(rows) - 1:
            filtered.append(row)
    return filtered


def build_dashboard_html(
    headers: List[str],
    latest_row: List[str],
    history_rows: List[List[str]],
    output_path: Path,
) -> str:
    def _safe_float(val: str) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            text = str(val).strip() if val is not None else ""
            if text:
                match = NUMERIC_RE.search(text)
                if match:
                    try:
                        return float(match.group(0))
                    except ValueError:
                        pass
            logger.debug("Non-numeric chart value %r; defaulting to 0", val)
            return 0.0

    def _format_chart_label(value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime("%a")
            except ValueError:
                continue
        text = text.split(" ");
        return text[0] + " " + text[1] + " " + text[2] + "     " + text[4] + " " + text[5] 

    def _format_card_timestamp(value: str) -> str:
        """Short, fixed timestamp for card display to reduce wrapping."""
        text = str(value or "").strip()
        if not text:
            return ""
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime("%m/%d %I:%M %p")
            except ValueError:
                continue
        return text

    title = "Lockout Music Studios Oceanside CA"
    def _find_index(keywords: Tuple[str, ...]) -> Optional[int]:
        for idx, header in enumerate(headers):
            if not header:
                continue
            value = header.strip().lower()
            for keyword in keywords:
                if keyword in value:
                    return idx
        return None

    setpoint_idx = _find_index(("cooling set point", "cooling setpoint", "set point", "d"))
    actual_idx = _find_index(("Building Temperature", "actual temperature", "temperature"))
    if actual_idx is not None and actual_idx == setpoint_idx:
        actual_idx = None
    setpoint_label = "Set Point"
    actual_label = (
        headers[actual_idx] if actual_idx is not None and len(headers) > actual_idx else "Building Temperature"
    )
    actual_card_label = "Building Temperature"
    outside_idx = _find_index(("outside temperature", "outside temp", "exterior temperature", "outdoor temp"))
    outside_label = (
        headers[outside_idx] if outside_idx is not None and len(headers) > outside_idx else "Outside Temp"
    )

    fan_idx = _find_index(("fan", "fan setting", "fan mode"))
    cooling_idx = _find_index(
        ("equipment status", "equipment status", "status", "equipment", "cooling status")
    )
    timestamp_idx = _find_index(("timestamp",))
    type_idx = _find_index(("type",))
    FAN_LABELS = ["Auto", "Circulate", "On"]
    COOLING_LABELS = ["Idle", "Cooling"]

    def _fan_value(row: List[str]) -> Optional[str]:
        if fan_idx is None or fan_idx >= len(row):
            return None
        val = str(row[fan_idx]).strip().lower()
        if not val:
            return None
        if "auto" in val:
            return "A"
        if "circulate" in val or "cir" in val:
            return "C"
        if val in ("on", "fan", "low", "high") or "run" in val:
            return "O"
        return None

    def _cooling_value(row: List[str]) -> Optional[int]:
        if cooling_idx is None or cooling_idx >= len(row):
            return None
        val = str(row[cooling_idx]).strip().lower()
        if not val:
            return None
        return 1 if "cool" in val else 0

    def _extract_clamped(idx: Optional[int], row: List[str]) -> Optional[float]:
        if idx is None or idx >= len(row):
            return None
        val = _safe_float(row[idx])
        if 45 <= val <= 100:
            return val
        return None

    chart_labels = [_format_chart_label(row[0] if row else "") for row in history_rows]
    setpoint_series = [_extract_clamped(setpoint_idx, row) for row in history_rows]
    actual_series = [_extract_clamped(actual_idx, row) for row in history_rows]
    fan_series = [_fan_value(row) for row in history_rows]
    outside_series = []
    outside_flags = []
    outside_flag_day_chars = []
    for row in history_rows:
        raw_value = (
            str(row[outside_idx]).strip()
            if outside_idx is not None and outside_idx < len(row)
            else ""
        )
        flag = raw_value[:1].upper() if raw_value else ""
        day_char = raw_value[1].upper() if len(raw_value) > 1 else "D"
        outside_flags.append(flag)
        outside_flag_day_chars.append(day_char)
        outside_series.append(_extract_clamped(outside_idx, row))
    cooling_series = [_cooling_value(row) for row in history_rows]
    cooling_label = (
        headers[cooling_idx]
        if cooling_idx is not None and len(headers) > cooling_idx
        else "Status"
    )
    condenser_idx = _find_index(("condenser minutes", "condenser runtime"))
    condenser_minutes_series = []
    for row in history_rows:
        if condenser_idx is None or condenser_idx >= len(row):
            condenser_minutes_series.append(None)
            continue
        value = row[condenser_idx]
        try:
            condenser_minutes_series.append(float(value))
        except (TypeError, ValueError):
            condenser_minutes_series.append(_safe_float(str(value)))
    total_condenser_minutes = sum(
        v for v in condenser_minutes_series if isinstance(v, (int, float)) and not math.isnan(v)
    )
    if isinstance(total_condenser_minutes, (int, float)) and math.isfinite(total_condenser_minutes):
        if float(total_condenser_minutes).is_integer():
            total_condenser_display = str(int(total_condenser_minutes))
        else:
            total_condenser_display = f"{total_condenser_minutes:.1f}"
        total_condenser_minutes_value = total_condenser_minutes
    else:
        total_condenser_display = ""
        total_condenser_minutes_value = 0
    total_condenser_cost_value = total_condenser_minutes_value * COST_PER_MINUTE
    total_condenser_cost_display = f"${total_condenser_cost_value:,.2f}"
    if total_condenser_cost_value < 5:
        condenser_cost_class = "cost-ok"
    elif total_condenser_cost_value < 10:
        condenser_cost_class = "cost-warm"
    elif total_condenser_cost_value < 15:
        condenser_cost_class = "cost-hot"
    else:
        condenser_cost_class = "cost-red"
    chart_data = []
    for label, sp_val, actual_val in zip(chart_labels, setpoint_series, actual_series):
        selected = sp_val if sp_val is not None else actual_val
        if selected is not None:
            chart_data.append({"label": label, "value": selected})
    latest_actual_value = (
        _safe_float(latest_row[actual_idx]) if actual_idx is not None and actual_idx < len(latest_row) else None
    )
    latest_setpoint_value = (
        _safe_float(latest_row[setpoint_idx]) if setpoint_idx is not None and setpoint_idx < len(latest_row) else None
    )
    latest_outside_value = (
        _safe_float(latest_row[outside_idx]) if outside_idx is not None and outside_idx < len(latest_row) else None
    )
    latest_fan_value = _fan_value(latest_row)
    latest_cooling_value = _cooling_value(latest_row)
    latest_outside_raw = (
        str(latest_row[outside_idx]).strip() if outside_idx is not None and outside_idx < len(latest_row) else ""
    )
    latest_outside_flag_day_char = (
        latest_outside_raw[1].upper() if len(latest_outside_raw) > 1 else "D"
    )
    latest_outside_daylight = latest_outside_flag_day_char != "N"
    generated_at = datetime.now()
    generated_label = generated_at.strftime("%A %b %d %Y %I:%M:%S %p")
    generated_slug = generated_at.strftime("%Y-%m-%d")
    archive_slugs = set()
    if ARCHIVE_DIR.exists():
        for pattern in ("*.html", "*.json"):
            for entry in ARCHIVE_DIR.glob(pattern):
                slug = entry.stem
                if slug:
                    archive_slugs.add(slug)
    archive_slugs.add(generated_slug)
    def _format_archive_label(slug: str) -> str:
        try:
            parsed = datetime.strptime(slug, "%Y-%m-%d")
            return parsed.strftime("%b %d, %Y")
        except ValueError:
            return slug
    archive_dates = [
        {"slug": slug, "label": _format_archive_label(slug)}
        for slug in sorted(archive_slugs, reverse=True)
    ]
    outside_display_value = ""
    if latest_outside_value is not None:
        outside_display_value = (
            str(int(latest_outside_value))
            if float(latest_outside_value).is_integer()
            else f"{latest_outside_value:.1f}"
        )
    dashboard_payload = {
        "headers": headers,
        "latestRow": latest_row,
        "history": chart_data,
        "chartLabels": chart_labels,
        "setpoint": setpoint_series,
        "actual": actual_series,
        "setpointLabel": setpoint_label,
        "actualLabel": actual_label,
        "fan": fan_series,
        "fanLegend": FAN_LABELS,
        "outside": outside_series,
        "outsideLabel": outside_label,
        "outsideFlags": outside_flags,
        "outsideFlagDayChars": outside_flag_day_chars,
        "cooling": cooling_series,
        "coolingLegend": COOLING_LABELS,
        "coolingLabel": cooling_label,
        "condenserMinutes": condenser_minutes_series,
        "totalCondenserMinutes": total_condenser_display,
        "totalCondenserMinutesValue": total_condenser_minutes_value,
        "totalCondenserCost": total_condenser_cost_display,
        "totalCondenserCostValue": total_condenser_cost_value,
        "condenserCostPerMinute": COST_PER_MINUTE,
        "latestActual": latest_actual_value,
        "latestSetpoint": latest_setpoint_value,
        "latestOutside": latest_outside_value,
        "latestOutsideRaw": latest_outside_raw,
        "latestOutsideDaylight": latest_outside_daylight,
        "latestOutsideFlagDayChar": latest_outside_flag_day_char,
        "latestFan": latest_fan_value,
        "latestCooling": latest_cooling_value,
        "generatedTimestamp": generated_label,
        "generatedDateSlug": generated_slug,
        "archiveDates": archive_dates,
        "archivePath": ARCHIVE_DIR_NAME,
    }
    data_json = json.dumps(dashboard_payload)
    latest_outside_raw = (
        str(latest_row[outside_idx]).strip() if outside_idx is not None and outside_idx < len(latest_row) else ""
    )
    cards = ""
    seen_labels = set()
    for idx, label in enumerate(headers):
        if idx == actual_idx:
            display_label = actual_card_label
        else:
            display_label = label or ""
        if display_label in seen_labels:
            continue
        seen_labels.add(display_label)
        if idx == outside_idx:
            value = outside_display_value
        elif idx == condenser_idx:
            display_label = "Condenser Minutes Past Hour"
            value = total_condenser_display or "0"
        else:
            value = latest_row[idx] if idx < len(latest_row) else ""
        if idx == timestamp_idx:
            value = _format_card_timestamp(value)
        if value is None:
            value = ""
        metric_attr = ""
        fan_state_class = ""
        if idx == actual_idx:
            metric_attr = ' data-metric="actual"'
        elif idx == setpoint_idx:
            metric_attr = ' data-metric="setpoint"'
        elif idx == fan_idx:
            metric_attr = ' data-metric="fan"'
            if latest_fan_value:
                fan_state_class = f" fan-state-{latest_fan_value.lower()}"
        elif idx == cooling_idx:
            metric_attr = ' data-metric="cooling"'
        elif idx == outside_idx:
            metric_attr = ' data-metric="outside"'
        elif idx == condenser_idx:
            metric_attr = ' data-metric="condenser-minutes"'
        elif idx == timestamp_idx:
            metric_attr = ' data-metric="timestamp"'
        elif idx == type_idx:
            metric_attr = ' data-metric="type"'
        cards += f"""
        <div class="metric-card{fan_state_class}"{metric_attr}>
          <div class="label">{display_label}</div>
          <div class="value">{value}</div>
        </div>
        """
    script_path = SCRIPT_DIR / "dashboard_client.js"
    web_output_dir = base_dir.parent / "Web"
    if output_path.parent == web_output_dir:
        # HTML generated for the public Web directory should reference the script in the sibling scripts folder.
        script_src_url = "../scripts/dashboard_client.js"
    else:
        script_rel_to_output = Path(
            os.path.relpath(script_path, start=output_path.parent)
        )
        script_src_url = script_rel_to_output.as_posix()
    if INLINE_CLIENT_SCRIPT:
        client_js = script_path.read_text(encoding="utf-8")
        script_block = f"""    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script id="dashboard-data-inline" type="application/json">
{data_json}
    </script>
    <script id="dashboard-client" data-archive-path="{ARCHIVE_DIR_NAME}">
{client_js}
    </script>
    """
    else:
        script_block = f"""    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script id="dashboard-data-inline" type="application/json">
{data_json}
    </script>
    <script id="dashboard-client" data-archive-path="{ARCHIVE_DIR_NAME}" src="{script_src_url}"></script>
    """

    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap">
    <style>
      body {{
        forced-color-adjust: none;
        -webkit-text-fill-color: initial;
        color: inherit;
        margin: 0;
        font-family: 'Inter', system-ui, sans-serif;
        background: linear-gradient(to bottom, #453082, #71688c);
        color: #f4f6ff;
      }}
      .container {{
        max-width: 900px;
        margin: 1px auto;
        padding: 1px;
        background: transparent;
        border-radius: 16px;
      }}
      h1 {{
        margin: 0 0 16px;
        font-size: 32px;
      }}
      .header-row {{

        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
      }}
      .timestamp-row {{
        display: flex;
        justify-content: flex-end;
        margin-bottom: 18px;
      }}
      .date-display {{
        font-size: 14px;
        letter-spacing: 0.08em;
        opacity: 0.8;
        text-transform: uppercase;
        white-space: nowrap;
      }}
      .chartjs-legend {{
      margin-top: -40px;
      }}
      .header-label {{

        font-size: 80px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        opacity: 0.95;
        white-space: nowrap;
      }}
      #Company {{

        width: 80%;
        font-size: 60px;
        text-align: center;
        padding: 4px 0;
      }}

#chart-history-months {{
height: 5px
padding: 0;
font-size; 8PX;
line-height: 1
height: auto;
}}

#chart-history-months option {{
height: 5px
padding: 1 3px;
font-size; 8PX;
line-height: 1;
}}

      .logo-placeholder {{

        width: 190px;
        height: 126px;

                border-radius: 0px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 13px;
        color: #66ff99;
      }}
      .logo-placeholder img {{

                max-width: 100%;
        max-height: 100%;
        object-fit: contain;
      }}
      .card-grid {{

        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 16px;
      }}
      .hands-logo-slot {{
        display: none;
        width: 0;
        height: 0;
        margin: 0;
        padding: 0;
      }}
      .metric-card {{
        background: #2b2b30;
        color: #f5f7ff;
        border: 1px solid #3a3a40;
        border-radius: 12px;
        padding: 16px;
        min-height: 70px;
      }}
      .metric-card[data-metric="fan"] {{
        background: #f7e9b5;
        color: #2b2b30;
        border-color: #d9c36a;
      }}
      .metric-card.fan-state-c[data-metric="fan"] {{
        background: #fffde6;
        color: #5a4a12;
        border-color: #e9dca8;
      }}
      .metric-card[data-metric="fan"] .label {{
        color: #6a5a1f;
        opacity: 0.9;
      }}
      .metric-card.fan-state-c[data-metric="fan"] .label {{
        color: #5a4a12;
      }}
      .metric-card[data-metric="fan"] .value {{
        color: #2b2b30;
      }}
      .metric-card.fan-state-c[data-metric="fan"] .value {{
        color: #5a4a12;
      }}
      .metric-card[data-metric="timestamp"] .value {{
        font-size: 16px;
      }}
      .metric-card[data-metric="type"] .value {{
        font-size: 16px;
      }}
      .metric-card .label {{
        font-size: 14px;
        opacity: 0.7;
      }}
      .metric-card .value {{
        font-size: 24px;
        font-weight: 600;
      }}
      .metric-card.sunny-image,
      .metric-card.sunny-image .label,
      .metric-card.sunny-image .value {{
        background: transparent !important;
        border-color: transparent !important;
      }}
      .metric-card[data-metric="outside"].sunny-image::after {{
        content: "";
        position: absolute;
        inset: 0;
        border-radius: inherit;
        pointer-events: none;
        background: radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.25), rgba(255, 255, 255, 0) 70%);
        mix-blend-mode: screen;
      }}
      .metric-card[data-metric="outside"] {{
        position: relative;
        padding-right: 160px;
      }}
      .metric-card .sunny-graphic {{
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        width: 150px;
        pointer-events: none;
        background-repeat: no-repeat;
        background-position: center;
        background-size: cover;
      }}
      .metric-card[data-metric="outside"] {{
        position: relative;
        padding-right: 140px;
      }}
      .metric-card .sunny-graphic {{
        position: absolute;
        right: 12px;
        top: 50%;
        width: 120px;
        height: 90px;
        transform: translateY(-50%);
        pointer-events: none;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
      }}
      .history-panel {{
        margin-top: 8px;
        background: rgba(255,255,255,0.02);
        border-radius: 12px;
        padding: 16px;
        border: 1px solid rgba(255,255,255,0.08);
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
      }}
      .hands-logo-top {{
        width: 195px;
        height: 120px;
        background-image: url("../../../Images/Hands.png");
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        position: absolute;
        right: 40px;
        top: -32px;
        opacity: 1;
        transition: opacity 0.6s ease;
      }}
      .hands-logo-top.hidden {{
        opacity: 0;
      }}
      button {{
        background: #66ff99;
        border: none;
        color: #051b05;
        padding: 10px 18px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        transition: transform 0.2s ease;
      }}
      #toggle-history {{
        background: #111117;
        color: #c7cbcf;
        border: 1px solid #1f1f26;
        padding: 10px 18px;
        border-radius: 8px;
        font-weight: 600;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        transition: background 0.3s ease, color 0.3s ease;
      }}
      #toggle-history.history-visible {{
        background: #063016;
        color: #dceadf;
        border-color: #063016;
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
      }}
      button:active {{
        transform: scale(0.98);
      }}
      #chartcontrols {{
        width: 900px;

        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 4px 8px;
        margin-top: 20px;
        margin-bottom: 48px;
        font-size: 14px;
        color: #f4f6ff;
        height: 100px;
      }}
      .chart-control {{
        border: 1px solid #1a1a20;
        background: #0d0d12;
        color: #6f7176;
        padding: 6px 12px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
      }}
      .chart-control.active {{
        background: #0d0d12;
        color: #66ff99;
        border-color: #1a1a20;
        box-shadow: none;
      }}
      #autoplay-toggle {{
        color: #66ff99;
      }}
      #autoplay-toggle.off {{
        color: #ff6666;
      }}
      .condenser-runtime {{
        position: absolute;
        top: 24px;
        right: 34px;
        text-align: right;
        font-size: 12px;
        color: #b1ffce;
        letter-spacing: 0.06em;
      }}
      .condenser-runtime .value {{
        font-size: 16px;
        font-weight: 600;
      }}
      .condenser-runtime .cost-label {{
        font-size: 10px;
        opacity: 0.7;
        margin-top: 6px;
      }}
      .condenser-runtime .cost-value {{
        font-size: 16px;
        font-weight: 600;
        color: #fff5c7;
        background: linear-gradient(to bottom, #241B44, #332459);
        padding: 2px 6px;
        border-radius: 6px;
      }}
      .condenser-runtime .cost-value.cost-ok {{
        color: #00C853;
      }}
      .condenser-runtime .cost-value.cost-warm {{
        color: #ffcc99;
      }}
      .condenser-runtime .cost-value.cost-hot {{
        color: #f08a24;
      }}
      .condenser-runtime .cost-value.cost-red {{
        color: #FF1744;
      }}
      #history-chart {{

        gap: 20px;
        display: none;
        width: 100% !important;
        height: 100% !important;
        background: linear-gradient(
          to bottom,
          #0F0B1A 0%,
          #2A1E55 40%,
          #332459 75%
        );
      }}
      .chart-wrap {{
        height: 600px;
        margin: 8px auto 0;
        background: linear-gradient(
          to bottom,
          #0F0B1A 0%,
          #2A1E55 40%,
          #332459 75%
        );
        position: relative;
        max-width: 900px;
        width: 100%;
        padding: 12px 0 18px;
        box-sizing: border-box;
        background-image:
          url("../../../Images/Hands.png"),
          linear-gradient(
            to bottom,
            #0F0B1A 0%,
            #2A1E55 40%,
            #332459 75%
          );
        background-size: contain, cover;
        background-repeat: no-repeat, no-repeat;
        background-position: center top, center;
      }}
      .fan-legend-image {{
      }}
      #logo2 {{
        list-style: none;
        margin: 0;
        padding: 0;
        width: 50px;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }}
      #logo2 li {{
        font-size: 10px;
        color: #f4f6ff;
      }}
      .chart-history {{
        position: absolute;
        top: -86px;
        right: 0;
        background: #2f3136;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 14px;
        padding: 12px 14px;
        max-height: 220px;
        width: 360px;
        overflow-y: visible;
        box-shadow:
          0 14px 30px rgba(0, 0, 0, 0.45),
          inset 0 1px 2px rgba(255, 255, 255, 0.15);
        color: #fff5c7;
        border-top-color: rgba(255, 255, 255, 0.6);
        border-left-color: rgba(255, 255, 255, 0.45);
        border-bottom-color: rgba(0, 0, 0, 0.45);
        border-right-color: rgba(0, 0, 0, 0.3);
        display: flex;
        gap: 12px;
        align-items: flex-start;
      }}
      .history-months {{
        width: 150px;
        max-height: 140px;
        overflow-y: auto;
        padding-right: 4px;
        border-right: 1px solid rgba(255, 255, 255, 0.18);
      }}
      .history-months h5 {{
        margin: 0 0 6px;
        font-size: 12px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: #fff5c7;
      }}
      .history-months-list {{
        list-style: none;
        margin: 0;
        padding: 0;
        display: none;
        flex-direction: column;
        gap: 2px;
        max-height: 120px;
        overflow-y: auto;
      }}
      .history-lists-row:hover .history-months-list,
      .history-months:focus-within .history-months-list {{
        display: flex;
      }}
      .history-months-list li {{
        margin: 0;
        padding: 0;
      }}
      .history-months-list button {{
        all: unset;
        width: 100%;
        padding: 2px 6px;
        border-radius: 8px;
        background: rgba(0, 0, 0, 0.25);
        color: #fff5c7;
        font-size: 11px;
        letter-spacing: 0.03em;
        line-height: 1.1;
        cursor: pointer;
        transition: background 0.2s ease, color 0.2s ease;
      }}
      .history-months-list button:hover,
      .history-months-list button:focus-visible {{
        background: rgba(102, 255, 153, 0.12);
        color: #e8ffe8;
      }}
      .history-months-list button.active {{
        background: rgba(102, 255, 153, 0.25);
        color: #fff;
      }}
      .history-list-column {{
        flex: 1;
        max-height: 24px;
        overflow: hidden;
        min-width: 200px;
        min-height: 0;
        padding: 0;
        transition: max-height 0.2s ease, padding 0.2s ease;
      }}
      .history-list-column.expanded {{
        max-height: 220px;
        overflow-y: auto;
        padding: 4px 0;
      }}
      .history-month {{
        margin-bottom: 6px;
      }}
      .history-month-header {{
        display: flex;
        justify-content: flex-start;
        gap: 6px;
        align-items: center;
        margin: 0 0 4px;
      }}
      .history-month-header button {{
        all: unset;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        cursor: pointer;
        color: #fff5c7;
      }}
      .history-month-list {{
        list-style: none;
        margin: 0;
        padding: 0;
        font-size: 11px;
      }}
      .history-month-list.hidden {{
        display: none;
      }}
      .history-lists-row {{
        display: flex;
        gap: 12px;
        align-items: flex-start;
        width: 100%;
      }}
      .chart-history h4 {{
        margin: 0 0 6px;
        font-size: 12px;
        letter-spacing: 0.08em;
        font-weight: 600;
        text-transform: uppercase;
        cursor: pointer;
      }}
      .chart-history-status {{
        font-size: 11px;
        opacity: 0.7;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
      }}
      .chart-history ul {{
        list-style: none;
        margin: 0;
        padding: 0;
        font-size: 11px;
        color: #f4f6ff;
        line-height: 1.4;
      }}
      .chart-history ul button {{
        all: unset;
        width: 100%;
        text-align: left;
        cursor: pointer;
        color: #33ccff;
        font-size: 11px;
        letter-spacing: 0.04em;
      }}
      .chart-history ul button:hover,
      .chart-history ul button:focus-visible {{
        text-decoration: underline;
      }}
      .chart-history ul button.active {{
        color: #66ff99;
        font-weight: 600;
      }}
      .chart-history ul.hidden {{
        display: none;
      }}
      .note {{
        border: 2px solid;
        margin-top: 12px;
        font-size: 12px;
        opacity: 0.7;
      }}
      #js-log {{
       display: none;
         margin-top: 12px;
        padding: 8px;
        height: 120px;
        border: 1px solid #66ff99;
        background: #111;
        color: #66ff99;
        font-size: 11px;
        overflow-y: auto;
        white-space: pre-wrap;
        width: 100%;
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header-row">
        <div id="Company">Lockout Music Studios  Oceanside</div>
        <div id="Logo"class="logo-placeholder">
          <img src="../../../Images/Hands.png" alt="Logo" />
        </div>
      </div>
      <div class="timestamp-row">
        <div id="dashboard-timestamp" class="date-display">{generated_label}</div>
      </div>
      <div id="Cards" class="card-grid">
        {cards}
      </div>
      <div class="hands-logo-slot" aria-hidden="true">
        <div class="hands-logo-top"></div>
      </div>
        
      <div id="history" class="history-panel">

      <button id="toggle-history">Show History Chart</button>
      <div class="condenser-runtime">
        <div class="label">Total condenser runtime</div>
        <div class="value">{total_condenser_display or "0"} min</div>
        <div class="cost-label">Estimated condenser cost</div>
        <div class="cost-value {condenser_cost_class}">{total_condenser_cost_display or "$0.00"}</div>
      </div>

      <div id="chartcontrols" class="chart-controls">
          <button type="button" class="chart-control" data-mode="setpoint">Set Point</button>
          <button type="button" class="chart-control" data-mode="actual">Building Temp</button>
          <button type="button" class="chart-control" data-mode="outside">Outside Temp</button>
          <button type="button" class="chart-control" data-mode="cooling">AC Status</button>
          <button type="button" class="chart-control" data-mode="fan">Fan Mode</button>
          <button type="button" class="chart-control active" data-mode="both">Combined</button>
          <span>&nbsp;</span>
          <button type="button" class="chart-control" id="autoplay-toggle">Auto-play: On</button>
        </div>
        <div class="chart-wrap">
          <div>
          </div>
          <canvas id="history-chart"></canvas>
          <div class="chart-history" id="chart-history">
            <h4 id="chart-history-toggle">Chart History</h4>
            <div id="chart-history-status" class="chart-history-status"></div>
            <ul id="chart-history-list" class="hidden"></ul>
          </div>
        </div>
        <div class="note">Data source: Google Sheet (last updated when this page was generated).</div>
        <pre id="js-log"></pre>
      </div>
    </div>
    {script_block}

  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    logger.info("Wrote dashboard HTML to %s", output_path)
    return generated_slug, dashboard_payload


def main() -> None:
    headers, latest_row, history_rows = fetch_sheet_data()
    if not headers:
        raise SystemExit("Sheet returned no data; set GOOGLE_SHEET_ID and DATA_RANGE.")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target_path = TEMP_DIR / "dashboard.html"
    generated_suffix, dashboard_payload = build_dashboard_html(
        headers, latest_row, history_rows, target_path
    )
    # Also save a copy in the project folder for external publishing.
    public_dir = base_dir.parent / "Web"
    public_dir.mkdir(parents=True, exist_ok=True)
    public_copy = public_dir / "dashboard_public.html"
    try:
        # Keep a human-readable copy alongside the bot so it can be served or published separately.
        script_path = SCRIPT_DIR / "dashboard_client.js"
        temp_script_src = Path(os.path.relpath(script_path, start=target_path.parent)).as_posix()
        web_script_src = Path(os.path.relpath(script_path, start=public_copy.parent)).as_posix()
        public_html = target_path.read_text(encoding="utf-8")
        if temp_script_src != web_script_src:
            public_html = public_html.replace(temp_script_src, web_script_src, 1)
        public_copy.write_text(public_html, encoding="utf-8")
        logger.info("Wrote public copy to %s", public_copy)
        archive_dir = ARCHIVE_DIR
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_target = archive_dir / f"{generated_suffix}.html"
        shutil.copy2(public_copy, archive_target)
        archive_json = archive_dir / f"{generated_suffix}.json"
        archive_json.write_text(json.dumps(dashboard_payload, indent=2), encoding="utf-8")
        dashboard_data_path = public_dir / "dashboard_data.json"
        dashboard_data_path.write_text(json.dumps(dashboard_payload, indent=2), encoding="utf-8")
        # Automatically stage/commit/push the public HTML and archive copy so repo and remote stay in sync with each generation.
        dashboard_script_path = SCRIPT_DIR / "dashboard_client.js"
        git_autopush(
            public_copy,
            extra_paths=[archive_target, dashboard_data_path, dashboard_script_path],
        )
    except Exception as exc:
        logger.warning("Failed to write or push public copy %s (%s)", public_copy, exc)
    print(f"Dashboard generated at: {target_path.resolve()}")
    logger.info("Dashboard generation complete at %s", target_path.resolve())

    # Push to Drive and clean up local temp copy.
    try:
        file_id = push_dashboard_to_drive(target_path, generated_suffix)
        if DELETE_TEMP_FILES:
            logger.info("Dashboard uploaded to Drive (file id %s); removing local copy", file_id)
            try:
                target_path.unlink()
            except Exception as exc:
                logger.warning("Unable to delete temp file %s (%s)", target_path, exc)
        else:
            logger.info("Dashboard uploaded to Drive (file id %s); kept local copy at %s", file_id, target_path)
    except Exception as exc:
        logger.error("Failed to upload dashboard to Drive: %s", exc)


if __name__ == "__main__":
    main()
