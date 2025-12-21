from  __future__ import annotations

import argparse
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
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import random

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
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CACHE_DIR = TEMP_DIR / "open_meteo_hourly_cache"


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
TEST_MODE = _normalize_flag(
    cfg_payload.get("test_mode", cfg_payload.get("testMode", cfg_payload.get("test", False))),
    default=False,
)
logger.info("Dashboard test_mode=%s (generates HTML from cached JSON)", TEST_MODE)

HISTORY_WINDOW = 24
CHART_METRIC_INDEX = 1  # Fallback index; overridden to "Current Temperature" if present


def _load_credentials() -> Credentials:
    info = GLOBAL_SHARED_CONFIG
    logger.info("Loaded service account credentials from %s", GLOBAL_CONFIG_PATH)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return creds


def _parse_date_only(value: str) -> date:
    text = (value or "").strip()
    if not text:
        raise ValueError("Empty date value")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value!r} (use YYYY-MM-DD)")


def _daterange_inclusive(start: date, end: date) -> Iterable[date]:
    if end < start:
        raise ValueError(f"End date {end} is before start date {start}")
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _day_condition(target: date) -> str:
    """
    Deterministic day condition from date only (no external/weather dependencies).

    Returns: "full_sun", "mixed", or "rainy".
    """
    seed = int(target.strftime("%Y%m%d"))
    bucket = seed % 10
    if bucket <= 4:
        return "full_sun"
    if bucket <= 7:
        return "mixed"
    return "rainy"


def _fan_mode_for_hour(target: date, hour: int) -> str:
    if not (0 <= hour <= 23):
        raise ValueError(f"Hour out of range: {hour}")

    mmdd = (target.month, target.day)
    if target.month in (7, 8) and target.day >= 1:
        schedule = ((0, 5, "C"), (6, 12, "O"), (13, 18, "A"), (19, 23, "O"))
    elif target.month == 9 and target.day >= 1:
        schedule = ((0, 5, "O"), (6, 12, "C"), (13, 18, "A"), (19, 23, "O"))
    elif target.month == 10 and target.day >= 1:
        schedule = ((0, 5, "O"), (6, 12, "C"), (13, 18, "A"), (19, 23, "O"))
    elif target.month in (4, 5, 6) and target.day >= 1:
        schedule = ((0, 5, "C"), (6, 12, "O"), (13, 19, "A"), (20, 23, "O"))
    elif target.month == 11 and target.day >= 1:
        schedule = ((0, 18, "A"), (19, 23, "O"))
    elif target.month in (12, 1, 2, 3) and target.day >= 1:
        schedule = ((0, 12, "A"), (13, 18, "O"), (19, 23, "C"))
    else:
        schedule = ((0, 23, "A"),)

    for start_hour, end_hour, mode in schedule:
        if start_hour <= hour <= end_hour:
            return mode
    return "A"


def _baseline_anchor_temps(target: date, *, full_sun: bool) -> dict[int, float]:
    if target.month == 7 and target.day >= 1:
        # July is similar to August, but runs ~3°F cooler during the hot afternoon/evening window (~3pm–8pm).
        if full_sun:
            return {5: 65, 6: 65, 13: 73, 16: 72, 17: 74, 19: 77, 23: 70}
        return {5: 65, 6: 65, 13: 73, 16: 71, 17: 72, 19: 73, 23: 70}
    if target.month == 8 and target.day >= 1:
        if full_sun:
            return {5: 65, 6: 65, 13: 73, 16: 75, 17: 77, 19: 80, 23: 70}
        return {5: 65, 6: 65, 13: 73, 16: 74, 17: 75, 19: 76, 23: 70}
    if target.month == 9 and target.day >= 1:
        if full_sun:
            return {5: 65, 6: 70, 13: 77, 16: 78, 17: 80, 19: 77, 23: 70}
        return {5: 65, 6: 70, 13: 73, 16: 75, 17: 76, 19: 75, 23: 70}
    if target.month == 10 and target.day >= 1:
        if full_sun:
            return {5: 68, 6: 70, 13: 76, 16: 77, 17: 79, 19: 80, 23: 70}
        return {5: 68, 6: 65, 13: 70, 16: 72, 17: 73, 19: 74, 23: 70}
    if target.month in (11, 4, 5, 6) and target.day >= 1:
        if full_sun:
            return {5: 65, 6: 65, 13: 70, 16: 75, 17: 77, 19: 77, 23: 68}
        return {5: 65, 6: 65, 13: 70, 16: 70, 17: 72, 19: 73, 23: 68}
    if target.month in (12, 1, 2, 3) and target.day >= 1:
        if full_sun:
            return {5: 65, 6: 65, 13: 70, 16: 73, 17: 75, 19: 73, 23: 70}
        return {5: 63, 6: 62, 13: 68, 16: 69, 17: 70, 19: 68, 23: 65}
    # Fallback: mild daily swing.
    return {5: 68, 6: 68, 13: 72, 16: 74, 17: 74, 19: 72, 23: 70}


def _interpolate_hourly_from_anchors(anchors: dict[int, float]) -> List[float]:
    # Expected anchors include 23 and 5 to bridge midnight (wrap).
    if 23 not in anchors or 5 not in anchors:
        raise ValueError("Anchors must include 23 and 5 for midnight wrap interpolation")

    # Build extended anchor timeline: 0..29 (where 29 represents next-day 5:00 AM).
    anchor_points: List[Tuple[int, float]] = sorted((h, float(v)) for h, v in anchors.items())
    anchor_points.append((29, float(anchors[5])))

    def _interp(x: int) -> float:
        for idx in range(len(anchor_points) - 1):
            x0, y0 = anchor_points[idx]
            x1, y1 = anchor_points[idx + 1]
            if x0 <= x <= x1:
                if x1 == x0:
                    return y0
                ratio = (x - x0) / (x1 - x0)
                return y0 + (y1 - y0) * ratio
        return float(anchor_points[-1][1])

    hourly: List[float] = []
    for hour in range(24):
        x = hour + 24 if hour < 5 else hour
        hourly.append(_interp(x))
    return hourly


def _setpoint_for_hour(target: date, hour: int) -> float:
    # July variant:
    # - default: 75°F
    # - 3pm–8pm: 72°F
    if target.month == 7:
        if hour in (15, 16, 17, 18, 19, 20):
            return 72.0
        return 75.0

    # Summer-ish policy: Aug 1 through Oct 30 (inclusive).
    if target.month == 7 or (target.month == 8 and target.day >= 1) or target.month in (9, 10):
        default = 80.0
        if hour in (13, 14, 15, 16, 17):
            return 75.0
        if hour in (18, 19, 20, 21, 22, 23):
            return 78.0
        return default

    # Winter-ish policy: Nov 1 through Mar 31.
    if target.month in (11, 12, 1, 2, 3):
        default = 75.0
        if hour in (13, 14, 15, 16, 17):
            return 72.0
        if hour in (18, 19, 20, 21, 22, 23):
            return 75.0
        return default

    return 75.0


def _hourly_drop_for_condition(condition: str) -> float:
    if condition == "full_sun":
        return 1.0
    if condition == "mixed":
        return 2.0
    return 4.0


def _daylight_char_for_hour(hour: int) -> str:
    return "D" if 6 <= hour <= 18 else "N"


def _open_meteo_flag(code: int, is_day_flag: int) -> str:
    rain_codes = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    partly_codes = {1, 2, 3}
    overcast_codes = {45, 48}
    is_day = bool(int(is_day_flag))
    if int(code) == 0:
        return "S" if is_day else "N"
    if int(code) in partly_codes:
        return "P"
    if int(code) in overcast_codes:
        return "O"
    if int(code) in rain_codes:
        return "R"
    if 71 <= int(code) <= 77:
        return "O"
    return "O"


def _open_meteo_day_char(is_day_flag: int) -> str:
    return "D" if int(is_day_flag) == 1 else "N"


def _fmt_open_meteo_outside_raw(flag: str, dayc: str, temp_f: float) -> str:
    if float(temp_f).is_integer():
        t = str(int(round(float(temp_f))))
    else:
        t = f"{float(temp_f):.1f}"
    return f"{flag}{dayc}{t} | Open-Meteo"


def _http_get_json(url: str, params: dict) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": "thermostat-dashboard"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _extract_open_meteo_day_hourly(payload: dict, target_day: date) -> tuple[List[float], List[int], List[int], List[float]]:
    h = payload.get("hourly") or {}
    times = h.get("time") or []
    temps = h.get("temperature_2m") or []
    codes = h.get("weather_code") or []
    is_day = h.get("is_day") or []
    precip = h.get("precipitation") or [0.0] * len(times)
    if not (len(times) == len(temps) == len(codes) == len(is_day) == len(precip)):
        raise RuntimeError("Open-Meteo returned mismatched hourly arrays.")

    day_prefix = target_day.isoformat()
    by_hour: dict[int, tuple[float, int, int, float]] = {}
    for t, tf, code, dayflag, p in zip(times, temps, codes, is_day, precip):
        if not isinstance(t, str) or not t.startswith(day_prefix):
            continue
        # Open-Meteo uses "YYYY-MM-DDTHH:MM"
        try:
            hour = int(t.split("T", 1)[1].split(":", 1)[0])
        except Exception:
            continue
        if 0 <= hour <= 23:
            by_hour[hour] = (float(tf), int(code), int(dayflag), float(p) if p is not None else 0.0)

    missing = [h for h in range(24) if h not in by_hour]
    if missing:
        raise RuntimeError(f"Missing Open-Meteo hours for {target_day.isoformat()}: {missing}")

    temps_out: List[float] = []
    codes_out: List[int] = []
    is_day_out: List[int] = []
    precip_out: List[float] = []
    for hour in range(24):
        tf, code, dayflag, p = by_hour[hour]
        temps_out.append(tf)
        codes_out.append(code)
        is_day_out.append(dayflag)
        precip_out.append(p)
    return temps_out, codes_out, is_day_out, precip_out


def _fetch_open_meteo_hourly_for_day(target_day: date, tz: str, lat: float, lon: float) -> tuple[List[float], List[int], List[int], List[float]]:
    WEATHER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = WEATHER_CACHE_DIR / f"{target_day.isoformat()}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return _extract_open_meteo_day_hourly(cached, target_day)
        except Exception:
            pass

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": target_day.isoformat(),
        "end_date": target_day.isoformat(),
        "hourly": "temperature_2m,weather_code,is_day,precipitation",
        "temperature_unit": "fahrenheit",
        "timezone": tz or "auto",
    }
    payload: Optional[dict] = None
    try:
        payload = _http_get_json(OPEN_METEO_ARCHIVE_URL, params)
    except Exception as exc:
        logger.warning("Open-Meteo archive fetch failed for %s (%s); trying forecast endpoint", target_day, exc)
        payload = _http_get_json(OPEN_METEO_FORECAST_URL, params)

    try:
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
    return _extract_open_meteo_day_hourly(payload, target_day)


def _classify_condition_from_weather(flags: List[str], precip: List[float]) -> str:
    # Use the "working hours" window 10:00-16:00 inclusive for classification.
    window = list(range(10, 17))
    window_flags = [flags[i] for i in window if i < len(flags)]
    window_precip = [precip[i] for i in window if i < len(precip)]
    if any(f == "R" for f in window_flags) or any((p or 0.0) > 0.0 for p in window_precip):
        return "rainy"
    count_sunny = sum(1 for f in window_flags if f == "S")
    count_cloudy = sum(1 for f in window_flags if f in ("P", "O"))
    if count_sunny >= max(1, count_cloudy):
        return "full_sun"
    return "mixed"


def build_projected_dashboard_payload(
    target: date,
    archive_dates: List[dict],
    *,
    weather_source: str = "auto",
    simulate_requests: bool = False,
    request_every_days: int = 3,
    request_setpoint_delta_f: float = 2.0,
    request_setpoint_deltas_f: Optional[List[float]] = None,
    request_deltas_mode: str = "random",
) -> tuple[dict, dict]:
    """
    Create a full dashboard payload JSON for the archive viewer, generated from date only.

    Returns (payload, summary).
    """
    tz = cfg_payload.get("timezone") or GLOBAL_SHARED_CONFIG.get("timezone") or "auto"
    lat = cfg_payload.get("weather_lat") or GLOBAL_SHARED_CONFIG.get("weather_lat")
    lon = cfg_payload.get("weather_lon") or GLOBAL_SHARED_CONFIG.get("weather_lon")

    use_real_weather = weather_source in ("auto", "open-meteo") and lat is not None and lon is not None

    outside: List[float]
    outside_flags: List[str]
    outside_flag_day_chars: List[str]
    precip: List[float]

    condition = _day_condition(target)
    if use_real_weather:
        try:
            temps_f, codes, is_day, precip = _fetch_open_meteo_hourly_for_day(target, tz, float(lat), float(lon))
            outside = temps_f
            outside_flags = [_open_meteo_flag(code, dayflag) for code, dayflag in zip(codes, is_day)]
            outside_flag_day_chars = [_open_meteo_day_char(dayflag) for dayflag in is_day]
            condition = _classify_condition_from_weather(outside_flags, precip)
        except Exception as exc:
            logger.warning("Falling back to synthetic outside temps for %s (%s)", target, exc)
            use_real_weather = False

    if not use_real_weather:
        precip = [0.0] * 24
        outside_offset = 0.0
        if target.month in (8, 9):
            outside_offset = 8.0
        elif target.month == 10:
            outside_offset = 5.0
        elif target.month == 11:
            outside_offset = 3.0
        elif target.month == 12:
            outside_offset = 2.0
        full_sun_fallback = condition == "full_sun"
        anchors_fallback = _baseline_anchor_temps(target, full_sun=full_sun_fallback)
        normal_fallback = _interpolate_hourly_from_anchors(anchors_fallback)
        outside = [max(30.0, min(105.0, t + outside_offset)) for t in normal_fallback]
        flag = "S" if condition == "full_sun" else ("R" if condition == "rainy" else "P")
        outside_flag_day_chars = [_daylight_char_for_hour(h) for h in range(24)]
        outside_flags = [flag] * 24

    full_sun = condition == "full_sun"
    anchors = _baseline_anchor_temps(target, full_sun=full_sun)
    normal_temp = _interpolate_hourly_from_anchors(anchors)
    setpoint = [_setpoint_for_hour(target, hour) for hour in range(24)]

    # Optional: simulate sporadic "someone came in and wanted it colder" requests.
    # This lowers the setpoints for a small afternoon window on a periodic cadence (deterministic by date).
    request_hours = set(range(15, 21))  # 3pm–8pm inclusive
    request_enabled = bool(simulate_requests) and int(request_every_days) > 0
    request_day = False
    request_delta_for_day = float(request_setpoint_delta_f or 0.0)
    if request_enabled:
        seed = int(target.strftime("%Y%m%d"))
        request_day = (seed % int(request_every_days)) == 0
        deltas = [float(v) for v in (request_setpoint_deltas_f or []) if float(v) > 0]
        if deltas:
            mode = str(request_deltas_mode or "random").strip().lower()
            if mode == "cycle":
                request_delta_for_day = deltas[seed % len(deltas)]
            else:
                # Deterministic "random" choice per day (stable across reruns).
                request_delta_for_day = random.Random(seed).choice(deltas)
    if request_day and request_setpoint_delta_f:
        for hour in request_hours:
            setpoint[hour] = max(60.0, float(setpoint[hour]) - request_delta_for_day)

    hourly_drop = _hourly_drop_for_condition(condition)

    adjusted_temp: List[float] = [float(normal_temp[0])]
    condenser_on: List[bool] = [False] * 24

    for hour in range(24):
        forced_request = bool(request_day) and hour in request_hours
        if forced_request or adjusted_temp[hour] > setpoint[hour]:
            condenser_on[hour] = True
            if hour < 23:
                cooled = float(normal_temp[hour + 1]) - hourly_drop
                adjusted_temp.append(max(cooled, float(setpoint[hour + 1])))
        else:
            condenser_on[hour] = False
            if hour < 23:
                adjusted_temp.append(float(normal_temp[hour + 1]))

    runtime_this_hour = [40 if on else 0 for on in condenser_on]
    total_runtime_minutes = sum(runtime_this_hour)

    latest_outside_raw = ""
    if outside_flags and outside_flag_day_chars and outside:
        if use_real_weather:
            latest_outside_raw = _fmt_open_meteo_outside_raw(outside_flags[-1], outside_flag_day_chars[-1], outside[-1])
        else:
            latest_outside_raw = f"{outside_flags[-1]}{outside_flag_day_chars[-1]}"

    fan_series = [_fan_mode_for_hour(target, hour) for hour in range(24)]
    cooling_series = [1 if on else 0 for on in condenser_on]
    climate_setting_series = ["Cool"] * 24

    # Request metadata (simulated) - matches spreadsheet style:
    # Type: "request (studio 11, zone3, 50m)"
    # Studio: "11" (parsed from Type in real data, but we force it here)
    # Request Expires (local time): "h:mm AM/PM" for that hour + 50 minutes
    request_minutes = 50
    request_studio = "11"
    request_zone = "3"
    type_series: List[str] = []
    studio_series: List[str] = []
    request_expires_series: List[str] = []
    tz_name = str(cfg_payload.get("timezone") or GLOBAL_SHARED_CONFIG.get("timezone") or "America/Los_Angeles")
    tzinfo = None
    try:
        tzinfo = ZoneInfo(tz_name)
    except Exception:
        tzinfo = None
    for hour in range(24):
        forced_request = bool(request_day) and hour in request_hours
        if forced_request:
            type_series.append(f"request (studio {request_studio}, zone{request_zone}, {request_minutes}m)")
            studio_series.append(request_studio)
            base_dt = datetime(target.year, target.month, target.day, hour, 0, 0)
            if tzinfo is not None:
                base_dt = base_dt.replace(tzinfo=tzinfo)
            expires_dt = base_dt + timedelta(minutes=request_minutes)
            time_text = expires_dt.strftime("%I:%M %p")
            if time_text.startswith("0"):
                time_text = time_text[1:]
            request_expires_series.append(time_text)
        else:
            type_series.append("System")
            studio_series.append("")
            request_expires_series.append("")

    # Display/summary values.
    total_condenser_cost_value = float(total_runtime_minutes) * float(COST_PER_MINUTE)
    total_condenser_minutes_display = str(int(total_runtime_minutes))
    total_condenser_cost_display = f"${total_condenser_cost_value:.2f}"

    slug = target.strftime("%Y-%m-%d")
    generated_timestamp = (
        f"Projected {target.strftime('%b %d, %Y')} ({'Open-Meteo' if use_real_weather else 'Synthetic outside'})"
    )

    # Match the live dashboard card schema as closely as possible so existing UI cards populate naturally.
    headers = [
        "Timestamp",
        "Type",
        "Building Temperature",
        "Cooling Set Point",
        "Climate Setting",
        "Fan Setting",
        "Equipment Status",
        "Studio",
        "Request Expires (local time)",
        "Outside Temp",
        "Condenser State",
        "Condenser Minutes",
    ]
    latest_row = [
        f"{slug} 23:00",
        type_series[-1],
        adjusted_temp[-1],
        setpoint[-1],
        climate_setting_series[-1],
        fan_series[-1],
        "Cooling" if cooling_series[-1] else "Idle",
        studio_series[-1],
        request_expires_series[-1],
        outside[-1],
        "On" if condenser_on[-1] else "Off",
        runtime_this_hour[-1],
    ]

    FAN_LABELS = ["Auto", "Circulate", "On"]
    COOLING_LABELS = ["Idle", "Cooling"]

    chart_labels = [
        datetime(target.year, target.month, target.day, hour).strftime("%a %m/%d %I %p")
        for hour in range(24)
    ]

    payload = {
        "headers": headers,
        "latestRow": latest_row,
        "history": [],
        "chartLabels": chart_labels,
        "setpoint": setpoint,
        "actual": adjusted_temp,
        "setpointLabel": "Set Point",
        "actualLabel": "Building Temperature",
        "fan": fan_series,
        "fanLegend": FAN_LABELS,
        "outside": outside,
        "outsideLabel": "Outside Temp",
        "outsideFlags": outside_flags,
        "outsideFlagDayChars": outside_flag_day_chars,
        "cooling": cooling_series,
        "coolingLegend": COOLING_LABELS,
        "coolingLabel": "Status",
        "climateSetting": climate_setting_series,
        "climateSettingLabel": "Climate Setting",
        "typeSeries": type_series,
        "studioSeries": studio_series,
        "requestExpiresLocalSeries": request_expires_series,
        "condenserMinutes": runtime_this_hour,
        "totalCondenserMinutes": total_condenser_minutes_display,
        "totalCondenserMinutesValue": float(total_runtime_minutes),
        "totalCondenserCost": total_condenser_cost_display,
        "totalCondenserCostValue": float(total_condenser_cost_value),
        "condenserCostPerMinute": COST_PER_MINUTE,
        "latestActual": adjusted_temp[-1],
        "latestSetpoint": setpoint[-1],
        "latestOutside": outside[-1],
        "latestOutsideRaw": latest_outside_raw,
        "latestOutsideDaylight": outside_flag_day_chars[-1] != "N",
        "latestOutsideFlagDayChar": outside_flag_day_chars[-1],
        "latestFan": fan_series[-1],
        "latestCooling": cooling_series[-1],
        "latestCondenserState": "On" if condenser_on[-1] else "Off",
        "generatedTimestamp": generated_timestamp,
        "generatedDateSlug": slug,
        "archiveDates": archive_dates,
        "archivePath": ARCHIVE_DIR_NAME,
    }

    hours_condenser_ran = [h for h, on in enumerate(condenser_on) if on]
    summary = {
        "targetDate": slug,
        "datasetAction": "created_or_overwritten",
        "setpointSchedule": {
            "default": sorted(set(setpoint))[0] if setpoint else None,
            "hours": setpoint,
        },
        "condenserHours": hours_condenser_ran,
        "hourlyCoolingDropApplied": hourly_drop,
        "totalProjectedHvacRuntimeMinutes": total_runtime_minutes,
        "dayCondition": condition,
    }
    return payload, summary


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
    if TEST_MODE:
        logger.info("Skipping git autopush because test_mode is enabled in config")
        return
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

    title = "Any Company Anywhere USA"
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
    climate_setting_idx = _find_index(("climate setting", "climate", "mode"))
    condenser_state_idx = _find_index(
        ("condenser state", "compressor state", "condenser status", "compressor status")
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

    def _climate_setting_value(row: List[str]) -> Optional[str]:
        # Force cooling-only display for the dashboard UI.
        return "Cool"

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
    climate_setting_series = [_climate_setting_value(row) for row in history_rows]
    cooling_label = (
        headers[cooling_idx]
        if cooling_idx is not None and len(headers) > cooling_idx
        else "Status"
    )
    climate_setting_label = (
        headers[climate_setting_idx]
        if climate_setting_idx is not None and len(headers) > climate_setting_idx
        else "Climate Setting"
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
    latest_condenser_state = (
        str(latest_row[condenser_state_idx]).strip()
        if condenser_state_idx is not None and condenser_state_idx < len(latest_row)
        else ""
    )
    # Force cooling-only climate setting for dashboard UI consistency.
    if climate_setting_idx is not None and climate_setting_idx < len(latest_row):
        latest_row[climate_setting_idx] = "Cool"
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
        "climateSetting": climate_setting_series,
        "climateSettingLabel": climate_setting_label,
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
        "latestCondenserState": latest_condenser_state,
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
        elif idx == condenser_state_idx:
            metric_attr = ' data-metric="condenser-state"'
        elif idx == climate_setting_idx:
            metric_attr = ' data-metric="climate-setting"'
        elif idx == outside_idx:
            metric_attr = ' data-metric="outside"'
        elif idx == condenser_idx:
            metric_attr = ' data-metric="condenser-minutes"'
        elif idx == timestamp_idx:
            metric_attr = ' data-metric="timestamp"'
        elif idx == type_idx:
            metric_attr = ' data-metric="type"'
        cards += f"""
        <div class="metric-card frame2{fan_state_class}"{metric_attr}>
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
      html, body {{
        height: 100%;
      }}
      body {{
        forced-color-adjust: none;
        -webkit-text-fill-color: initial;
        color: inherit;
        margin: 0;
        font-family: 'Inter', system-ui, sans-serif;
        background: linear-gradient(to bottom, #070312, #160d30, #221542, #453082, #5b517a, #71688c, #71688c, #877796, #71688c);
        background-repeat: no-repeat;
        background-attachment: fixed;
        background-size: 100% 100%;
        min-height: 100vh;
        color: #f4f6ff;
      }}
      .frame {{
        border: 25px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        box-shadow:
          0 4px 6px rgba(0,0,0,0.45),
          inset 0 4px 4px rgba(255,255,255,0.03),
          inset 0 -2px 4px rgba(0,0,0,0.35);
      }}
      .frame2 {{
        border: 6px solid rgba(255,255,255,0.05);
        border-radius: 12px;
        box-shadow:
          0 4px 12px rgba(0,0,0,0.45),
          inset 0 1px 2px rgba(255,255,255,0.03),
          inset 0 -2px 4px rgba(0,0,0,0.35);
      }}
      .container {{
        max-width: 1020px;
        margin: 1px auto;
        padding: 22px;
        background: transparent;
        border: 2px solid rgba(255, 255, 255, 0.01);
        border-radius: 12px;
        box-sizing: border-box;
      }}
      h1 {{
        margin: 0 0 16px;
        font-size: 32px;
      }}
      .header-row {{

        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 1px;
      }}
      .timestamp-row {{
        display: none;
        justify-content: flex-end;
        margin-bottom: 0;
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

        width: auto;
        font-size: 16px;
        line-height: 1.05;
        text-align: left;
        padding: 0;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        opacity: 0.9;
      }}

#chart-history-months {{
  list-style: none;
  margin: 0;
  padding: 0;
}}


  /* Must be visible so the chart-history picker (positioned above) isn't clipped. */
  overflow: visible;
}}

/* Glossy highlight + specular edge for the TV frame (border only). */


.tv-frame {{
  position: relative;
  isolation: isolate;
  --frame-border: 10px;
  border-radius: 14px;
  border: var(--frame-border) solid rgba(255, 255, 255, 0.18);
  background: linear-gradient(
    to bottom,
    #0c0a18 0%,
    #2a2550 22%,
    #1a1730 48%,
    #0b0a16 100%
  );
  box-shadow:
    0 22px 48px rgba(0, 0, 0, 0.75),
    0 0 24px rgba(120, 140, 255, 0.14),
    inset 0 4px 6px rgba(255, 255, 255, 0.32),
    inset 0 -4px 8px rgba(0, 0, 0, 0.92),
    inset 0 0 24px rgba(255, 255, 255, 0.12),
    inset 0 0 38px rgba(0, 0, 0, 0.78);
}}


.tv-frame::before {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: var(--frame-border, 10px);
  pointer-events: none;
  z-index: 50;
  background:
    radial-gradient(140% 80% at 20% 6%,
      rgba(255,255,255,0.42) 0%,
      rgba(255,255,255,0.18) 26%,
      rgba(255,255,255,0.00) 56%
    ),
    linear-gradient(
      to bottom,
      rgba(255,255,255,0.22) 0%,
      rgba(255,255,255,0.06) 38%,
      rgba(255,255,255,0.00) 100%
    );
  mix-blend-mode: screen;
  opacity: 1;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
}}

.tv-frame::after {{
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: var(--frame-border, 10px);
  pointer-events: none;
  z-index: 51;
  box-shadow:
    inset 0 2px 0 rgba(255,255,255,0.42),
    inset 0 -1px 0 rgba(0,0,0,0.38);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
}}



      .logo-placeholder {{

        width: 72px;
        height: 52px;

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
        padding: 18px 22px;
        border-radius: 12px;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 16px;
        background: linear-gradient(to bottom, #120f1c 0%, #1a162b 50%, #0f0d17 100%);
        border: 2px solid rgba(200, 220, 255, 0.08);
        box-shadow:
          inset 0 2px 12px rgba(255, 255, 255, 0.04),
          inset 0 -2px 18px rgba(0, 0, 0, 0.7),
          inset 0 0 24px rgba(0, 0, 0, 0.8),
          0 2px 4px rgba(0, 0, 0, 0.5);
        background-blend-mode: overlay;
        position: relative;
        overflow: hidden;
      }}
      .card-grid::after {{
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 1;
        background-image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEklEQVR42mP8/5+hHgAHggJ/P4qUPwAAAABJRU5ErkJggg==");
        background-repeat: repeat;
        opacity: 0.07;
        mix-blend-mode: soft-light;
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
        border: 10px ridge #3a3a40;
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
        overflow: hidden;
        padding-right: 50%;
      }}
      .metric-card[data-metric="outside"] .label,
      .metric-card[data-metric="outside"] .value {{
        position: relative;
        z-index: 2;
      }}
      .metric-card .sunny-graphic {{
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        width: 50%;
        z-index: 1;
        pointer-events: none;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
      }}
      .metric-card[data-metric="outside"] {{
        position: relative;
        overflow: hidden;
        padding-right: 50%;
      }}
      .metric-card .sunny-graphic {{
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        width: 50%;
        z-index: 1;
        pointer-events: none;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
      }}
      .metric-card[data-metric="outside"] .sunny-graphic {{
        background-position: 50% center;
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
      /* Keep the toggle in the layout (spacing preserved) but hide it visually. */
      #toggle-history {{
        visibility: hidden;
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
      
      .chart-controls {{
        width: 100px;
      }}
      
      #chartcontrols {{
        margin-top: 5PX;
        margin-left: 35PX;
        max-width: none;
        width: 80%;
        position: relative;
        z-index: 30;
        padding: 1px;
        display: grid;
        grid-template-columns: 1fr;
        gap: 2px;
        font-size: 13px;
        color: #f4f6ff;



      }}
      #chartcontrols .chart-control {{
        width: 60%;
        justify-content: flex-start;
        padding: 3px 8px;
        font-size: 12px;
        line-height: 1;
      }}
      #chartcontrols #autoplay-toggle {{
        grid-column: 1 / -1;
      }}
      .controls-transport-wrap {{
        margin-top: -45px;
        margin-left: 0;
        height: auto;
        display: grid;
        grid-template-columns: minmax(0, 240px) minmax(0, 320px);
        grid-template-areas:
          "controls transport"
          "history history";
        align-items: start;
        column-gap: 14px;
        row-gap: 10px;
      }}
      #chartcontrols {{
        grid-area: controls;
        min-width: 0;
      }}
      .controls-transport-wrap .chart-history {{
        grid-area: history;
      }}
      .transport-stack {{
        margin-top: 0;
        position: relative;
        z-index: 10;
        transform: none;
        grid-area: transport;
        min-width: 0;
      }}
      .transport-panel {{
        height: 210px;
        flex: 0 0 auto;
        width: 100%;
        max-width: 320px;
        margin-top: 0;
        margin-left: auto;
        margin-right: auto;
        transform: none;
        position: relative;
        z-index: 1;
        padding: 12px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
        gap: 6px;
        border-radius: 12px;
        box-sizing: border-box;
        pointer-events: auto;
        cursor: pointer;
      }}
      .transport-history-status {{
        
        position: relative;
        z-index: 10;
        width: 100%;
        max-width: 320px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 26px;
        gap: 2px;
        opacity: 0.9;
        color: white;
        margin: 1px auto 0;
        padding: 1px 1px;
        border-radius: 12px;
        white-space: normal;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: center;
        line-height: 1.1;
        margin-top: 0;
      }}
      .transport-history-status .transport-history-month {{
        width: 100%;
        font-size: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        opacity: 0.9;
      }}
      .transport-history-status .transport-history-day {{
        width: 100%;
        font-size: 18px;
        letter-spacing: 0.06em;
        opacity: 0.98;
      }}
      .transport-step-modes {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0;
        padding: 4px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(0,0,0,0.18);
        backdrop-filter: blur(6px);
      }}
      .transport-step-modes label {{
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        user-select: none;
        cursor: pointer;
      }}
      .transport-step-modes input[type="radio"] {{
        position: absolute;
        opacity: 0;
      }}
      .transport-step-modes span {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(255,255,255,0.04);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(244, 246, 255, 0.82);
        transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
      }}
      .transport-step-modes input[type="radio"]:checked + span {{
        background: rgba(255, 179, 71, 0.28);
        border-color: rgba(255, 179, 71, 0.65);
        color: rgba(255, 255, 255, 0.95);
      }}
      .transport-step-modes input[type="radio"]:focus-visible + span {{
        outline: 2px solid rgba(255, 179, 71, 0.85);
        outline-offset: 2px;
      }}
      .transport-deck {{
        width: 280px;
        height: 130px;
        margin-top: 0px;
        border-radius: 14px;
        pointer-events: auto;
        opacity: 0.98;
      }}
      .transport-nav {{
        margin-top: -1px;
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 1px;
        pointer-events: auto;
      }}
      .transport-nav .chart-control {{
        padding: 10px 18px;
        font-size: 18px;
        border-radius: 12px;
      }}
      .transport-deck svg {{
        width: 100%;
        height: 100%;
        display: block;
      }}
      .transport-deck .deck-cassette {{
        opacity: 0;
        transition: opacity 0.3s ease;
      }}
      .transport-deck.cassette-skin .deck-cassette {{
        opacity: 1;
      }}
      .transport-deck.cassette-skin .deck-ui {{
        opacity: 0;
      }}
      .transport-deck {{
        --cassette-reel-scale: 1.05;
        --cassette-reel-left-x: 20px;
        --cassette-reel-left-y: -10px;
        --cassette-reel-right-x: -20px;
        --cassette-reel-right-y: -10px;
        --cassette-image-scale: 1.05;
        --cassette-image-x: 0px;
        --cassette-image-y: 5px;
      }}
      .transport-deck .reel-wrap {{
        transform-box: fill-box;
        transform-origin: center;
      }}
      .transport-deck .reel-wrap.reel-left {{
        transform: translate(var(--cassette-reel-left-x), var(--cassette-reel-left-y)) scale(var(--cassette-reel-scale));
      }}
      .transport-deck .reel-wrap.reel-right {{
        transform: translate(var(--cassette-reel-right-x), var(--cassette-reel-right-y)) scale(var(--cassette-reel-scale));
      }}
      .transport-deck .reel-spin {{
        height: 200px;
        transform-box: fill-box;
        transform-origin: center;
      }}
      .transport-deck .deck-cassette {{
        transform-box: fill-box;
        transform-origin: center;
        transform: translate(var(--cassette-image-x), var(--cassette-image-y)) scale(var(--cassette-image-scale));
      }}
      .transport-deck.playing .reel-spin {{
        animation: deck-spin 1.35s linear infinite;
      }}
      .transport-deck .led-dot {{
        transition: fill 0.25s ease, filter 0.25s ease;
      }}
      .transport-deck.playing .led-dot {{
        fill: rgba(102, 255, 153, 0.95) !important;
        filter: drop-shadow(0 0 6px rgba(102, 255, 153, 0.55));
      }}
      @keyframes deck-spin {{
        from {{ transform: rotate(0deg); }}
        to {{ transform: rotate(360deg); }}
      }}
      .chart-top-row {{
        max-width: 1120px;
        width: 100%;
        display: grid;
        grid-template-columns: 400px minmax(340px, 1fr);
        align-items: flex-start;
        gap: 14px;
        margin-top: 20px;
        margin-bottom: 18px;
        transform: translateX(-15px);
        border: 1px solid rgba(255, 255, 255, 0.18);
      }}
      .usage-slot {{
        width: 400px;
        min-width: 400px;
        height: 236px;
        margin-top: -65px;
        margin-left: 1px;
 
        border-radius: 12px;
        background: rgba(0, 0, 0, 0.6);

        padding: 10px 12px;
        color: #fff5c7;
        font-size: 12px;
        opacity: 0.9;
        position: relative;
        overflow: visible;
        display: flex;
        flex-direction: column;
      }}
      .usage-frame-wrap {{
        position: relative;
        container-type: inline-size;
        --usage-legs-overlap: 18px;
      }}
      .usage-frame-wrap .usage-legs {{
        position: absolute;
        left: 50%;
        bottom: 0;
        transform: translateX(-50%) translateY(calc(100% - var(--usage-legs-overlap)));
        height: clamp(170px, 92%, 260px);
        width: min(520px, 95%);
        z-index: 0;
        pointer-events: none;
        opacity: 0.96;
        background-image: url("../../../Images/Legs2.png");
        background-repeat: no-repeat;
        background-position: center bottom;
        background-size: contain;
        filter: brightness(1.25) contrast(1.1) saturate(1.15) drop-shadow(0 10px 20px rgba(0,0,0,0.6));
      }}
      @supports (height: 1cqi) {{
        .usage-frame-wrap .usage-legs {{
          height: clamp(170px, 62cqi, 300px);
          width: min(520px, 120cqi);
        }}
      }}
      .usage-frame-wrap .usage-slot {{
        position: relative;
        z-index: 1;
      }}
      .usage-slot > .usage-header,
      .usage-slot > .usage-graphic,
      .usage-slot > .swap-controls {{
        position: relative;
        z-index: 1;
      }}
      .usage-header {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
      }}
      .usage-header-left {{
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: 0;
        align-items: flex-start;
      }}
      .usage-slot .title {{
        font-size: 12px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: 0;
        opacity: 0.9;
        text-align: left;
      }}
      .usage-slot .hint {{
        opacity: 0.75;
        font-size: 11px;
      }}
      .usage-controls {{
        display: flex;
        gap: 1px;
        margin-bottom: 0;
        padding: 6px;
    
        border-radius: 12px;
        background: rgba(0, 0, 0, 0.18);
      }}
      .usage-control {{
        border: 1px solid rgba(255, 255, 255, 0.16);
        background: rgba(0, 0, 0, 0.22);
        color: #fff5c7;
        padding: 4px 8px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 11px;
      }}
      .usage-control.active {{
        border-color: rgba(255, 179, 71, 0.9);
        color: #ffb347;
      }}
      .usage-graphic {{
        flex: 1;
        min-height: 0;
        position: relative;
        display: flex;
        align-items: stretch;
        height: 150px;
      }}
      .swap-controls {{
        margin-top: 8px;
        width: 100%;
        display: flex;
        justify-content: center;
      }}
      .swap-controls .swap-controls-inner {{
        width: 100%;
        max-width: 320px;
        padding: 8px 12px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.16);
        background: rgba(0, 0, 0, 0.18);
        box-shadow: 0 10px 18px rgba(0, 0, 0, 0.35);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        user-select: none;
        color: rgba(255, 245, 199, 0.95);
      }}
      .swap-controls .swap-step-btn {{
        flex: 0 0 auto;
        min-width: 48px;
        height: 36px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.22);
        background: rgba(0,0,0,0.35);
        color: rgba(244, 246, 255, 0.92);
        font-size: 16px;
        letter-spacing: 0.08em;
        cursor: pointer;
        box-shadow: 0 10px 18px rgba(0, 0, 0, 0.35);
      }}
      .swap-controls .swap-step-btn:disabled {{
        opacity: 0.35;
        cursor: default;
      }}
      .swap-controls .swap-step-label {{
        flex: 1 1 auto;
        text-align: center;
        font-size: 12px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        opacity: 0.95;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .swap-controls .swap-controls-inner:focus-visible {{
        outline: 2px solid rgba(102, 255, 153, 0.55);
        outline-offset: 2px;
      }}
      #usage-slot-canvas-slot {{
        flex: 1 1 auto;
        min-height: 0;
        width: 100%;
        height: 100%;
        display: flex;
      }}
      #usage-slot-canvas-slot > canvas {{
        flex: 1 1 auto;
        min-height: 0;
      }}
      .usage-stats {{
        flex: 0 0 auto;
        display: grid;
        grid-template-columns: auto auto;
        gap: 2px 10px;
        padding: 2px 8px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.54);
        background: rgba(0, 0, 0, 0.35);
        color: #fff5c7;
        font-size: 9px;
        line-height: 1.05;
        pointer-events: none;
        margin-top: 2px;
      }}
      .usage-stats .k {{
        opacity: 0.75;
      }}
      .usage-stats .v {{
        color: #ffb347;
        font-weight: 600;
        text-align: right;
        min-width: 58px;
      }}
      .usage-slot #usage-slot-chart {{
        width: 100% !important;
        height: 100% !important;
        max-height: 100% !important;
      }}
      .usage-slot #history-chart {{
        width: 100% !important;
        height: 100% !important;
        max-height: 100% !important;
      }}
      .chart-wrap #usage-slot-chart {{
        width: 100% !important;
        height: 70% !important;
      }}
      .usage-slot .title {{
        cursor: pointer;
      }}
      @media (max-width: 980px) {{
        .chart-top-row {{
          grid-template-columns: 1fr;
          transform: none;
        }}

        #chartcontrols {{
          max-width: none;
          width: 100%;
          box-sizing: border-box;
          display: grid;
          grid-template-columns: 1fr;
          margin-right: 0;
          margin-left: 0;
          padding-right: 1px;
        }}
        .controls-transport-wrap {{
          margin-top: 40;
          margin-left: 10;
          width: 100%;
          align-items: start;
          display: grid;
          grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
          grid-template-areas:
            "controls transport"
            "history history";
        }}
        .transport-stack {{
          width: 100%;
          max-width: 320px;
          margin-top: 0;
          transform: none;
        }}
        .transport-panel {{
          flex: 0 0 auto;
          width: 100%;
          margin-top: 0;
          margin-left: 0;
          height: auto;
          transform: none;
        }}
        .transport-deck {{
          display: none;
        }}
        .transport-nav {{
          margin-top: 10px;
        }}
        .usage-slot {{
          min-width: 0;
          width: 100%;
          height: auto;
        }}
      }}
      .chart-control {{
        background: #0d0d12;
        color: #6f7176;
        padding: 5px 10px;
        border-radius: 8px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        cursor: pointer;
        transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
      }}
      .chart-control[data-mode] {{
        width: 150px;
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
        display: none;
        margin-top: 65px;
        position: absolute;
        top: 24px;
        right: 4px;
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
      }}
      .chart-wrap {{
        height: 580px;
        margin: -29px auto 0;
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
        display: flex;
        flex-direction: column;
        --usage-pip-reserve: 0px;
      }}
      .chart-wrap #history-chart-canvas-slot {{
        flex: 1 1 auto;
        min-height: 0;
        display: flex;
      }}
      .chart-wrap #history-chart {{
        flex: 1 1 auto;
        min-height: 0;
      }}
      body.charts-swapped .chart-wrap #usage-slot-chart {{
        flex: 1 1 auto;
        min-height: 0;
      }}
      body.charts-swapped .chart-wrap #history-chart-canvas-slot {{
        align-items: stretch;
        display: flex;
        flex-direction: column;
        padding-top: var(--usage-pip-reserve);
        box-sizing: border-box;
      }}
      body.charts-swapped .chart-wrap #history-chart-canvas-slot > canvas {{
        width: 100% !important;
        box-sizing: border-box;
        flex: 1 1 auto;
        min-height: 0;
      }}
      body.charts-swapped .chart-wrap {{
        --usage-pip-reserve: 130px;
      }}
      @media (max-width: 980px) {{
        body.charts-swapped .chart-wrap {{
          --usage-pip-reserve: 92px;
        }}
      }}
      /* When the Usage chart is on the TV frame, show its header/stats as a right-side overlay. */
      #usage-pip {{
        display: none;
        position: absolute;
        top: 18px;
        right: 18px;
        width: 360px;
        max-width: calc(100% - 36px);
        padding: 10px 12px;
        border-radius: 14px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        background: rgba(0, 0, 0, 0.24);
        box-shadow: 0 14px 28px rgba(0,0,0,0.55);
        z-index: 4;
      }}
      body.charts-swapped #usage-pip {{
        display: block;
      }}
      body.charts-swapped #usage-pip {{
        left: 18px;
        right: auto;
        width: 540px;
      }}
      body.charts-swapped #usage-pip .usage-header {{
        flex-direction: row;
        align-items: center;
        justify-content: space-between;
        flex-wrap: nowrap;
        gap: 12px;
      }}
      body.charts-swapped #usage-pip .usage-header-left {{
        flex-direction: row;
        align-items: center;
        gap: 12px;
      }}
      body.charts-swapped #usage-pip .title {{
        font-size: 14px;
        letter-spacing: 0.08em;
        white-space: nowrap;
      }}
      body.charts-swapped #usage-pip .usage-controls {{
        padding: 8px;
        gap: 4px;
        flex-wrap: nowrap;
      }}
      body.charts-swapped #usage-pip .usage-control {{
        font-size: 13px;
        padding: 6px 12px;
        border-radius: 10px;
        white-space: nowrap;
      }}
      body.charts-swapped #usage-pip .usage-stats {{
        font-size: 11px;
        gap: 4px 12px;
        padding: 6px 10px;
        border-radius: 12px;
      }}
      body.charts-swapped #usage-pip .usage-stats .v {{
        min-width: 72px;
      }}
      @media (max-width: 680px) {{
        #usage-pip {{
          display: none !important;
        }}
      }}
      /* Hands logo overlay when the Usage chart is on the TV frame. */
      #tv-hands-logo {{
        display: none;
        position: absolute;
        top: 22px;
        right: 38px;
        width: 250px;
        height: 64px;
        background-image: url("../../../Images/Hands.png");
        background-repeat: no-repeat;
        background-position: right center;
        background-size: contain;
        opacity: 0.9;
        z-index: 4;
        pointer-events: none;
        filter: drop-shadow(0 10px 16px rgba(0,0,0,0.55));
      }}
      body.charts-swapped #tv-hands-logo {{
        display: block;
      }}
      @media (max-width: 680px) {{
        #tv-hands-logo {{
          display: none !important;
        }}
      }}
      /* TV stand/legs graphic under the main chart frame. */
      .tv-frame-wrap {{
        position: relative;
        container-type: inline-size;
        --tv-legs-overlap: 35px;
        margin-bottom: 48px;
      }}
      body.hide-big-chart .tv-frame-wrap {{
        display: none;
      }}
      .tv-frame-wrap .tv-legs {{
        position: absolute;
        left: 50%;
        bottom: 0;
        transform: translateX(-50%) translateY(calc(100% - var(--tv-legs-overlap)));
        height: clamp(400px, 95%, 650px);
        width: min(1100px, 95%);
        z-index: 0;
        pointer-events: none;
        opacity: 0.98;
        background-image: url("../../../Images/Legs2.png");
        background-repeat: no-repeat;
        background-position: center bottom;
        background-size: contain;
        filter: brightness(1.25) contrast(1.1) saturate(1.15) drop-shadow(0 18px 26px rgba(0,0,0,0.65));
      }}
      @supports (height: 1cqi) {{
        .tv-frame-wrap .tv-legs {{
          height: clamp(400px, 62cqi, 700px);
          width: min(1100px, 140cqi);
        }}
      }}
      .tv-frame-wrap .chart-wrap.tv-frame {{
        position: relative;
        z-index: 1;
      }}
      body.hide-big-chart #toggle-history {{
        display: none;
      }}
      body.tv-mode {{
        overflow: hidden;
        background: #07070b;
      }}
      body.tv-mode .header-row,
      body.tv-mode .timestamp-row,
      body.tv-mode #Cards,
      body.tv-mode .hands-logo-slot,
      body.tv-mode #toggle-history,
      body.tv-mode .condenser-runtime,
      body.tv-mode .chart-top-row,
      body.tv-mode .note,
      body.tv-mode #js-log {{
        display: none !important;
      }}
      body.tv-mode .container.frame {{
        max-width: none;
        width: 100vw;
        margin: 0;
        padding: 0;
        border: 0;
        box-shadow: none;
        border-radius: 0;
      }}
      body.tv-mode .tv-frame-wrap {{
        display: block !important;
        position: fixed;
        inset: 14px 34px 74px 34px;
        z-index: 9999;
      }}
      body.tv-mode .tv-frame-wrap .chart-wrap.tv-frame {{
        position: absolute;
        inset: 0;
        height: auto;
        width: auto;
        max-width: none;
        margin: 0;
        border-radius: 22px;
        padding: 18px 0 18px;
        --frame-border: 12px;
        border: var(--frame-border) solid rgba(255, 255, 255, 0.2);
        background: linear-gradient(to bottom, #050506 0%, #151518 55%, #2b2b2e 100%);
      }}
      body.tv-mode #history-chart-canvas-slot,
      body.tv-mode #history-chart {{
        height: 100% !important;
      }}
      body.tv-mode .tv-frame-wrap .tv-legs {{
        display: block;
        height: clamp(360px, 72%, 560px);
      }}
      @supports (height: 1cqi) {{
        body.tv-mode .tv-frame-wrap .tv-legs {{
          height: clamp(360px, 40cqi, 600px);
        }}
      }}
      /* TV mode chart controls (mode toggles) shown on the right. */
      .tv-chartcontrols-overlay {{
        display: none;
      }}
      body.tv-mode .tv-chartcontrols-overlay {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        grid-auto-rows: auto;
        gap: 6px 6px;
        padding: 5px;
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(0,0,0,0.24);
        backdrop-filter: blur(8px);
        width: 300px;
        justify-content: start;

      }}
      body.tv-mode .tv-chartcontrols-overlay .chart-control {{
        width: 100%;
        text-align: left;
        font-size: 11px;
        padding: 2px 6px;
        letter-spacing: 0.2px;
        white-space: nowrap;
      }}
      .tv-bottom-bar {{
        display: none;
      }}
      body.tv-mode .tv-bottom-bar {{
        display: flex;
        position: fixed;
        left: 34px;
        right: 34px;
        bottom: 15px;
        z-index: 10060;
        align-items: flex-end;
        justify-content: space-between;
        gap: 12px;
        pointer-events: auto;
      }}
      body.tv-mode .tv-bottom-left {{
        display: flex;
        align-items: flex-end;
        gap: 12px;
      }}
      body.tv-mode .tv-file-select {{
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 6px 10px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(0,0,0,0.24);
        backdrop-filter: blur(8px);
        width: 320px;
        box-sizing: border-box;
      }}
      body.tv-mode .tv-file-select-title {{
        font-size: 10px;
        line-height: 1.1;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        opacity: 0.85;
        user-select: none;
        width: 100%;
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      body.tv-mode .tv-file-select-status {{
        font-size: 11px;
        line-height: 1.1;
        opacity: 0.9;
        letter-spacing: 0.02em;
        user-select: none;
        width: 100%;
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      body.tv-mode #tv-history-status {{
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 2px;
      }}
      body.tv-mode #tv-history-status .tv-history-month {{
        width: 100%;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        opacity: 0.9;
      }}
      body.tv-mode #tv-history-status .tv-history-day {{
        width: 100%;
        font-size: 18px;
        letter-spacing: 0.06em;
        opacity: 0.95;
      }}
      body.tv-mode #tv-history-status .tv-history-hour {{
        width: 100%;
        font-size: 14px;
        letter-spacing: 0.08em;
        color: #ffb347;
      }}
      body.tv-mode #tv-file-select {{
        cursor: pointer;
      }}
      body.tv-mode #tv-file-select .chart-history {{
        max-width: none;
        margin: 0;
        height: 0;
        overflow: visible;
      }}
      body.tv-mode #tv-file-select .chart-wrap.tv-frame .chart-history,
      body.tv-mode #tv-file-select .chart-history {{
        position: relative;
        top: auto;
        right: auto;
        background: transparent;
        border: 0;
        box-shadow: none;
        padding: 0;
        width: 100%;
        max-height: none;
        overflow: visible;
        display: block;
      }}
      body.tv-mode #tv-file-select .chart-history h4 {{
        display: none;
      }}
      body.tv-mode #tv-file-select .chart-history-status {{
        display: none !important;
      }}
      /* TV mode navigation controls (prev/next day) positioned between the legs. */
      .tv-nav-overlay {{
        display: none;
      }}
      body.tv-mode .tv-nav-overlay {{
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
        gap: 8px;
        pointer-events: auto;
        position: fixed;
        left: 50%;
        bottom: 34px;
        transform: translateX(-50%);
        z-index: 10070;
      }}
      body.tv-mode .tv-nav-overlay .tv-step-modes {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0;
        padding: 4px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(0,0,0,0.18);
        backdrop-filter: blur(6px);
      }}
      body.tv-mode .tv-nav-overlay .tv-step-modes label {{
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        user-select: none;
        cursor: pointer;
      }}
      body.tv-mode .tv-nav-overlay .tv-step-modes input[type="radio"] {{
        position: absolute;
        opacity: 0;
      }}
      body.tv-mode .tv-nav-overlay .tv-step-modes span {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.10);
        background: rgba(255,255,255,0.04);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(244, 246, 255, 0.82);
        transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
      }}
      body.tv-mode .tv-nav-overlay .tv-step-modes input[type="radio"]:checked + span {{
        background: rgba(255, 179, 71, 0.28);
        border-color: rgba(255, 179, 71, 0.65);
        color: rgba(255, 255, 255, 0.95);
      }}
      body.tv-mode .tv-nav-overlay .tv-step-modes input[type="radio"]:focus-visible + span {{
        outline: 2px solid rgba(255, 179, 71, 0.85);
        outline-offset: 2px;
      }}
      body.tv-mode .tv-nav-overlay .tv-nav-row {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 28px;
      }}
      body.tv-mode .tv-nav-overlay .tv-step-value {{
        min-width: 140px;
        text-align: center;
        font-size: 22px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(244, 246, 255, 0.92);
        user-select: none;
      }}
      .tv-nav-btn {{
        flex: 0 0 auto;
        min-width: 52px;
        height: 40px;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.22);
        background: rgba(0,0,0,0.35);
        color: rgba(244, 246, 255, 0.92);
        font-size: 18px;
        letter-spacing: 0.08em;
        cursor: pointer;
        box-shadow: 0 18px 30px rgba(0,0,0,0.55);
      }}
      .tv-nav-btn:disabled {{
        opacity: 0.35;
        cursor: default;
      }}
      body.hide-chart-history .chart-history {{
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: 0;
        background: transparent;
        min-height: 0;
      }}
      body.hide-chart-history .chart-history > h4,
      body.hide-chart-history .chart-history > .chart-history-status {{
        display: none !important;
      }}
      body.hide-big-chart .chart-history {{
        position: relative;
        width: 100%;
        max-width: 720px;
        margin: 14px auto 0;
        box-sizing: border-box;
      }}
      @media (max-width: 680px) {{
        .chart-wrap.tv-frame {{
          margin-bottom: 18px;
        }}
      }}
      .chart-wrap::before {{
        content: "";
        position: absolute;
        top: 8px;
        left: 50%;
        transform: translateX(-50%);
        width: 260px;
        height: 160px;
        pointer-events: none;
        z-index: 1;
        background-image: url("../../../Images/Hands.png");
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
        opacity: 0;
        filter: drop-shadow(0 8px 16px rgba(0,0,0,0.55));
      }}
      body.charts-swapped .chart-wrap::before {{
        opacity: 0.16;
      }}
      .chart-wrap canvas {{
        position: relative;
        z-index: 2;
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
        position: relative;
        width: 100%;
        max-width: 720px;
        margin: 14px auto 0;
        z-index: 40;
        box-sizing: border-box;
        padding: 0;
        background: transparent;
        border: 0;
        box-shadow: none;
        color: #fff5c7;
      }}
      .chart-wrap.tv-frame .chart-history {{
        position: absolute;
        margin-top: 10px;
        top: -217px;
        right: 55px;
        z-index: 5;
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
        flex-wrap: nowrap;
        gap: 12px;
        align-items: flex-start;
      }}
      .history-months {{
        flex: 0 0 125px;
        width: 125px;
        padding-right: 4px;
        border-right: 1px solid rgba(255, 255, 255, 0.18);
      }}
      .history-months h5 {{
        margin: 0 0 6px;
        font-size: 12px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: #fff5c7;
        white-space: nowrap;
      }}
      .history-months-list {{
        list-style: none;
        margin: 0;
        padding: 0;
        display: none;
        flex-direction: column;
        gap: 2px;
      }}
      /* Open months list only when history is expanded (no hover-open). */
      .chart-history.expanded .history-months-list {{
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
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
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
        min-width: 0;
        min-height: 0;
        padding: 0;
        transition: max-height 0.2s ease, padding 0.2s ease;
      }}
      .history-list-column.expanded {{
        max-height: none;
        overflow: visible;
        padding: 0;
        margin-right: 0;
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
        white-space: nowrap;
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
        display: none;
        flex-wrap: nowrap;
        gap: 12px;
        align-items: flex-start;
        width: 100%;
      }}
      /* Expand upward (drop-up) without pushing layout down. */
      .chart-history.expanded .history-lists-row {{
        display: flex;
        position: absolute;
        left: 0;
        right: 0;
        bottom: calc(100% + 10px);
        z-index: 60;
        background: #2f3136;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 14px;
        padding: 12px 14px;
        box-shadow:
          0 14px 30px rgba(0, 0, 0, 0.45),
          inset 0 1px 2px rgba(255, 255, 255, 0.15);
      }}
      .chart-history h4 {{
        margin: 0;
        font-size: 12px;
        letter-spacing: 0.08em;
        font-weight: 600;
        text-transform: uppercase;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 12px;
        background: #2f3136;
        border: 1px solid rgba(255, 255, 255, 0.2);
        box-shadow: 0 10px 18px rgba(0, 0, 0, 0.35);
      }}
      .chart-history.expanded h4 {{
        border-color: rgba(102, 255, 153, 0.45);
      }}
      .chart-history {{
        position: relative;
      }}
      .chart-history:not(.expanded) .chart-history-status {{
        display: none;
      }}
      .chart-history-status {{
        display: none;
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
        display: block;
        width: 100%;
        box-sizing: border-box;
        text-align: left;
        cursor: pointer;
        color: #33ccff;
        font-size: 11px;
        letter-spacing: 0.04em;
        padding: 3px 8px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
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
  <body class="hide-big-chart hide-chart-history">
    <div class="container">
      <div id="Cards" class="card-grid frame2">
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

      <div class="chart-top-row">
        <div class="usage-frame-wrap">
          <div class="usage-legs" aria-hidden="true"></div>
          <div class="usage-slot tv-frame" id="usage-slot">
            <div class="usage-header">
              <div class="usage-header-left">
                <div class="title">Usage Chart</div>
                <div class="usage-controls" role="group" aria-label="Usage Range">
                  <button type="button" class="usage-control" data-range="7d">7 Day</button>
                  <button type="button" class="usage-control" data-range="month">Month</button>
                  <button type="button" class="usage-control active" data-range="year">Year</button>
                </div>
              </div>
              <div class="usage-stats" id="usage-slot-stats" aria-hidden="true">
                <div class="k">Total</div><div class="v" id="usage-stat-total">-</div>
                <div class="k">Avg</div><div class="v" id="usage-stat-avg">-</div>
                <div class="k">Max</div><div class="v" id="usage-stat-max">-</div>
                <div class="k">Cost</div><div class="v" id="usage-stat-cost">-</div>
              </div>
            </div>
            <div class="usage-graphic">
              <div id="usage-slot-canvas-slot">
                <canvas id="usage-slot-chart"></canvas>
              </div>
            </div>
            <div id="swap-controls" class="swap-controls" aria-hidden="false">
              <div id="swap-controls-label" class="swap-controls-inner" role="group" aria-label="Step through 24 hour chart">
                <button type="button" id="chart-step-prev" class="swap-step-btn" aria-label="Previous point">&lt;&lt;</button>
                <div id="chart-step-value" class="swap-step-label">Step Time</div>
                <button type="button" id="chart-step-next" class="swap-step-btn" aria-label="Next point">&gt;&gt;</button>
              </div>
            </div>
          </div>
        </div>
        <div class="controls-transport-wrap">
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
          <div class="chart-history" id="chart-history">
            <h4 id="chart-history-toggle">Chart History</h4>
            <div id="chart-history-status" class="chart-history-status"></div>
            <ul id="chart-history-list" class="hidden"></ul>
          </div>
          <div class="transport-stack">

      <div id="transport-panel" class="transport-panel">
            <div id="transport-deck" class="transport-deck cassette-skin" aria-hidden="true">
              <svg viewBox="0 0 240 90" role="img" aria-label="Data deck">
              <defs>
                <linearGradient id="deck-bg" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0" stop-color="#1c1c24" />
                  <stop offset="0.55" stop-color="#0d0d14" />
                  <stop offset="1" stop-color="#2b2b34" />
                </linearGradient>
                <linearGradient id="deck-edge" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0" stop-color="rgba(255,255,255,0.18)" />
                  <stop offset="1" stop-color="rgba(0,0,0,0.6)" />
                </linearGradient>
                <filter id="deck-shadow" x="-20%" y="-40%" width="140%" height="180%">
                  <feDropShadow dx="0" dy="10" stdDeviation="7" flood-color="rgba(0,0,0,0.7)" />
                </filter>
              </defs>
              <g class="deck-ui">
                <!-- Depth/back plate to make the deck feel like a cassette -->
                <rect x="6" y="6" width="234" height="84" rx="14" fill="rgba(0,0,0,0.55)" />
                <!-- Main body -->
                <rect x="3" y="3" width="234" height="84" rx="14" fill="url(#deck-bg)" stroke="url(#deck-edge)" stroke-width="2" filter="url(#deck-shadow)" />
                <!-- Bottom lip -->
                <rect x="10" y="74" width="220" height="10" rx="6" fill="rgba(0,0,0,0.28)" />
                <!-- Window area -->
                <rect x="12" y="14" width="216" height="40" rx="10" fill="rgba(255,255,255,0.07)" />
                <rect x="14" y="16" width="212" height="36" rx="9" fill="rgba(0,0,0,0.30)" />
              </g>

              <!-- Cassette overlay (RGBA). Place behind reels so the animated reels are visible. -->
              <image class="deck-cassette" href="../../../Images/Casette2.png" x="0" y="0" width="240" height="90" preserveAspectRatio="xMidYMid meet" />

              <g class="reel-wrap reel-left" aria-hidden="true">
                <g class="reel-spin">
                  <circle cx="72" cy="34" r="14" fill="rgba(0,0,0,0.0)" stroke="rgba(0,0,0,0.55)" stroke-width="1.5" />
                  <circle cx="72" cy="34" r="10" fill="rgba(0,0,0,0.0)" stroke="rgba(255,255,255,0.14)" stroke-width="1" />
                  <circle cx="72" cy="34" r="2.5" fill="rgba(255,255,255,0.35)" />
                  <path d="M72 24 L74.8 32 L72 34 L69.2 32 Z" fill="rgba(255,255,255,0.35)" />
                  <path d="M62 34 L70 36.8 L72 34 L70 31.2 Z" fill="rgba(255,255,255,0.35)" />
                  <path d="M72 44 L74.8 36 L72 34 L69.2 36 Z" fill="rgba(255,255,255,0.35)" />
                  <path d="M82 34 L74 36.8 L72 34 L74 31.2 Z" fill="rgba(255,255,255,0.35)" />
                </g>
              </g>

              <g class="reel-wrap reel-right" aria-hidden="true">
                <g class="reel-spin">
                  <circle cx="168" cy="34" r="14" fill="rgba(0,0,0,0.0)" stroke="rgba(0,0,0,0.55)" stroke-width="1.5" />
                  <circle cx="168" cy="34" r="10" fill="rgba(0,0,0,0.0)" stroke="rgba(255,255,255,0.14)" stroke-width="1" />
                  <circle cx="168" cy="34" r="2.5" fill="rgba(255,255,255,0.35)" />
                  <path d="M168 24 L170.8 32 L168 34 L165.2 32 Z" fill="rgba(255,255,255,0.35)" />
                  <path d="M158 34 L166 36.8 L168 34 L166 31.2 Z" fill="rgba(255,255,255,0.35)" />
                  <path d="M168 44 L170.8 36 L168 34 L165.2 36 Z" fill="rgba(255,255,255,0.35)" />
                  <path d="M178 34 L170 36.8 L168 34 L170 31.2 Z" fill="rgba(255,255,255,0.35)" />
                </g>
              </g>

              <g class="deck-ui">
                <path d="M86 34 C104 28, 136 28, 154 34" stroke="rgba(255,255,255,0.18)" stroke-width="2" fill="none" />
                <path d="M86 38 C104 44, 136 44, 154 38" stroke="rgba(255,255,255,0.10)" stroke-width="2" fill="none" />

                <text x="120" y="70" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="12" fill="rgba(244,246,255,0.72)" letter-spacing="0.18em">
                  DATA TRANSPORT
                </text>
              </g>

              <g class="deck-led">
                <circle cx="178" cy="50" r="5.5" fill="rgba(0,0,0,0.35)" />
                <circle class="led-dot" cx="178" cy="50" r="3.5" fill="rgba(255,102,102,0.25)" />
              </g>
            </svg>
          </div>
          <div id="transport-history-status" class="transport-history-status">
            <div id="transport-history-month" class="transport-history-month">Current</div>
            <div id="transport-history-day" class="transport-history-day"></div>
          </div>
          <div class="transport-step-modes" aria-label="Step size" role="radiogroup">
            <label><input type="radio" name="transport-step-mode" id="transport-step-month" value="month" /><span>Month</span></label>
            <label><input type="radio" name="transport-step-mode" id="transport-step-day" value="day" checked /><span>Day</span></label>
          </div>
          <div id="transport-nav" class="transport-nav" role="group" aria-label="History navigation"></div>
        </div>
        </div>
        </div>
      </div>
        <div class="tv-frame-wrap">
          <div class="tv-legs" aria-hidden="true"></div>
          <div class="chart-wrap tv-frame">
            <div id="usage-pip" aria-hidden="true"></div>
            <div id="tv-hands-logo" aria-hidden="true"></div>
            <div>
            </div>
            <div id="history-chart-canvas-slot">
              <canvas id="history-chart"></canvas>
            </div>
              <div class="tv-bottom-bar" aria-hidden="true">
                <div class="tv-bottom-left">
                <div class="tv-file-select" id="tv-file-select" aria-label="TV file select">
                  <div class="tv-file-select-title">Chart History</div>
                  <div id="tv-history-status" class="tv-file-select-status">
                    <div id="tv-history-month" class="tv-history-month">Current</div>
                    <div id="tv-history-day" class="tv-history-day"></div>
                    <div id="tv-history-hour" class="tv-history-hour"></div>
                  </div>
                  <div id="tv-history-slot"></div>
                </div>
              </div>
                <div class="tv-nav-overlay" aria-hidden="true">
                  <div class="tv-step-modes" aria-label="Step size" role="radiogroup">
                    <label><input type="radio" name="tv-step-mode" id="tv-step-month" value="month" /><span>Month</span></label>
                    <label><input type="radio" name="tv-step-mode" id="tv-step-day" value="day" checked /><span>Day</span></label>
                    <label><input type="radio" name="tv-step-mode" id="tv-step-hour" value="hour" /><span>Hour</span></label>
                  </div>
                  <div class="tv-nav-row" aria-hidden="true">
                    <button type="button" id="tv-archive-prev" class="tv-nav-btn" aria-label="Previous">&lt;&lt;</button>
                    <div id="tv-step-value" class="tv-step-value"></div>
                    <button type="button" id="tv-archive-next" class="tv-nav-btn" aria-label="Next">&gt;&gt;</button>
                  </div>
                </div>
              <div class="tv-chartcontrols-overlay" aria-label="TV chart controls">
                <button type="button" class="chart-control" data-mode="setpoint">Set Point</button>
                <button type="button" class="chart-control" data-mode="actual">Building Temp</button>
                <button type="button" class="chart-control" data-mode="outside">Outside Temp</button>
                <button type="button" class="chart-control" data-mode="cooling">AC Status</button>
                <button type="button" class="chart-control" data-mode="fan">Fan Mode</button>
                <button type="button" class="chart-control" data-mode="both">Combined</button>
              </div>
            </div>
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


def run_live_dashboard() -> None:
    if TEST_MODE:
        run_test_mode_dashboard()
        return
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
        git_autopush(public_copy, extra_paths=[archive_target, dashboard_data_path, dashboard_script_path])
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


def _find_index_in_headers(headers: List[str], keywords: Tuple[str, ...]) -> Optional[int]:
    for idx, header in enumerate(headers):
        if not header:
            continue
        value = str(header).strip().lower()
        for keyword in keywords:
            if keyword in value:
                return idx
    return None


def _reconstruct_history_rows_from_payload(payload: dict) -> Tuple[List[str], List[str], List[List[str]]]:
    headers = list(payload.get("headers") or [])
    latest_row = list(payload.get("latestRow") or [])

    chart_labels = list(payload.get("chartLabels") or [])
    setpoint_series = list(payload.get("setpoint") or [])
    actual_series = list(payload.get("actual") or [])
    outside_series = list(payload.get("outside") or [])
    fan_series = list(payload.get("fan") or [])
    cooling_series = list(payload.get("cooling") or [])
    condenser_minutes_series = list(payload.get("condenserMinutes") or [])

    row_count = max(
        len(chart_labels),
        len(setpoint_series),
        len(actual_series),
        len(outside_series),
        len(fan_series),
        len(cooling_series),
        len(condenser_minutes_series),
    )
    if row_count == 0:
        raise SystemExit("Cached payload missing chart series; cannot reconstruct history rows.")

    setpoint_idx = _find_index_in_headers(
        headers, ("cooling set point", "cooling setpoint", "set point", "d")
    )
    actual_idx = _find_index_in_headers(headers, ("building temperature", "actual temperature", "temperature"))
    outside_idx = _find_index_in_headers(headers, ("outside temperature", "outside temp", "exterior temperature", "outdoor temp"))
    fan_idx = _find_index_in_headers(headers, ("fan", "fan setting", "fan mode"))
    cooling_idx = _find_index_in_headers(headers, ("equipment status", "status", "equipment", "cooling status"))
    condenser_idx = _find_index_in_headers(headers, ("condenser minutes", "condenser runtime"))

    def _series_value(series: List, idx: int) -> str:
        if idx < 0 or idx >= len(series):
            return ""
        value = series[idx]
        if value is None:
            return ""
        return str(value)

    def _fan_text(val: str) -> str:
        t = (val or "").strip().upper()
        if t == "A":
            return "Auto"
        if t == "C":
            return "Circulate"
        if t == "O":
            return "On"
        return val

    def _cooling_text(val: str) -> str:
        t = (val or "").strip()
        if not t:
            return ""
        if t in ("1", "1.0", "true", "True"):
            return "Cooling"
        if t in ("0", "0.0", "false", "False"):
            return "Idle"
        try:
            return "Cooling" if float(t) >= 1 else "Idle"
        except ValueError:
            return t

    history_rows: List[List[str]] = []
    for i in range(row_count):
        row = [""] * len(headers)
        # build_dashboard_html always uses row[0] for chart labels.
        if row:
            row[0] = _series_value(chart_labels, i)
        if setpoint_idx is not None and setpoint_idx < len(row):
            row[setpoint_idx] = _series_value(setpoint_series, i)
        if actual_idx is not None and actual_idx < len(row):
            row[actual_idx] = _series_value(actual_series, i)
        if outside_idx is not None and outside_idx < len(row):
            row[outside_idx] = _series_value(outside_series, i)
        if fan_idx is not None and fan_idx < len(row):
            row[fan_idx] = _fan_text(_series_value(fan_series, i))
        if cooling_idx is not None and cooling_idx < len(row):
            row[cooling_idx] = _cooling_text(_series_value(cooling_series, i))
        if condenser_idx is not None and condenser_idx < len(row):
            row[condenser_idx] = _series_value(condenser_minutes_series, i)
        history_rows.append(row)

    return headers, latest_row, history_rows


def run_test_mode_dashboard() -> None:
    # Test mode intentionally avoids spreadsheet access; it regenerates HTML from cached JSON.
    public_dir = base_dir.parent / "Web"
    payload_path = public_dir / "dashboard_data.json"
    if not payload_path.exists():
        raise SystemExit(f"test_mode expects cached payload at {payload_path}")
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in cached payload {payload_path}: {exc}") from exc

    headers, latest_row, history_rows = _reconstruct_history_rows_from_payload(payload)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target_path = TEMP_DIR / "dashboard.html"
    build_dashboard_html(headers, latest_row, history_rows, target_path)

    public_dir.mkdir(parents=True, exist_ok=True)
    public_copy = public_dir / "dashboard_public.html"
    build_dashboard_html(headers, latest_row, history_rows, public_copy)
    print(f"Dashboard generated (test_mode) at: {target_path.resolve()}")
    logger.info("test_mode HTML generated from cached payload %s", payload_path)


def _format_archive_label(slug: str) -> str:
    try:
        parsed = datetime.strptime(slug, "%Y-%m-%d")
        return parsed.strftime("%b %d, %Y")
    except ValueError:
        return slug


def run_projected_range(
    start: date,
    end: date,
    *,
    weather_source: str = "auto",
    simulate_requests: bool = False,
    request_every_days: int = 3,
    request_setpoint_delta_f: float = 2.0,
    request_setpoint_deltas_f: Optional[List[float]] = None,
    request_deltas_mode: str = "random",
) -> List[dict]:
    """
    Generate/overwrite archive JSON datasets for each day in [start, end].

    Returns the per-day summaries printed during generation.
    """
    archive_dir = ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Build archive list = existing files + target range, so any loaded JSON can still show the full picker.
    archive_slugs = set()
    if archive_dir.exists():
        for entry in archive_dir.glob("*.json"):
            if entry.stem:
                archive_slugs.add(entry.stem)
    for day in _daterange_inclusive(start, end):
        archive_slugs.add(day.strftime("%Y-%m-%d"))

    archive_dates = [
        {"slug": slug, "label": _format_archive_label(slug)}
        for slug in sorted(archive_slugs, reverse=True)
    ]

    summaries: List[dict] = []
    for day in _daterange_inclusive(start, end):
        slug = day.strftime("%Y-%m-%d")
        target_json = archive_dir / f"{slug}.json"
        existed = target_json.exists()
        payload, summary = build_projected_dashboard_payload(
            day,
            archive_dates,
            weather_source=weather_source,
            simulate_requests=simulate_requests,
            request_every_days=request_every_days,
            request_setpoint_delta_f=request_setpoint_delta_f,
            request_setpoint_deltas_f=request_setpoint_deltas_f,
            request_deltas_mode=request_deltas_mode,
        )
        summary["datasetAction"] = "overwritten" if existed else "created"
        target_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        summaries.append(summary)
        logger.info(
            "Projected dataset %s (%s): drop=%s°F/hr, runtime=%s min, condenser_hours=%s",
            slug,
            summary["datasetAction"],
            summary["hourlyCoolingDropApplied"],
            summary["totalProjectedHvacRuntimeMinutes"],
            ",".join(str(h) for h in summary["condenserHours"]) or "-",
        )

    return summaries


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Thermostat dashboard generator")
    parser.add_argument(
        "--project-date",
        metavar="YYYY-MM-DD",
        help="Generate/overwrite a single projected archive JSON file for the given date.",
    )
    parser.add_argument(
        "--project-range",
        nargs=2,
        metavar=("START", "END"),
        help="Generate/overwrite projected archive JSON files for each day in the inclusive range.",
    )
    parser.add_argument(
        "--weather",
        choices=("auto", "synthetic", "open-meteo"),
        default="auto",
        help="Outside temperature source for projection generation (default: auto).",
    )
    parser.add_argument(
        "--simulate-requests",
        action="store_true",
        help="For projected datasets, periodically lower afternoon setpoints and populate Type/Studio as if a request came in.",
    )
    parser.add_argument(
        "--request-every-days",
        type=int,
        default=3,
        help="When --simulate-requests is set, apply a request day every N days (default: 3).",
    )
    parser.add_argument(
        "--request-delta",
        type=float,
        default=2.0,
        help="When --simulate-requests is set, lower setpoints by this many °F in the request window (default: 2).",
    )
    parser.add_argument(
        "--request-deltas",
        type=str,
        default="",
        help="Optional comma-separated list of °F deltas to cycle through on request days (e.g. '1,2,3,5').",
    )
    parser.add_argument(
        "--request-deltas-mode",
        choices=("random", "cycle"),
        default="random",
        help="How to select a delta from --request-deltas on request days (default: random).",
    )
    args = parser.parse_args(argv)
    request_deltas: Optional[List[float]] = None
    if args.request_deltas:
        try:
            request_deltas = [float(part.strip()) for part in str(args.request_deltas).split(",") if part.strip()]
        except ValueError:
            raise SystemExit("--request-deltas must be a comma-separated list of numbers, e.g. '1,2,3,5'")

    if args.project_date or args.project_range:
        if args.project_date and args.project_range:
            raise SystemExit("Use only one of --project-date or --project-range.")
        if args.project_date:
            target = _parse_date_only(args.project_date)
            run_projected_range(
                target,
                target,
                weather_source=args.weather,
                simulate_requests=bool(args.simulate_requests),
                request_every_days=int(args.request_every_days),
                request_setpoint_delta_f=float(args.request_delta),
                request_setpoint_deltas_f=request_deltas,
                request_deltas_mode=str(args.request_deltas_mode),
            )
            return
        start_s, end_s = args.project_range
        run_projected_range(
            _parse_date_only(start_s),
            _parse_date_only(end_s),
            weather_source=args.weather,
            simulate_requests=bool(args.simulate_requests),
            request_every_days=int(args.request_every_days),
            request_setpoint_delta_f=float(args.request_delta),
            request_setpoint_deltas_f=request_deltas,
            request_deltas_mode=str(args.request_deltas_mode),
        )
        return

    run_live_dashboard()


if __name__ == "__main__":
    main()
