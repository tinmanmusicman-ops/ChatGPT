from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover (older Python)
    ZoneInfo = None  # type: ignore[assignment]


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parents[2]
AI_BOTS_ROOT = WORKSPACE_ROOT / "ai-bots"
GLOBAL_CONFIG_PATH = AI_BOTS_ROOT / "shared" / "Global.json"
THERMOSTAT_CONFIG_PATH = AI_BOTS_ROOT / "Thermostats" / "bot-assets" / "config.json"
ARCHIVE_DIR = SCRIPT_DIR.parent / "Web" / "chart hist"
DASHBOARD_DATA_TEMPLATE_PATH = SCRIPT_DIR.parent / "Web" / "dashboard_data.json"

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_SETPOINT_F = 75.0
OCCUPIED_SETPOINT_F = 72.0
# Standard schedule: occupied setpoint applies from 1:00 PM through 7:59 PM.
# (Inclusive of the hour starting at 1:00 PM and ending at 7:59 PM.)
OCCUPIED_START_HOUR = 13  # 1:00 PM
OCCUPIED_END_HOUR_EXCLUSIVE = 20  # through 7:59 PM
CHART_INDOOR_SERIES_KEY = "actual"  # dashboard_client.js reads getDashboardValue("actual", [])

LOCAL_EVENT_DEFAULT_SETPOINT_F = 75.0
LOCAL_EVENT_OCCUPIED_SETPOINT_F = 70.0
LOCAL_EVENT_OCCUPIED_START_HOUR = 13  # 1:00 PM
LOCAL_EVENT_OCCUPIED_END_HOUR_EXCLUSIVE = 20  # through 7:59 PM
LOCAL_EVENT_READING_MINUTES = 5.0
LOCAL_EVENT_MAX_ADJUSTED_READINGS = 3
LOCAL_EVENT_PROJECTED_RUNTIME_MINUTES = 40.0

HOURLY_DEFAULT_SETPOINT_F = 75.0
HOURLY_OCCUPIED_SETPOINT_F = 72.0
HOURLY_OCCUPIED_START_HOUR = 13  # 1:00 PM
# Hourly occupied window ends at 5:00 PM (inclusive), i.e. through 17:59.
HOURLY_OCCUPIED_END_HOUR_EXCLUSIVE = 18
HOURLY_POST_OCCUPIED_SETPOINT_F = 75.0
HOURLY_NIGHT_SETPOINT_F = 75.0
HOURLY_NIGHT_START_HOUR = 18  # 6:00 PM
HOURLY_NIGHT_END_HOUR_EXCLUSIVE = 24  # through 11:59 PM
HOURLY_OVERNIGHT_SETPOINT_F = 75.0  # 12:00 AM through 5:59 AM
HOURLY_RUNTIME_PER_ON_HOUR_MINUTES = 40.0


DEFAULT_MODE = "local"


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _format_archive_label(d: date) -> str:
    # Matches the existing archiveDates label style: "Dec 16, 2025"
    return d.strftime("%b %d, %Y")


def _build_archive_dates() -> List[Dict[str, str]]:
    slugs = []
    for p in ARCHIVE_DIR.glob("*.json"):
        try:
            slug = p.stem
            datetime.strptime(slug, "%Y-%m-%d")
            slugs.append(slug)
        except Exception:
            continue
    slugs = sorted(set(slugs), reverse=True)
    out: List[Dict[str, str]] = []
    for slug in slugs:
        d = datetime.strptime(slug, "%Y-%m-%d").date()
        out.append({"slug": slug, "label": _format_archive_label(d)})
    return out


def _load_template_payload(exclude_slug: Optional[str] = None) -> dict:
    """
    Loads a representative JSON payload to use as a schema template.
    Preference order:
      1) Most recent Web/chart hist/*.json (excluding exclude_slug)
      2) Web/dashboard_data.json
    """
    candidates: List[Path] = []
    for p in ARCHIVE_DIR.glob("*.json"):
        if exclude_slug and p.stem == exclude_slug:
            continue
        candidates.append(p)
    candidates.sort(key=lambda p: p.name, reverse=True)
    if candidates:
        return _load_json(candidates[0])
    if DASHBOARD_DATA_TEMPLATE_PATH.exists():
        return _load_json(DASHBOARD_DATA_TEMPLATE_PATH)
    raise FileNotFoundError("No template JSON found (no chart hist files and no dashboard_data.json).")


def _fmt_chart_label(dt: datetime) -> str:
    weekday = dt.strftime("%A")
    mon = dt.strftime("%b")
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{weekday} {mon} {dt.day}     {hour12}:00 {ampm}"


def _fmt_latest_row_timestamp(dt: datetime) -> str:
    weekday = dt.strftime("%A")
    mon = dt.strftime("%b")
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{weekday} {mon} {dt.day} {dt.year} {hour12}:{dt.minute:02d} {ampm}"


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _interpolate_smooth(out: List[float], i0: int, v0: float, i1: int, v1: float) -> None:
    steps = i1 - i0
    for k in range(steps + 1):
        t = 0.0 if steps == 0 else k / steps
        s = _smoothstep(t)
        out[i0 + k] = round(v0 + (v1 - v0) * s, 1)


def _interpolate_linear(out: List[float], i0: int, v0: float, i1: int, v1: float) -> None:
    steps = i1 - i0
    for k in range(steps + 1):
        t = 0.0 if steps == 0 else k / steps
        out[i0 + k] = round(v0 + (v1 - v0) * t, 1)


@dataclass(frozen=True)
class DayType:
    name: str
    peak_f: float
    minutes_per_degree: float
    reason: str


def _fmt_dt_hour(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:00")


def _flag_for(code: int, is_day_flag: int) -> str:
    # Keep consistent with dashboard_client.js weatherGraphicPaths keys.
    rain_codes = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    partly_codes = {1, 2, 3}
    overcast_codes = {45, 48}
    is_day = bool(is_day_flag)
    if code == 0:
        return "S" if is_day else "N"
    if code in partly_codes:
        return "P"
    if code in overcast_codes:
        return "O"
    if code in rain_codes:
        return "R"
    if 71 <= code <= 77:
        return "O"
    return "O"


def _day_char(is_day_flag: int) -> str:
    return "D" if int(is_day_flag) == 1 else "N"


def _fmt_outside_raw(flag: str, dayc: str, temp_f: float) -> str:
    if float(temp_f).is_integer():
        t = str(int(round(float(temp_f))))
    else:
        t = f"{float(temp_f):.1f}"
    return f"{flag}{dayc}{t} | Open-Meteo"


def _http_get_json(url: str, params: Dict[str, Any]) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": "thermostat-demo-pipeline"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _fetch_open_meteo_hourly(
    lat: float, lon: float, tz: str, day: date, next_day: date
) -> Dict[str, Dict[str, Any]]:
    hourly_fields = "temperature_2m,weather_code,is_day,precipitation"

    def parse_hourly(payload: dict) -> Dict[str, Dict[str, Any]]:
        h = payload.get("hourly") or {}
        times = h.get("time") or []
        temps = h.get("temperature_2m") or []
        codes = h.get("weather_code") or []
        is_day = h.get("is_day") or []
        precip = h.get("precipitation") or [0.0] * len(times)
        if not (len(times) == len(temps) == len(codes) == len(is_day) == len(precip)):
            raise RuntimeError("Open-Meteo returned mismatched hourly arrays.")
        by_time: Dict[str, Dict[str, Any]] = {}
        for t, tf, code, dayflag, p in zip(times, temps, codes, is_day, precip):
            by_time[t] = {
                "temp_f": float(tf),
                "code": int(code),
                "is_day": int(dayflag),
                "precip": float(p) if p is not None else 0.0,
            }
        return by_time

    # First try the archive API for the full two-day span.
    try:
        payload = _http_get_json(
            ARCHIVE_API_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": day.isoformat(),
                "end_date": next_day.isoformat(),
                "hourly": hourly_fields,
                "temperature_unit": "fahrenheit",
                "timezone": tz,
            },
        )
        return parse_hourly(payload)
    except Exception:
        # Some dates may exceed archive range; fall back to:
        # - archive for the target day
        # - forecast for the next day (to cover 12:00 AM–5:00 AM)
        archive_payload = _http_get_json(
            ARCHIVE_API_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
                "hourly": hourly_fields,
                "temperature_unit": "fahrenheit",
                "timezone": tz,
            },
        )
        forecast_payload = _http_get_json(
            FORECAST_API_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "start_date": next_day.isoformat(),
                "end_date": next_day.isoformat(),
                "hourly": hourly_fields,
                "temperature_unit": "fahrenheit",
                "timezone": tz,
            },
        )
        merged = parse_hourly(archive_payload)
        merged.update(parse_hourly(forecast_payload))
        return merged


def _classify_day_type(
    flags: List[str], precip: List[float], window_idxs: Iterable[int]
) -> DayType:
    idxs = list(window_idxs)
    window_flags = [flags[i] for i in idxs]
    window_precip = [precip[i] for i in idxs]
    has_rain = any(f == "R" for f in window_flags) or any(p > 0.0 for p in window_precip)
    if has_rain:
        return DayType(
            name="C",
            peak_f=68.0,
            minutes_per_degree=15.0,
            reason="precipitation present in 10:00 AM-4:00 PM window",
        )
    count_overcastish = sum(1 for f in window_flags if f in ("O", "P"))
    count_sunny = sum(1 for f in window_flags if f == "S")
    if count_overcastish > count_sunny:
        return DayType(
            name="B",
            peak_f=74.0,
            minutes_per_degree=30.0,
            reason=f"overcast/partly dominates (O/P={count_overcastish} vs S={count_sunny})",
        )
    return DayType(
        name="A",
        peak_f=80.0,
        minutes_per_degree=60.0,
        reason=f"sun dominates (S={count_sunny} vs O/P={count_overcastish})",
    )


def _build_setpoint_series(labels_dt: List[datetime]) -> List[float]:
    series: List[float] = []
    for dt in labels_dt:
        if OCCUPIED_START_HOUR <= dt.hour < OCCUPIED_END_HOUR_EXCLUSIVE:
            series.append(OCCUPIED_SETPOINT_F)
        else:
            series.append(DEFAULT_SETPOINT_F)
    return series


def _build_setpoint_series_local_event(labels_dt: List[datetime]) -> List[float]:
    series: List[float] = []
    for dt in labels_dt:
        if LOCAL_EVENT_OCCUPIED_START_HOUR <= dt.hour < LOCAL_EVENT_OCCUPIED_END_HOUR_EXCLUSIVE:
            series.append(LOCAL_EVENT_OCCUPIED_SETPOINT_F)
        else:
            series.append(LOCAL_EVENT_DEFAULT_SETPOINT_F)
    return series


def _build_setpoint_series_hourly(labels_dt: List[datetime], target_day: date) -> List[float]:
    """
    HOURLY setpoint schedule.

    Summer policy (Aug 1–Oct 30 inclusive):
      - default 80F
      - occupied 75F (13:00-17:59)
      - evening 78F (18:00-23:59)
      - overnight 80F (00:00-05:59)

    Winter policy (Nov 1–Dec 31 inclusive): default 75F, occupied 72F (13:00-17:59), evening 75F (18:00-23:59).
    """

    year = int(target_day.year)
    aug_1 = date(year, 8, 1)
    oct_31 = date(year, 10, 31)  # exclusive upper bound => through Oct 30
    nov_1 = date(year, 11, 1)
    jan_1_next = date(year + 1, 1, 1)

    if aug_1 <= target_day < oct_31:
        default_sp = 80.0
        occupied_sp = 75.0
        evening_sp = 78.0
        overnight_sp = 80.0
    elif nov_1 <= target_day < jan_1_next:
        default_sp = 75.0
        occupied_sp = 72.0
        evening_sp = 75.0
        overnight_sp = 75.0
    else:
        default_sp = HOURLY_DEFAULT_SETPOINT_F
        occupied_sp = HOURLY_OCCUPIED_SETPOINT_F
        evening_sp = HOURLY_NIGHT_SETPOINT_F
        overnight_sp = HOURLY_OVERNIGHT_SETPOINT_F

    series: List[float] = []
    for dt in labels_dt:
        hour = int(dt.hour)
        in_day_occupied = HOURLY_OCCUPIED_START_HOUR <= hour < HOURLY_OCCUPIED_END_HOUR_EXCLUSIVE  # 13-17
        in_evening = HOURLY_NIGHT_START_HOUR <= hour < HOURLY_NIGHT_END_HOUR_EXCLUSIVE  # 18-23
        in_overnight = 0 <= hour < 6  # 00-05
        if in_day_occupied:
            series.append(occupied_sp)
        elif in_evening:
            series.append(evening_sp)
        elif in_overnight:
            series.append(overnight_sp)
        else:
            series.append(default_sp)
    return series


def _build_hourly_anchor_baseline(
    labels_dt: List[datetime], target_day: date, *, day_type_name: Optional[str] = None
) -> List[float]:
    """
    HOURLY baseline indoor temperature curve (NO HVAC), from fixed anchors:
      Winter-style anchors (target >= Dec 1):
        6:00  -> 65
        13:00 -> 70
        16:00 -> 73
        17:00 -> 75
        19:00 -> 73
        23:00 -> 70
        5:00  -> 65 (next day)

      Summer-style anchors (target >= Aug 1 and < Dec 1):
        6:00  -> 65
        13:00 -> 73
        16:00 -> 75
        17:00 -> 77
        19:00 -> 80
        23:00 -> 70
        5:00  -> 65 (next day)

    Interpolate linearly between anchors (hour-to-hour).
    """

    year = int(target_day.year)
    aug_1 = date(year, 8, 1)
    aug_31 = date(year, 8, 31)
    sep_1 = date(year, 9, 1)
    oct_1 = date(year, 10, 1)
    oct_31 = date(year, 10, 31)
    nov_1 = date(year, 11, 1)
    dec_1 = date(year, 12, 1)
    jan_1_next = date(year + 1, 1, 1)

    is_full_sun = str(day_type_name or "").strip().upper() == "A"

    if dec_1 <= target_day < jan_1_next:
        if is_full_sun:
            anchors = {
                6: 65.0,
                13: 70.0,
                16: 73.0,
                17: 75.0,
                19: 73.0,
                23: 70.0,
                5: 65.0,
            }
        else:
            anchors = {
                6: 62.0,
                13: 68.0,
                16: 69.0,
                17: 70.0,
                19: 68.0,
                23: 65.0,
                5: 63.0,
            }
    elif nov_1 <= target_day < dec_1:
        if is_full_sun:
            anchors = {
                6: 65.0,
                13: 70.0,
                16: 75.0,
                17: 77.0,
                19: 77.0,
                23: 68.0,
                5: 65.0,
            }
        else:
            anchors = {
                6: 65.0,
                13: 70.0,
                16: 70.0,
                17: 72.0,
                19: 73.0,
                23: 68.0,
                5: 65.0,
            }
    elif oct_1 <= target_day < oct_31:
        # For October: use a higher baseline for "full sun" days (DayType A); otherwise use the cooler baseline.
        if is_full_sun:
            anchors = {
                6: 70.0,
                13: 76.0,
                16: 77.0,
                17: 79.0,
                19: 80.0,
                23: 70.0,
                5: 68.0,
            }
        else:
            anchors = {
                6: 65.0,
                13: 70.0,
                16: 72.0,
                17: 73.0,
                19: 74.0,
                23: 70.0,
                5: 68.0,
            }
    elif sep_1 <= target_day < oct_1:
        if is_full_sun:
            anchors = {
                6: 70.0,
                13: 77.0,
                16: 78.0,
                17: 80.0,
                19: 77.0,
                23: 70.0,
                5: 65.0,
            }
        else:
            anchors = {
                6: 70.0,
                13: 73.0,
                16: 75.0,
                17: 76.0,
                19: 75.0,
                23: 70.0,
                5: 65.0,
            }
    elif aug_1 <= target_day < aug_31:
        if is_full_sun:
            anchors = {
                6: 65.0,
                13: 73.0,
                16: 75.0,
                17: 77.0,
                19: 80.0,
                23: 70.0,
                5: 65.0,
            }
        else:
            anchors = {
                6: 65.0,
                13: 73.0,
                16: 74.0,
                17: 75.0,
                19: 76.0,
                23: 70.0,
                5: 65.0,
            }
    else:
        # Default to winter-style anchors if no seasonal override is specified.
        anchors = {
            6: 65.0,
            13: 70.0,
            16: 73.0,
            17: 75.0,
            19: 73.0,
            23: 70.0,
            5: 65.0,
        }

    base = [0.0] * 24
    i_6 = _index_for_hour(labels_dt, 6)
    i_13 = _index_for_hour(labels_dt, 13)
    i_16 = _index_for_hour(labels_dt, 16)
    i_17 = _index_for_hour(labels_dt, 17)
    i_19 = _index_for_hour(labels_dt, 19)
    i_23 = _index_for_hour(labels_dt, 23)
    i_5 = _index_for_hour(labels_dt, 5)

    _interpolate_linear(base, i_6, anchors[6], i_13, anchors[13])
    _interpolate_linear(base, i_13, anchors[13], i_16, anchors[16])
    _interpolate_linear(base, i_16, anchors[16], i_17, anchors[17])
    _interpolate_linear(base, i_17, anchors[17], i_19, anchors[19])
    _interpolate_linear(base, i_19, anchors[19], i_23, anchors[23])
    _interpolate_linear(base, i_23, anchors[23], i_5, anchors[5])

    return [round(float(v), 1) for v in base]


def _build_fan_series_hourly(labels_dt: List[datetime], target_day: date) -> List[str]:
    """
    Fan schedule, HOURLY.

    For Aug 1–Aug 30:
      00:00-05:59 -> C
      06:00-12:59 -> O
      13:00-18:59 -> A
      19:00-23:59 -> O

    For Sep 1–Sep 30:
      00:00-05:59 -> O
      06:00-12:59 -> C
      13:00-18:59 -> A
      19:00-23:59 -> O

    For Oct 1–Oct 30:
      00:00-05:59 -> O
      06:00-12:59 -> C
      13:00-18:59 -> A
      19:00-23:59 -> O

    For Nov 1–Nov 30:
      00:00-18:59 -> A
      19:00-23:59 -> O

    For Dec 1–Dec 30:
      00:00-12:59 -> A
      13:00-18:59 -> O
      19:00-23:59 -> C

    Otherwise defaults to Auto all day.
    """

    year = int(target_day.year)
    aug_1 = date(year, 8, 1)
    sep_1 = date(year, 9, 1)
    oct_1 = date(year, 10, 1)
    nov_1 = date(year, 11, 1)
    dec_1 = date(year, 12, 1)
    aug_31 = date(year, 8, 31)  # exclusive upper bound to include through Aug 30
    oct_31 = date(year, 10, 31)  # exclusive upper bound to include through Oct 30
    dec_31 = date(year, 12, 31)  # exclusive upper bound to include through Dec 30

    # Default to Auto if we don't have an explicit month policy.
    if not (aug_1 <= target_day < dec_31):
        return ["A"] * 24

    series: List[str] = []
    for dt in labels_dt:
        hour = int(dt.hour)
        if aug_1 <= target_day < aug_31:
            if 0 <= hour < 6:
                series.append("C")
            elif 6 <= hour < 13:
                series.append("O")
            elif 13 <= hour < 19:
                series.append("A")
            else:
                series.append("O")
        elif sep_1 <= target_day < oct_1:
            if 0 <= hour < 6:
                series.append("O")
            elif 6 <= hour < 13:
                series.append("C")
            elif 13 <= hour < 19:
                series.append("A")
            else:
                series.append("O")
        elif oct_1 <= target_day < oct_31:
            if 0 <= hour < 6:
                series.append("O")
            elif 6 <= hour < 13:
                series.append("C")
            elif 13 <= hour < 19:
                series.append("A")
            else:
                series.append("O")
        elif nov_1 <= target_day < dec_1:
            series.append("A" if hour < 19 else "O")
        elif dec_1 <= target_day < dec_31:
            if hour < 13:
                series.append("A")
            elif hour < 19:
                series.append("O")
            else:
                series.append("C")
        else:
            series.append("A")
    return series


def _apply_cooling_adjustment_hourly(normal_next: float, setpoint_next: float, hourly_drop: float) -> float:
    """
    Apply a 1-hour cooling adjustment to the next hour without ever "heating" above the baseline.

    If setpoint_next is higher than the baseline, we still allow temps below setpoint (HVAC would be off),
    and we never raise the value above normal_next.
    """

    cooled = float(normal_next) - float(hourly_drop)
    if float(setpoint_next) <= float(normal_next):
        return min(float(normal_next), max(float(setpoint_next), float(cooled)))
    return min(float(normal_next), float(cooled))


def _index_for_hour(labels_dt: List[datetime], hour_of_day: int) -> int:
    for idx, dt in enumerate(labels_dt):
        if dt.hour == hour_of_day:
            return idx
    raise ValueError(f"Hour {hour_of_day:02d}:00 not found in 24h window.")


def _build_baseline_series(day_type: DayType, labels_dt: List[datetime], peak_hour: int) -> List[float]:
    peak = day_type.peak_f
    base = [0.0] * 24

    i_6am = _index_for_hour(labels_dt, 6)
    i_1pm = _index_for_hour(labels_dt, 13)
    i_4pm = _index_for_hour(labels_dt, 16)
    i_peak = _index_for_hour(labels_dt, peak_hour)
    i_5am = _index_for_hour(labels_dt, 5)

    anchor_6am = 65.0
    anchor_1pm = anchor_6am + 0.45 * (peak - anchor_6am)
    anchor_4pm = anchor_6am + 0.70 * (peak - anchor_6am)
    anchor_peak = peak
    anchor_5am = 65.0

    if not (i_6am < i_1pm < i_4pm < i_peak < i_5am):
        raise ValueError(
            f"Unexpected anchor order for peak_hour={peak_hour}: "
            f"6am={i_6am}, 1pm={i_1pm}, 4pm={i_4pm}, peak={i_peak}, 5am={i_5am}"
        )

    _interpolate_smooth(base, i_6am, anchor_6am, i_1pm, anchor_1pm)
    _interpolate_smooth(base, i_1pm, anchor_1pm, i_4pm, anchor_4pm)
    _interpolate_smooth(base, i_4pm, anchor_4pm, i_peak, anchor_peak)
    _interpolate_smooth(base, i_peak, anchor_peak, i_5am, anchor_5am)
    return base


def _simulate_controlled(
    baseline: List[float], setpoint: List[float], day_type: DayType
) -> Tuple[List[float], List[int], List[float], List[int], List[Dict[str, Any]]]:
    deg_per_min = 1.0 / day_type.minutes_per_degree
    block_drop = 5.0 * deg_per_min

    controlled = [0.0] * 24
    cooling = [0] * 24
    runtime = [0.0] * 24
    saturated_hours: List[int] = []
    diagnostics: List[Dict[str, Any]] = []

    prev_controlled: Optional[float] = None
    for i in range(24):
        # IMPORTANT CONTROL RULE:
        # - Hour t starts from max(baseline[t], controlled[t-1]).
        # - The charted value for hour t is the cooled controlled[t] (when runtime > 0).
        start_temp = baseline[i] if prev_controlled is None else max(baseline[i], prev_controlled)
        carried = None if prev_controlled is None else float(prev_controlled)
        sp = float(setpoint[i])

        if start_temp <= sp:
            # HVAC off: controlled follows baseline for this hour.
            controlled[i] = baseline[i]
            cooling[i] = 0
            runtime[i] = 0.0
            prev_controlled = controlled[i]
            diagnostics.append(
                {
                    "baseline_temp_f": float(baseline[i]),
                    "carried_temp_from_prev_hour_f": carried,
                    "start_temp_used_f": float(start_temp),
                    "setpoint_f": float(sp),
                    "cooling_rate_degF_per_min": float(deg_per_min),
                    "runtime_minutes_applied": 0,
                    "calculated_temp_drop_f": 0.0,
                    "final_controlled_temp_f": float(controlled[i]),
                }
            )
            continue

        blocks_needed = math.ceil((start_temp - sp) / block_drop) if block_drop > 0 else 12
        blocks_applied = min(12, max(0, blocks_needed))
        minutes = blocks_applied * 5
        end_temp = start_temp - blocks_applied * block_drop
        end_temp = max(sp, end_temp)

        if minutes >= 60 and end_temp > sp + 1e-6:
            saturated_hours.append(i)

        # HVAC on: store the cooled result as the charted temperature for this hour.
        controlled[i] = round(end_temp, 1)
        cooling[i] = 1 if minutes > 0 else 0
        runtime[i] = float(minutes)
        prev_controlled = controlled[i]

        if minutes > 0:
            # Sanity checks: no overshoot below setpoint, and we must not "snap back" to baseline.
            if controlled[i] < sp - 1e-6:
                raise RuntimeError(f"Controlled temp overshot below setpoint at hour {i}: {controlled[i]} < {sp}")
            if controlled[i] > start_temp + 1e-6:
                raise RuntimeError(f"Controlled temp increased during cooling at hour {i}: {controlled[i]} > {start_temp}")

        diagnostics.append(
            {
                "baseline_temp_f": float(baseline[i]),
                "carried_temp_from_prev_hour_f": carried,
                "start_temp_used_f": float(start_temp),
                "setpoint_f": float(sp),
                "cooling_rate_degF_per_min": float(deg_per_min),
                "runtime_minutes_applied": int(minutes),
                "calculated_temp_drop_f": float(round(float(start_temp) - float(controlled[i]), 3)),
                "final_controlled_temp_f": float(controlled[i]),
            }
        )

    return controlled, cooling, runtime, saturated_hours, diagnostics


def _coerce_series(payload: dict, key: str) -> List[float]:
    series = payload.get(key)
    if not isinstance(series, list):
        raise RuntimeError(f"Expected payload['{key}'] to be a list.")
    if len(series) != 24:
        raise RuntimeError(f"Expected payload['{key}'] length 24, got {len(series)}.")
    return [float(v) for v in series]


def _coerce_int_series(payload: dict, key: str) -> List[int]:
    series = payload.get(key)
    if not isinstance(series, list):
        raise RuntimeError(f"Expected payload['{key}'] to be a list.")
    if len(series) != 24:
        raise RuntimeError(f"Expected payload['{key}'] length 24, got {len(series)}.")
    return [int(float(v)) for v in series]


def _apply_local_cooling_event(
    temps: List[float],
    setpoint: List[float],
    day_type: DayType,
    *,
    reading_minutes: float = LOCAL_EVENT_READING_MINUTES,
    max_adjusted_readings: int = LOCAL_EVENT_MAX_ADJUSTED_READINGS,
) -> Tuple[List[float], List[bool], List[float], float, Optional[int], int, List[Dict[str, Any]]]:
    """
    Local adjustment logic (NO re-simulation; single cooling event only):
    - Find the first index i where temp[i] > setpoint[i].
    - Turn condenser_on[i] on.
    - Adjust ONLY the next 1..N readings (N max), each by one 5-minute cooling step:
        drop_per_reading = reading_minutes / minutes_per_degree
      Clamp to setpoint. Stop early if the adjusted point hits setpoint.
    - After the adjustment window, force condenser off (no carry forward).
    """

    if len(temps) != 24 or len(setpoint) != 24:
        raise RuntimeError("Expected temps/setpoint arrays of length 24.")

    minutes_per_degree = float(day_type.minutes_per_degree)
    if minutes_per_degree <= 0:
        raise RuntimeError("Invalid cooling minutes_per_degree.")
    drop_per_reading = float(reading_minutes) / minutes_per_degree

    adjusted = [round(float(v), 1) for v in temps]
    on = [False] * 24
    runtime = [0.0] * 24
    diagnostics: List[Dict[str, Any]] = []

    first_exceed_idx: Optional[int] = None
    for i in range(24):
        if adjusted[i] > float(setpoint[i]):
            first_exceed_idx = i
            break

    adjusted_readings = 0
    if first_exceed_idx is not None:
        i = first_exceed_idx
        on[i] = True
        runtime[i] = float(reading_minutes)

        for k in range(1, min(max_adjusted_readings, 23 - i) + 1):
            idx = i + k
            before = adjusted[idx]
            after = round(before - drop_per_reading, 1)
            after = max(float(setpoint[idx]), after)
            adjusted[idx] = after
            adjusted_readings += 1

            if adjusted[idx] <= float(setpoint[idx]):
                on[idx] = False
                runtime[idx] = 0.0
                break

            on[idx] = True
            runtime[idx] = float(reading_minutes)

        # After the adjustment window, force condenser off (no carry forward).
        for idx in range(i + max_adjusted_readings + 1, 24):
            on[idx] = False
            runtime[idx] = 0.0

    for i in range(24):
        diagnostics.append(
            {
                "index": i,
                "temp_before_f": float(temps[i]),
                "setpoint_f": float(setpoint[i]),
                "temp_after_f": float(adjusted[i]),
                "condenser_on": bool(on[i]),
                "runtime_minutes": float(runtime[i]),
            }
        )

    return (
        adjusted,
        on,
        runtime,
        float(round(drop_per_reading, 6)),
        first_exceed_idx,
        adjusted_readings,
        diagnostics,
    )


def _update_dataset_in_place(
    payload: dict,
    labels_dt: List[datetime],
    labels: List[str],
    outside: List[float],
    outside_flags: List[str],
    outside_day_chars: List[str],
    baseline: List[float],
    controlled: List[float],
    setpoint: List[float],
    cooling: List[int],
    runtime: List[float],
    day_type: DayType,
) -> None:
    payload["chartLabels"] = labels
    payload["outside"] = outside
    payload["outsideFlags"] = outside_flags
    payload["outsideFlagDayChars"] = outside_day_chars

    payload["setpoint"] = setpoint
    payload["latestSetpoint"] = float(setpoint[-1])

    # CRITICAL OVERRIDE — AUTHORITATIVE TEMPERATURE SERIES:
    # The dashboard charts a single indoor series: payload["actual"].
    # When runtime[t] > 0, this MUST be the cooled controlled[t] value (never baseline[t]).
    payload[CHART_INDOOR_SERIES_KEY] = controlled
    payload["latestActual"] = float(controlled[-1])

    # Store baseline (NO HVAC) separately in history list (existing schema).
    payload["history"] = [{"label": lbl, "value": float(val)} for lbl, val in zip(labels, baseline)]

    payload["cooling"] = cooling
    payload["latestCooling"] = int(cooling[-1])

    payload["condenserMinutes"] = runtime
    for idx, minutes in enumerate(runtime):
        if float(minutes) > 0 and abs(float(payload[CHART_INDOOR_SERIES_KEY][idx]) - float(controlled[idx])) > 1e-9:
            raise RuntimeError(
                f"Authoritative indoor series mismatch at hour {idx}: "
                f"{CHART_INDOOR_SERIES_KEY}={payload[CHART_INDOOR_SERIES_KEY][idx]} vs controlled={controlled[idx]}"
            )

    cost_per = float(payload.get("condenserCostPerMinute") or 0.05)
    payload["condenserCostPerMinute"] = cost_per
    total_minutes = float(sum(runtime))
    payload["totalCondenserMinutesValue"] = total_minutes
    payload["totalCondenserMinutes"] = str(int(total_minutes) if total_minutes.is_integer() else round(total_minutes, 1))
    payload["totalCondenserCostValue"] = float(total_minutes * cost_per)
    payload["totalCondenserCost"] = f"${total_minutes * cost_per:,.2f}"

    payload["fan"] = ["A"] * 24
    payload["latestFan"] = "A"

    payload["latestCondenserState"] = "On" if cooling[-1] == 1 else "Off"

    payload["latestOutside"] = float(outside[-1])
    payload["latestOutsideRaw"] = _fmt_outside_raw(outside_flags[-1], outside_day_chars[-1], outside[-1])
    payload["latestOutsideDaylight"] = outside_day_chars[-1] != "N"
    payload["latestOutsideFlagDayChar"] = outside_day_chars[-1]

    existing_ts = str(payload.get("generatedTimestamp", "")).strip()
    if "| SimType" in existing_ts:
        existing_ts = existing_ts.split("| SimType", 1)[0].strip()
    payload["generatedTimestamp"] = f"{existing_ts} | SimType {day_type.name} ({day_type.reason})".strip(" |")

    headers = [str(h).strip().lower() for h in (payload.get("headers") or [])]
    latest_row = payload.get("latestRow")
    if isinstance(latest_row, list) and latest_row:
        latest_row[0] = _fmt_latest_row_timestamp(labels_dt[-1])

        def idx_of(name: str) -> Optional[int]:
            try:
                return headers.index(name)
            except ValueError:
                return None

        idx = idx_of("current temperature")
        if idx is not None and idx < len(latest_row):
            val = controlled[-1]
            latest_row[idx] = str(int(val)) if float(val).is_integer() else f"{val:.1f}"

        idx = idx_of("cooling set point")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = str(int(setpoint[-1])) if float(setpoint[-1]).is_integer() else f"{setpoint[-1]:.1f}"

        idx = idx_of("fan setting")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = "Auto"

        idx = idx_of("equipment status")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = "Cooling" if cooling[-1] == 1 else "Idle"

        idx = idx_of("outside temp")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = payload["latestOutsideRaw"]

        idx = idx_of("condenser state")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = payload["latestCondenserState"]

        idx = idx_of("condenser minutes")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = str(int(runtime[-1])) if float(runtime[-1]).is_integer() else f"{runtime[-1]:.1f}"

        payload["latestRow"] = latest_row


def _update_dataset_local_hvac(
    payload: dict,
    *,
    temps: List[float],
    cooling: List[int],
    runtime: Optional[List[float]] = None,
    labels_dt: List[datetime],
) -> None:
    payload[CHART_INDOOR_SERIES_KEY] = temps
    payload["latestActual"] = float(temps[-1])

    payload["cooling"] = cooling
    payload["latestCooling"] = int(cooling[-1])

    if runtime is not None:
        payload["condenserMinutes"] = runtime
        payload["latestCondenserState"] = "On" if cooling[-1] == 1 else "Off"

        cost_per = float(payload.get("condenserCostPerMinute") or 0.05)
        payload["condenserCostPerMinute"] = cost_per
        total_minutes = float(sum(runtime))
        payload["totalCondenserMinutesValue"] = total_minutes
        payload["totalCondenserMinutes"] = str(
            int(total_minutes) if total_minutes.is_integer() else round(total_minutes, 1)
        )
        payload["totalCondenserCostValue"] = float(total_minutes * cost_per)
        payload["totalCondenserCost"] = f"${total_minutes * cost_per:,.2f}"

    headers = [str(h).strip().lower() for h in (payload.get("headers") or [])]
    latest_row = payload.get("latestRow")
    if isinstance(latest_row, list) and latest_row:
        latest_row[0] = _fmt_latest_row_timestamp(labels_dt[-1])

        def idx_of(name: str) -> Optional[int]:
            try:
                return headers.index(name)
            except ValueError:
                return None

        idx = idx_of("current temperature")
        if idx is not None and idx < len(latest_row):
            val = temps[-1]
            latest_row[idx] = str(int(val)) if float(val).is_integer() else f"{val:.1f}"

        idx = idx_of("equipment status")
        if idx is not None and idx < len(latest_row):
            latest_row[idx] = "Cooling" if cooling[-1] == 1 else "Idle"

        if runtime is not None:
            idx = idx_of("condenser state")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = payload["latestCondenserState"]

            idx = idx_of("condenser minutes")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = str(int(runtime[-1])) if float(runtime[-1]).is_integer() else f"{runtime[-1]:.1f}"

        payload["latestRow"] = latest_row


def _resolve_target_date(spec: str, tz: str) -> date:
    spec = spec.strip().lower()
    if spec == "yesterday":
        if ZoneInfo is None:
            # Fall back to local date if zoneinfo unavailable.
            return (datetime.now() - timedelta(days=1)).date()
        return (datetime.now(ZoneInfo(tz)) - timedelta(days=1)).date()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(spec, fmt).date()
        except ValueError:
            continue
    # Allow bare month/day inputs (assume current year in configured timezone).
    # Parse manually to avoid datetime.strptime() deprecation warnings.
    for sep in ("/", "-"):
        if sep in spec:
            parts = spec.split(sep)
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                month = int(parts[0])
                day = int(parts[1])
                if ZoneInfo is None:
                    year = datetime.now().year
                else:
                    year = datetime.now(ZoneInfo(tz)).year
                return date(year, month, day)
    raise ValueError("Unsupported date format. Use YYYY-MM-DD, MM/DD/YYYY, MM-DD-YYYY, or 'yesterday'.")


def run(
    day_spec: str,
    *,
    peak_hour: int,
    mode: str,
    log_per_hour: bool = True,
) -> None:
    shared = _load_json(GLOBAL_CONFIG_PATH)
    cfg = _load_json(THERMOSTAT_CONFIG_PATH)
    tz = cfg.get("timezone") or "America/Los_Angeles"

    target_day = _resolve_target_date(day_spec, tz)
    next_day = target_day + timedelta(days=1)
    slug = target_day.isoformat()

    target_path = ARCHIVE_DIR / f"{slug}.json"
    created_new = False
    if target_path.exists():
        payload = _load_json(target_path)
    else:
        # Create from scratch using an existing payload as a schema template.
        payload = _load_template_payload(exclude_slug=slug)
        created_new = True

    lat = float(shared["weather_lat"])
    lon = float(shared["weather_lon"])

    start_dt = datetime(target_day.year, target_day.month, target_day.day, 6, 0)
    labels_dt = [start_dt + timedelta(hours=i) for i in range(24)]
    labels = [_fmt_chart_label(dt) for dt in labels_dt]
    # Peak timing is data-driven for this execution (override any season heuristics).
    peak_hour = int(peak_hour)
    # Keep archiveDates consistent across files (used by the history picker).
    payload["archivePath"] = "chart hist"
    archive_dates = _build_archive_dates()
    if not any(entry.get("slug") == slug for entry in archive_dates):
        archive_dates.insert(0, {"slug": slug, "label": _format_archive_label(target_day)})
    payload["archiveDates"] = archive_dates
    payload["generatedDateSlug"] = slug

    mode = str(mode or "").strip().lower()
    if mode not in ("simulate", "local", "hourly"):
        raise ValueError(f"Unsupported mode: {mode} (expected 'local', 'hourly', or 'simulate')")

    def has_hourly_weather_for_window(existing: dict) -> bool:
        try:
            if existing.get("chartLabels") != labels:
                return False
            outside_existing = existing.get("outside")
            flags_existing = existing.get("outsideFlags")
            day_existing = existing.get("outsideFlagDayChars")
            if not (
                isinstance(outside_existing, list)
                and isinstance(flags_existing, list)
                and isinstance(day_existing, list)
                and len(outside_existing) == len(flags_existing) == len(day_existing) == 24
            ):
                return False
            if any(v is None for v in outside_existing):
                return False
            if any(not str(v).strip() for v in flags_existing):
                return False
            if any(not str(v).strip() for v in day_existing):
                return False
            return True
        except Exception:
            return False

    def get_or_fetch_weather(existing: dict) -> Tuple[List[float], List[str], List[str], List[float]]:
        precip_local: List[float] = []
        if has_hourly_weather_for_window(existing):
            out = [round(float(v), 1) for v in existing["outside"]]
            flg = [str(v).strip().upper() for v in existing["outsideFlags"]]
            dayc = [str(v).strip().upper() for v in existing["outsideFlagDayChars"]]
            precip_local = [1.0 if f == "R" else 0.0 for f in flg]
            return out, flg, dayc, precip_local

        weather = _fetch_open_meteo_hourly(lat, lon, tz, target_day, next_day)
        out: List[float] = []
        flg: List[str] = []
        dayc: List[str] = []
        missing: List[str] = []
        for dt in labels_dt:
            key = dt.strftime("%Y-%m-%dT%H:00")
            entry = weather.get(key)
            if not entry:
                missing.append(key)
                out.append(0.0)
                flg.append("O")
                dayc.append("D")
                precip_local.append(0.0)
                continue
            temp_f = round(float(entry["temp_f"]), 1)
            code = int(entry["code"])
            is_day_flag = int(entry["is_day"])
            p = float(entry.get("precip") or 0.0)
            out.append(temp_f)
            flg.append(_flag_for(code, is_day_flag))
            dayc.append(_day_char(is_day_flag))
            precip_local.append(p)
        if missing:
            raise RuntimeError(f"Missing Open-Meteo hours: {missing}")
        return out, flg, dayc, precip_local

    # Local HVAC adjustment mode operates ONLY on existing dataset series (no baseline physics rebuild).
    if mode == "local":
        # Assume the existing baseline curve is correct. Prefer "history" values as baseline when present.
        baseline_history = payload.get("history")
        if (
            isinstance(baseline_history, list)
            and len(baseline_history) == 24
            and all(isinstance(item, dict) and "value" in item for item in baseline_history)
        ):
            temps = [float(item["value"]) for item in baseline_history]
        else:
            temps = _coerce_series(payload, CHART_INDOOR_SERIES_KEY)

        # STEP 1: facility setpoint policy (per reading).
        setpoint = _build_setpoint_series_local_event(labels_dt)
        payload["setpoint"] = setpoint

        # STEP 2: day type selection for cooling strength (value only).
        outside_flags = payload.get("outsideFlags")
        if not isinstance(outside_flags, list) or len(outside_flags) != 24:
            raise RuntimeError("Local mode requires payload['outsideFlags'] (len 24) to determine day type.")
        outside_flags = [str(v).strip().upper() for v in outside_flags]
        precip = [1.0 if f == "R" else 0.0 for f in outside_flags]
        day_type = _classify_day_type(outside_flags, precip, range(4, 11))

        # STEP 3-5: apply a single short cooling event (max 3 readings) and then shut down.
        (
            adjusted,
            condenser_on,
            runtime,
            drop_per_reading,
            first_exceed_idx,
            adjusted_readings,
            local_diag,
        ) = _apply_local_cooling_event(temps, setpoint, day_type)
        cooling = [1 if v else 0 for v in condenser_on]

        # Per prompt: only modify setpoint + chart temperature + condenser_on flags.
        # Per prompt: overwrite only the chart-bound temperature field and condenser_on flags.
        payload[CHART_INDOOR_SERIES_KEY] = adjusted
        payload["cooling"] = cooling
        # STEP 5: project cumulative HVAC runtime (single 40-minute cycle when first exceeded).
        projected = [0.0] * 24
        if first_exceed_idx is not None:
            for idx in range(first_exceed_idx, 24):
                projected[idx] = float(LOCAL_EVENT_PROJECTED_RUNTIME_MINUTES)
        payload["condenserMinutes"] = projected

        warnings: List[str] = []
        errors: List[str] = []
        if log_per_hour:
            print("Per-hour diagnostics (JSONL):")
            for i, dt in enumerate(labels_dt):
                entry = dict(local_diag[i])
                entry.update(
                    {
                        "date": dt.date().isoformat(),
                        "hour_local": dt.strftime("%H:00"),
                        "dt_local": _fmt_dt_hour(dt),
                        "day_type": day_type.name,
                        "cooling_minutes_per_degree": float(day_type.minutes_per_degree),
                        "drop_per_reading_f": float(drop_per_reading),
                        "first_exceed_index": first_exceed_idx,
                        "adjusted_readings": int(adjusted_readings),
                        "projected_runtime_minutes_cumulative": float(projected[i]),
                        "chart_field_written": CHART_INDOOR_SERIES_KEY,
                        "value_written_to_chart_field": float(payload[CHART_INDOOR_SERIES_KEY][i]),
                        "setpoint_f": float(setpoint[i]),
                        "condenser_on_final": bool(cooling[i] == 1),
                    }
                )
                if float(runtime[i]) > 0 and abs(float(adjusted[i]) - float(temps[i])) < 1e-9:
                    warning = f"cooling_applied_but_no_temp_change @ {entry['dt_local']}"
                    entry["WARNING"] = warning
                    warnings.append(warning)
                if abs(float(entry["value_written_to_chart_field"]) - float(entry["temp_after_f"])) > 1e-9:
                    err = f"controlled_temp_not_plotted @ {entry['dt_local']}"
                    entry["ERROR"] = err
                    errors.append(err)
                print(json.dumps(entry, sort_keys=True))

        if errors:
            print("ERRORS:")
            for e in errors:
                print(f"- {e}")
            raise SystemExit(2)

        _save_json(target_path, payload)

        total_runtime = int(LOCAL_EVENT_PROJECTED_RUNTIME_MINUTES if first_exceed_idx is not None else 0)
        first_engaged_idx = next((i for i, m in enumerate(runtime) if float(m) > 0), None)
        print(f"Window: {slug} 06:00 -> {next_day.isoformat()} 05:00 ({tz})")
        print("Mode: local (next-point adjustment; no re-simulation)")
        print(
            f"Setpoint: default {LOCAL_EVENT_DEFAULT_SETPOINT_F:.0f}F; occupied {LOCAL_EVENT_OCCUPIED_SETPOINT_F:.0f}F "
            f"{LOCAL_EVENT_OCCUPIED_START_HOUR:02d}:00-{LOCAL_EVENT_OCCUPIED_END_HOUR_EXCLUSIVE-1:02d}:59"
        )
        print(f"DayType: {day_type.name} ({day_type.reason})")
        print(f"drop_per_reading: {drop_per_reading:.3f}F (assuming {LOCAL_EVENT_READING_MINUTES:.0f}-minute readings)")
        print(f"Adjusted readings: {adjusted_readings}")
        print(f"Total HVAC runtime (projected): {total_runtime} minutes")
        print(f"First hour HVAC engaged: {labels[first_engaged_idx] if first_engaged_idx is not None else 'none'}")
        if warnings:
            print("WARNINGS:")
            for w in warnings:
                print(f"- {w}")
        return

    # HOURLY anchor-based projection: generate baseline and apply a single next-hour cooling event.
    if mode == "hourly":
        outside, outside_flags, outside_day_chars, precip = get_or_fetch_weather(payload)
        payload["chartLabels"] = labels
        payload["outside"] = outside
        payload["outsideFlags"] = outside_flags
        payload["outsideFlagDayChars"] = outside_day_chars

        setpoint = _build_setpoint_series_hourly(labels_dt, target_day=target_day)
        payload["setpoint"] = setpoint
        payload["fan"] = _build_fan_series_hourly(labels_dt, target_day=target_day)

        day_type = _classify_day_type(outside_flags, precip, range(4, 11))
        if day_type.name == "A":
            hourly_drop = 1.0
        elif day_type.name == "B":
            hourly_drop = 2.0
        else:
            hourly_drop = 4.0

        normal_temp = _build_hourly_anchor_baseline(labels_dt, target_day=target_day, day_type_name=day_type.name)

        # PHASE 4: iterative hourly control. Baseline must not override control while out of policy.
        adjusted_temp = list(normal_temp)
        cooling = [0] * 24
        for t in range(23):
            if float(adjusted_temp[t]) > float(setpoint[t]):
                cooling[t] = 1
                adjusted_temp[t + 1] = round(
                    _apply_cooling_adjustment_hourly(
                        normal_next=float(normal_temp[t + 1]),
                        setpoint_next=float(setpoint[t + 1]),
                        hourly_drop=float(hourly_drop),
                    ),
                    1,
                )
            else:
                cooling[t] = 0
                adjusted_temp[t + 1] = float(normal_temp[t + 1])
        # Last hour: no t+1 to adjust.
        cooling[23] = 1 if float(adjusted_temp[23]) > float(setpoint[23]) else 0

        # PHASE 5: cumulative runtime projection (40 minutes per hour where condenser is on).
        # Keep the baseline series for reference in existing schema.
        payload["history"] = [{"label": lbl, "value": float(val)} for lbl, val in zip(labels, normal_temp)]

        payload[CHART_INDOOR_SERIES_KEY] = adjusted_temp
        payload["cooling"] = cooling

        # PHASE 5: per-hour runtime series (chart field): MUST be 0 or 40 only (never cumulative).
        runtime_this_hour = [float(HOURLY_RUNTIME_PER_ON_HOUR_MINUTES) if int(v) == 1 else 0.0 for v in cooling]
        if any((m not in (0.0, float(HOURLY_RUNTIME_PER_ON_HOUR_MINUTES))) for m in runtime_this_hour):
            raise RuntimeError("Hourly runtime must be 0 or 40 only.")
        payload["condenserMinutes"] = runtime_this_hour

        # Cumulative totals (summary fields).
        total_runtime_minutes = float(sum(runtime_this_hour))
        cost_per = float(payload.get("condenserCostPerMinute") or 0.05)
        payload["condenserCostPerMinute"] = cost_per
        payload["totalCondenserMinutesValue"] = total_runtime_minutes
        payload["totalCondenserMinutes"] = str(int(total_runtime_minutes))
        payload["totalCondenserCostValue"] = float(total_runtime_minutes * cost_per)
        payload["totalCondenserCost"] = f"${total_runtime_minutes * cost_per:,.2f}"

        # Update "latest" fields for dashboard cards.
        payload["latestActual"] = float(adjusted_temp[-1])
        payload["latestSetpoint"] = float(setpoint[-1])
        payload["latestCooling"] = int(cooling[-1])
        payload["latestCondenserState"] = "On" if int(cooling[-1]) == 1 else "Off"
        payload["latestFan"] = "A"
        payload["latestOutside"] = float(outside[-1])
        payload["latestOutsideRaw"] = _fmt_outside_raw(outside_flags[-1], outside_day_chars[-1], outside[-1])
        payload["latestOutsideDaylight"] = outside_day_chars[-1] != "N"
        payload["latestOutsideFlagDayChar"] = outside_day_chars[-1]
        payload["generatedTimestamp"] = datetime.now().strftime("%A %b %d %Y %I:%M:%S %p").replace(" 0", " ")

        # Update latestRow if present to avoid stale template values.
        headers = [str(h).strip().lower() for h in (payload.get("headers") or [])]
        latest_row = payload.get("latestRow")
        if isinstance(latest_row, list) and latest_row:
            latest_row[0] = _fmt_latest_row_timestamp(labels_dt[-1])

            def idx_of(name: str) -> Optional[int]:
                try:
                    return headers.index(name)
                except ValueError:
                    return None

            idx = idx_of("current temperature")
            if idx is not None and idx < len(latest_row):
                val = adjusted_temp[-1]
                latest_row[idx] = str(int(val)) if float(val).is_integer() else f"{val:.1f}"

            idx = idx_of("cooling set point")
            if idx is not None and idx < len(latest_row):
                val = setpoint[-1]
                latest_row[idx] = str(int(val)) if float(val).is_integer() else f"{val:.1f}"

            idx = idx_of("fan setting")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = "Auto"

            idx = idx_of("equipment status")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = "Cooling" if int(cooling[-1]) == 1 else "Idle"

            idx = idx_of("outside temp")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = payload["latestOutsideRaw"]

            idx = idx_of("condenser state")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = payload["latestCondenserState"]

            idx = idx_of("condenser minutes")
            if idx is not None and idx < len(latest_row):
                latest_row[idx] = str(int(runtime_this_hour[-1]))

            payload["latestRow"] = latest_row

        _save_json(target_path, payload)

        on_hours = [labels[i] for i, v in enumerate(cooling) if int(v) == 1]
        total_runtime = int(total_runtime_minutes)
        print(f"Target date: {slug}")
        print(f"Dataset: {'created' if created_new else 'overwritten'} ({target_path.name})")
        print("Baseline: generated from fixed hourly anchors (no HVAC).")
        i_6 = _index_for_hour(labels_dt, 6)
        i_13 = _index_for_hour(labels_dt, 13)
        i_18 = _index_for_hour(labels_dt, 18)
        i_0 = _index_for_hour(labels_dt, 0)
        print(
            f"Setpoint: {setpoint[i_6]:.0f}F default; "
            f"{setpoint[i_13]:.0f}F occupied 13:00-17:59; "
            f"{setpoint[i_18]:.0f}F evening 18:00-23:59; "
            f"{setpoint[i_0]:.0f}F overnight 00:00-05:59."
        )
        print(f"DayType: {day_type.name} ({day_type.reason})")
        print(f"Hourly cooling drop applied: {hourly_drop:.0f}F/hour")
        if not on_hours:
            print("Cooling hours: none")
        else:
            print("Cooling hours: " + ", ".join(on_hours))
        print(f"Total projected HVAC runtime minutes: {total_runtime}")
        print("Per-hour runtime values: 0 or 40 only")
        return

    precip: List[float] = []
    if has_hourly_weather_for_window(payload):
        outside = [round(float(v), 1) for v in payload["outside"]]
        outside_flags = [str(v).strip().upper() for v in payload["outsideFlags"]]
        outside_day_chars = [str(v).strip().upper() for v in payload["outsideFlagDayChars"]]
        # Precipitation isn't stored in the JSON schema; use the existing rain flag as a yes/no proxy.
        precip = [1.0 if f == 'R' else 0.0 for f in outside_flags]
    else:
        weather = _fetch_open_meteo_hourly(lat, lon, tz, target_day, next_day)
        outside = []
        outside_flags = []
        outside_day_chars = []
        missing: List[str] = []
        for dt in labels_dt:
            key = dt.strftime("%Y-%m-%dT%H:00")
            entry = weather.get(key)
            if not entry:
                missing.append(key)
                outside.append(0.0)
                outside_flags.append("O")
                outside_day_chars.append("D")
                precip.append(0.0)
                continue
            temp_f = round(float(entry["temp_f"]), 1)
            code = int(entry["code"])
            is_day_flag = int(entry["is_day"])
            p = float(entry.get("precip") or 0.0)
            outside.append(temp_f)
            outside_flags.append(_flag_for(code, is_day_flag))
            outside_day_chars.append(_day_char(is_day_flag))
            precip.append(p)
        if missing:
            raise RuntimeError(f"Missing Open-Meteo hours: {missing}")

    setpoint = _build_setpoint_series(labels_dt)
    # Day-type classification window: 10:00 AM-4:00 PM inclusive => indices 4..10.
    day_type = _classify_day_type(outside_flags, precip, range(4, 11))
    baseline = _build_baseline_series(day_type, labels_dt=labels_dt, peak_hour=peak_hour)
    controlled, cooling, runtime, saturated, diagnostics = _simulate_controlled(baseline, setpoint, day_type)
    _update_dataset_in_place(
        payload,
        labels_dt=labels_dt,
        labels=labels,
        outside=outside,
        outside_flags=outside_flags,
        outside_day_chars=outside_day_chars,
        baseline=baseline,
        controlled=controlled,
        setpoint=setpoint,
        cooling=cooling,
        runtime=runtime,
        day_type=day_type,
    )
    warnings: List[str] = []
    errors: List[str] = []
    for i, dt in enumerate(labels_dt):
        entry = diagnostics[i]
        entry.update(
            {
                "date": dt.date().isoformat(),
                "hour_local": dt.strftime("%H:00"),
                "dt_local": _fmt_dt_hour(dt),
                "day_type": day_type.name,
                "peak_value_f": float(day_type.peak_f),
                "peak_hour": int(peak_hour),
                "outside_temp_f": float(outside[i]),
                "outside_flag": str(outside_flags[i]),
                "precip_yes": bool(precip[i] > 0.0) if i < len(precip) else False,
                "chart_field_written": CHART_INDOOR_SERIES_KEY,
                "value_written_to_chart_field": float(payload[CHART_INDOOR_SERIES_KEY][i]),
            }
        )

        if float(entry["runtime_minutes_applied"]) > 0 and abs(
            float(entry["final_controlled_temp_f"]) - float(entry["baseline_temp_f"])
        ) < 1e-9:
            warning = f"cooling_applied_but_no_temp_change @ {entry['dt_local']}"
            entry["WARNING"] = warning
            warnings.append(warning)

        if abs(float(entry["value_written_to_chart_field"]) - float(entry["final_controlled_temp_f"])) > 1e-9:
            err = (
                f"controlled_temp_not_plotted @ {entry['dt_local']} "
                f"({entry['value_written_to_chart_field']} != {entry['final_controlled_temp_f']})"
            )
            entry["ERROR"] = err
            errors.append(err)

    if log_per_hour:
        print("Per-hour diagnostics (JSONL):")
        for entry in diagnostics:
            print(json.dumps(entry, sort_keys=True))

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"- {e}")
        raise SystemExit(2)

    _save_json(target_path, payload)

    setpoint_summary = (
        f"default {DEFAULT_SETPOINT_F:.0f}F; occupied {OCCUPIED_SETPOINT_F:.0f}F "
        f"{OCCUPIED_START_HOUR:02d}:00-{OCCUPIED_END_HOUR_EXCLUSIVE-1:02d}:59"
    )
    total_runtime = int(sum(runtime))
    first_engaged_idx = next((i for i, m in enumerate(runtime) if float(m) > 0), None)
    print(f"Window: {slug} 06:00 -> {next_day.isoformat()} 05:00 ({tz})")
    print(f"DayType: {day_type.name} peak={day_type.peak_f:.0f}F ({day_type.reason})")
    print(f"peak_hour: {peak_hour:02d}:00")
    print(f"Setpoint: {setpoint_summary}")
    print(f"Total HVAC runtime: {total_runtime} minutes")
    print(f"First hour HVAC engaged: {labels[first_engaged_idx] if first_engaged_idx is not None else 'none'}")
    if saturated:
        hours = ", ".join(labels[i] for i in saturated)
        print(f"Saturated @60 min without reaching SP: {hours}")
    else:
        print("Saturated @60 min without reaching SP: none")
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"- {w}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a thermostat demo JSON for a chosen day.")
    parser.add_argument(
        "day",
        nargs="?",
        help="Target day in YYYY-MM-DD (or MM/DD[/YYYY], MM-DD[-YYYY]) or 'yesterday'. Updates Web/chart hist/<day>.json in place.",
    )
    parser.add_argument(
        "--start",
        help="Start date for batch generation (inclusive). Format: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end",
        help="End date for batch generation (inclusive). Format: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "hourly", "simulate"),
        default=DEFAULT_MODE,
        help="HVAC logic mode: 'local' (single event, 5-min style), 'hourly' (anchor baseline + 1 next-hour drop), or 'simulate' (full baseline+control simulation).",
    )
    parser.add_argument(
        "--peak-hour",
        type=int,
        default=17,
        help="Hour of day (0-23) used for the indoor baseline peak (default: 17 = 5:00 PM).",
    )
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "--log-per-hour",
        dest="log_per_hour",
        action="store_true",
        default=True,
        help="Print per-hour diagnostics in JSONL (default).",
    )
    log_group.add_argument(
        "--no-log-per-hour",
        dest="log_per_hour",
        action="store_false",
        help="Disable per-hour diagnostics output.",
    )
    args = parser.parse_args()

    if (args.start is None) != (args.end is None):
        raise SystemExit("--start and --end must be provided together.")

    if args.start and args.end:
        try:
            start_day = date.fromisoformat(args.start)
            end_day = date.fromisoformat(args.end)
        except ValueError as exc:
            raise SystemExit(f"Invalid --start/--end date (expected YYYY-MM-DD): {exc}") from exc

        if end_day < start_day:
            raise SystemExit("--end must be on or after --start.")

        current = start_day
        while current <= end_day:
            run(
                current.isoformat(),
                peak_hour=args.peak_hour,
                mode=args.mode,
                log_per_hour=args.log_per_hour,
            )
            current += timedelta(days=1)
        return

    if not args.day:
        raise SystemExit("Provide either a DAY argument or --start/--end for batch generation.")

    run(args.day, peak_hour=args.peak_hour, mode=args.mode, log_per_hour=args.log_per_hour)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
