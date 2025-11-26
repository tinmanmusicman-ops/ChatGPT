from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
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
TOKEN_PATH = AI_BOTS_ROOT / "shared" / "tokens.json"
CREDENTIALS_PATH = AI_BOTS_ROOT / "shared" / "credentials.json"

GOOGLE_SHEET_ID = "TODO_SHEET_ID"
DATA_RANGE = "Sheet1!A1:E"
HISTORY_WINDOW = 20
CHART_METRIC_INDEX = 1  # 0-based index inside headers

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)


def _load_credentials() -> Credentials:
    creds: Optional[Credentials] = None
    client_config = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except ValueError:
            client_config = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_config:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(f"Missing credentials at {CREDENTIALS_PATH}")
                client_config = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_sheets_service():
    creds = _load_credentials()
    return build("sheets", "v4", credentials=creds)


def fetch_sheet_data() -> Tuple[List[str], List[str], List[List[str]]]:
    """Return headers, latest row, and history rows."""
    service = get_sheets_service()
    data = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=GOOGLE_SHEET_ID, range=DATA_RANGE)
        .execute()
    )
    values = data.get("values", [])
    if not values:
        return [], [], []
    headers = values[0]
    rows = values[1:]
    latest_row = rows[-1] if rows else []
    history_rows = rows[-HISTORY_WINDOW:] if rows else []
    return headers, latest_row, history_rows


def build_dashboard_html(
    headers: List[str],
    latest_row: List[str],
    history_rows: List[List[str]],
    output_path: Path,
) -> None:
    title = "Company Metrics Dashboard"
    metric_header = headers[CHART_METRIC_INDEX] if len(headers) > CHART_METRIC_INDEX else "Metric"
    chart_data = [
        {
            "label": row[0] if row else "",
            "value": float(row[CHART_METRIC_INDEX]) if len(row) > CHART_METRIC_INDEX else 0,
        }
        for row in history_rows
    ]
    data_json = json.dumps(
        {"headers": headers, "latestRow": latest_row, "history": chart_data}
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
        background: #05050f;
        color: #f4f6ff;
      }}
      .container {{
        max-width: 960px;
        margin: 32px auto;
        padding: 24px;
      }}
      h1 {{
        margin: 0 0 16px;
        font-size: 32px;
      }}
      .card-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 16px;
      }}
      .metric-card {{
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.1);
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
      #history-chart {{
        display: none;
        margin-top: 24px;
        width: 100%;
        height: 320px;
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
      <h1>{title}</h1>
      <div class="card-grid">
        {cards}
      </div>
      <div class="history-panel">
        <button id="toggle-history">Show History Chart</button>
        <canvas id="history-chart"></canvas>
        <div class="note">Data source: Google Sheet (last updated when this page was generated).</div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
      const dashboardData = {data_json};
      const ctx = document.getElementById("history-chart").getContext("2d");
      const parsed = dashboardData.history;
      let chart;
      document.getElementById("toggle-history").addEventListener("click", (evt) => {{
        const canvas = document.getElementById("history-chart");
        if (canvas.style.display === "none" || !canvas.style.display) {{
          canvas.style.display = "block";
          if (!chart) {{
            chart = new Chart(ctx, {{
              type: "line",
              data: {{
                labels: parsed.map(entry => entry.label || ""),
                datasets: [{{
                  label: "{metric_header}",
                  data: parsed.map(entry => entry.value || 0),
                  borderColor: "#66ff99",
                  backgroundColor: "rgba(102,255,153,0.2)",
                }}],
              }},
              options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                  y: {{
                    beginAtZero: true,
                    ticks: {{
                      color: "#f4f6ff",
                    }},
                    grid: {{
                      color: "rgba(255,255,255,0.1)",
                    }},
                  }},
                  x: {{
                    ticks: {{
                      color: "#f4f6ff",
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
                }},
              }},
            }});
          }}
        }} else {{
          canvas.style.display = "none";
        }}
      }});
    </script>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main() -> None:
    headers, latest_row, history_rows = fetch_sheet_data()
    if not headers:
        raise SystemExit("Sheet returned no data; set GOOGLE_SHEET_ID and DATA_RANGE.")
    target_path = base_dir / "dashboard.html"
    build_dashboard_html(headers, latest_row, history_rows, target_path)
    print(f"Dashboard generated at: {target_path.resolve()}")


if __name__ == "__main__":
    main()
