from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import json
import os
import logging
import mimetypes

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


GLOBAL_SHARED_CONFIG = _load_shared_config()
GIT_TEST_FLAG = bool(GLOBAL_SHARED_CONFIG.get("GitTestFlag", True))

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
    "data_range": "A:I",  # columns range within the sheet tab
    "delete_temp_files": False,
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
DELETE_TEMP_FILES = bool(cfg_payload.get("delete_temp_files", _DEFAULTS["delete_temp_files"]))

HISTORY_WINDOW = 20
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


def push_dashboard_to_drive(html_path: Path) -> str:
    service = get_drive_upload_service()
    folder_id = get_or_create_drive_folder(service, DRIVE_FOLDER_NAME)
    mime_type, _enc = mimetypes.guess_type(html_path.name)
    mime_type = mime_type or "text/html"
    content = html_path.read_bytes()
    file_id, target_name = upload_or_version_file(
        service, folder_id, html_path.name, content, mime_type
    )
    logger.info(
        "Drive link: https://drive.google.com/file/d/%s/view (stored as %s)",
        file_id,
        target_name,
    )
    return file_id


def git_autopush(html_path: Path) -> None:
    """Stage, commit, and push the generated dashboard copy."""
    if not GIT_TEST_FLAG:
        logger.info("Skipping git autopush because GitTestFlag is false")
        return
    repo_root = Path(__file__).resolve().parents[2]
    html_rel = html_path.relative_to(repo_root)
    subprocess.run(["git", "add", str(html_rel)], cwd=repo_root, check=True)
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


def build_dashboard_html(
    headers: List[str],
    latest_row: List[str],
    history_rows: List[List[str]],
    output_path: Path,
) -> None:
    def _safe_float(val: str) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            logger.debug("Non-numeric chart value %r; defaulting to 0", val)
            return 0.0

    title = "Lockout Music Studios Oside"
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
    actual_idx = _find_index(("current temperature", "actual temperature", "temperature"))
    if actual_idx is not None and actual_idx == setpoint_idx:
        actual_idx = None
    setpoint_label = (
        headers[setpoint_idx] if setpoint_idx is not None and len(headers) > setpoint_idx else "Cooling Set Point"
    )
    actual_label = (
        headers[actual_idx] if actual_idx is not None and len(headers) > actual_idx else "Actual Temperature"
    )

    fan_idx = _find_index(("fan", "fan setting", "fan mode"))
    FAN_LABELS = ["Auto", "Circulate", "On"]

    def _fan_value(row: List[str]) -> Optional[int]:
        if fan_idx is None or fan_idx >= len(row):
            return None
        val = str(row[fan_idx]).strip().lower()
        if not val:
            return None
        if "auto" in val:
            return 0
        if "circulate" in val or "cir" in val:
            return 1
        if val in ("on", "fan", "low", "high") or "run" in val:
            return 2
        return None

    def _extract_clamped(idx: Optional[int], row: List[str]) -> Optional[float]:
        if idx is None or idx >= len(row):
            return None
        val = _safe_float(row[idx])
        if 50 <= val <= 100:
            return val
        return None

    chart_labels = [row[0] if row else "" for row in history_rows]
    setpoint_series = [_extract_clamped(setpoint_idx, row) for row in history_rows]
    actual_series = [_extract_clamped(actual_idx, row) for row in history_rows]
    fan_series = [_fan_value(row) for row in history_rows]
    chart_data = []
    for label, sp_val, actual_val in zip(chart_labels, setpoint_series, actual_series):
        selected = sp_val if sp_val is not None else actual_val
        if selected is not None:
            chart_data.append({"label": label, "value": selected})
    data_json = json.dumps(
        {
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
        }
    )
    cards = ""
    for label, value in zip(headers, latest_row + [""] * (len(headers) - len(latest_row))):
        cards += f"""
        <div class="metric-card">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
        </div>
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
        margin: 0;
        font-family: 'Inter', system-ui, sans-serif;
        background: #4a4a4a;
        color: #f4f6ff;
      }}
      .container {{
        max-width: 960px;
        margin: 32px auto;
        padding: 24px;
        background: #4a4a4a;
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
        margin-bottom: 16px;
      }}
      .header-label {{
        font-size: 36px;
        text-transform: uppercase;
        letter-spacing: 0.25em;
        opacity: 0.95;
      }}
      .logo-placeholder {{
        width: 190px;
        height: 126px;
       /* border: 1px dashed #66ff99; */
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
      .metric-card {{
        background: #2b2b30;
        color: #f5f7ff;
        border: 1px solid #3a3a40;
        border-radius: 12px;
        padding: 16px;
      }}
      .metric-card .label {{
        font-size: 14px;
        opacity: 0.7;
      }}
      .metric-card .value {{
        font-size: 24px;
        font-weight: 600;
      }}
      .history-panel {{
        margin-top: 32px;
        background: rgba(255,255,255,0.02);
        border-radius: 12px;
        padding: 16px;
        border: 1px solid rgba(255,255,255,0.08);
        position: relative;
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
      button:active {{
        transform: scale(0.98);
      }}
      .chart-controls {{
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 12px;
        font-size: 14px;
        color: #f4f6ff;
      }}
      .chart-control {{
        border: 1px solid #3a3a40;
        background: #1f1f26;
        color: #f4f6ff;
        padding: 6px 12px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.2s ease, color 0.2s ease;
      }}
      .chart-control.active {{
        background: #ffa500;
        color: #051b05;
        border-color: #ffa500;
      }}
      #history-chart {{
        display: none;
        width: 100% !important;
        height: 100% !important;
      }}
      .chart-wrap {{
        height: 420px;
      }}
      .fan-legend {{

        position: absolute;
        top: 16px;
        right: 16px;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 4px;
        font-size: 12px;
        color: #cbd2e0; 
      }}
      .fan-legend-item {{
        cursor: default;
        padding: 2px 6px;
        border-radius: 999px;
        transition: color 0.2s ease, background 0.2s ease;
        color: #ffa500;
      }}
      .fan-legend-item.active {{
        font-weight: 600;
        color: #ffa500;
        background: rgba(255,165,0,0.1);
      }}
      .note {{
        margin-top: 12px;
        font-size: 12px;
        opacity: 0.7;
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header-row">
        <div class="header-label">Lockout Music Studios  Oceanside</div>
        <div class="logo-placeholder">
          <img src="../../../Images/LO_Logo.png" alt="Logo" />
        </div>
      </div>
      <div class="card-grid">
        {cards}
      </div>
      <div class="history-panel">
        <button id="toggle-history">Show History Chart</button>
        <div class="chart-controls">
          <label>Chart view:</label>
          <button class="chart-control" data-mode="setpoint">Target</button>
          <button class="chart-control" data-mode="actual">Actual</button>
          <button class="chart-control" data-mode="fan">Fan</button>
          <button class="chart-control active" data-mode="both">Combined</button>
        </div>
        <div class="chart-wrap">
          <canvas id="history-chart"></canvas>
        </div>
        <div class="fan-legend">
          <span class="fan-legend-item" data-mode="auto">Auto</span>
          <span class="fan-legend-item" data-mode="circulate">Circulate</span>
          <span class="fan-legend-item" data-mode="on">On</span>
        </div>
        <div class="note">Data source: Google Sheet (last updated when this page was generated).</div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
      const dashboardData = {data_json};
      const ctx = document.getElementById("history-chart").getContext("2d");
      const chartControlButtons = document.querySelectorAll(".chart-control");
      const chartLabels = dashboardData.chartLabels || [];
      const setpointSeries = dashboardData.setpoint || [];
      const actualSeries = dashboardData.actual || [];
      const fanSeries = dashboardData.fan || [];
      const fanLegend = dashboardData.fanLegend || ["Auto", "Circulate", "On"];
      const setpointLabel = dashboardData.setpointLabel || "Target Temperature";
      const actualLabel = dashboardData.actualLabel || "Actual Temperature";
      const fanLegendItems = document.querySelectorAll(".fan-legend-item");
      const FAN_STATE_NAMES = ["auto", "circulate", "off"];
      let chart;

      const updateChartVisibility = (mode) => {{
        if (!chart) {{
          return;
        }}
        chart.data.datasets[0].hidden = !(mode === "setpoint" || mode === "both");
        chart.data.datasets[1].hidden = !(mode === "actual" || mode === "both");
        chart.data.datasets[2].hidden = !(mode === "fan" || mode === "both");
        chart.update();
      }};
      const getLatestFanState = () => {{
        if (!fanSeries.length) {{
          return null;
        }}
        const idx = fanSeries[fanSeries.length - 1];
        if (typeof idx !== "number" || Number.isNaN(idx)) {{
          return null;
        }}
        return FAN_STATE_NAMES[idx] || null;
      }};
      const highlightFanLegend = (mode) => {{
        fanLegendItems.forEach((item) => {{
          const isActiveLegend = item.dataset.mode === mode;
          const baseColor = item.dataset.color || "#cbd2e0";
          const activeColor = item.dataset.activeColor || "#ffa500";
          item.classList.toggle("active", isActiveLegend);
          item.style.color = isActiveLegend ? activeColor : baseColor;
        }});
      }};
      const getActiveMode = () => {{
        const activeBtn = document.querySelector(".chart-control.active");
        return (activeBtn && activeBtn.dataset && activeBtn.dataset.mode) || "both";
      }};
      const setActiveMode = (mode) => {{
        chartControlButtons.forEach((btn) => {{
          btn.classList.toggle("active", btn.dataset.mode === mode);
        }});
        updateChartVisibility(mode);
        highlightFanLegend(getLatestFanState());
      }};
      chartControlButtons.forEach((button) => {{
        button.addEventListener("click", () => setActiveMode(button.dataset.mode));
      }});
      highlightFanLegend(getLatestFanState());
      document.getElementById("toggle-history").addEventListener("click", (evt) => {{
        const canvas = document.getElementById("history-chart");
        if (canvas.style.display === "none" || !canvas.style.display) {{
          canvas.style.display = "block";
          if (!chart) {{
            chart = new Chart(ctx, {{
              type: "line",
              data: {{
                labels: chartLabels,
                datasets: [
                  {{
                    label: setpointLabel,
                    data: setpointSeries,
                    borderColor: "#66ff99",
                    backgroundColor: "rgba(102,255,153,0.2)",
                    spanGaps: true,
                  }},
                  {{
                    label: actualLabel,
                    data: actualSeries,
                    borderColor: "#7da4ff",
                    backgroundColor: "rgba(125,164,255,0.2)",
                    spanGaps: true,
                  }},
                  {{
                    label: "Fan Mode",
                    data: fanSeries,
                    borderColor: "#ffa500",
                    backgroundColor: "rgba(255,165,0,0.3)",
                    yAxisID: "fan",
                    spanGaps: true,
                    borderDash: [4, 4],
                    pointRadius: 4,
                  }},
                ],
              }},
              options: {{
                responsive: true,
                maintainAspectRatio: true,
                animation: false,
                scales: {{
                  y: {{
                    beginAtZero: false,
                    min: 55,
                    max: 90,
                    ticks: {{
                      color: "#f4f6ff",
                    }},
                    grid: {{
                      color: "rgba(255,255,255,0.1)",
                    }},
                  }},
                  fan: {{
                    type: "linear",
                    position: "right",
                    min: -0.5,
                    max: 2.5,
                    ticks: {{
                      stepSize: 1,
                      callback: (value) => fanLegend[Math.round(value)] || "",
                      color: "#f4f6ff",
                    }},
                    grid: {{
                      drawOnChartArea: false,
                      color: "rgba(255,255,255,0.08)",
                    }},
                  }},
                  x: {{
                    ticks: {{
                      color: "#f4f6ff",
                      maxRotation: 0,
                      minRotation: 90,
                    }},
                    grid: {{
                      color: "rgba(255,255,255,0.08)",
                    }},
                  }},
                }},
                plugins: {{
                  legend: {{
                    labels: {{
                      color: "#f4f6ff",
                    }},
                  }},
                  tooltip: {{
                    callbacks: {{
                      label: (context) => {{
                        if (context.dataset.yAxisID === "fan") {{
                          const value = context.parsed.y;
                          return `\${{context.dataset.label}}: \${{
                            fanLegend[Math.round(value)] || "Unknown"
                          }}`;
                        }}
                        return `\${{context.dataset.label}}: \${{context.parsed.y ?? context.parsed}}`;
                      }},
                    }},
                  }},
                }},
              }},
            }});
          }}
          setActiveMode(getActiveMode());
        }} else {{
          canvas.style.display = "none";
        }}
      }});
    </script>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    logger.info("Wrote dashboard HTML to %s", output_path)


def main() -> None:
    headers, latest_row, history_rows = fetch_sheet_data()
    if not headers:
        raise SystemExit("Sheet returned no data; set GOOGLE_SHEET_ID and DATA_RANGE.")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target_path = TEMP_DIR / "dashboard.html"
    build_dashboard_html(headers, latest_row, history_rows, target_path)
    # Also save a copy in the project folder for external publishing.
    public_dir = base_dir.parent / "Web"
    public_dir.mkdir(parents=True, exist_ok=True)
    public_copy = public_dir / "dashboard_public.html"
    try:
        # Keep a human-readable copy alongside the bot so it can be served or published separately.
        public_copy.write_bytes(target_path.read_bytes())
        logger.info("Wrote public copy to %s", public_copy)
        # Automatically stage/commit/push the public HTML so repo and remote stay in sync with each generation.
        git_autopush(public_copy)
    except Exception as exc:
        logger.warning("Failed to write or push public copy %s (%s)", public_copy, exc)
    print(f"Dashboard generated at: {target_path.resolve()}")
    logger.info("Dashboard generation complete at %s", target_path.resolve())

    # Push to Drive and clean up local temp copy.
    try:
        file_id = push_dashboard_to_drive(target_path)
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
