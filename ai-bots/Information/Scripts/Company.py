from __future__ import annotations

import json
import io
import logging
import os
import re
import shutil
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import html
import tkinter as tk
from tkinter import messagebox, ttk
import urllib.request
from urllib.error import HTTPError, URLError
from socket import timeout as SocketTimeout
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from openai import OpenAI

SECTION_TITLES = [
    "Company Overview",
    "Business Model & Core Offerings",
    "Market Position & Competitive Landscape",
    "Revenue & Scale (Approximate)",
    "Customer Perception & Brand Reputation",
    "Employee Sentiment & Culture",
    "Recent Notable Events",
    "Key Risks & Challenges",
    "Growth Opportunities & Strategic Insights",
    "Evaluation Highlights",
]

# 
def emphasize_key_labels(text: str) -> str:
    """Replace markdown label phrases with styled chips."""
    replacements = {
        "**Core Offerings:**": '<span class="label-chip">Core Offerings</span>',
        "**Business Model:**": '<span class="label-chip">Business Model</span>',
        "**Market Position:**": '<span class="label-chip">Market Position</span>',
        "**Competitive Landscape:**": '<span class="label-chip">Competitive Landscape</span>',
        "**Customer Perception:**": '<span class="label-chip">Customer Perception</span>',
        "**Brand Reputation:**": '<span class="label-chip">Brand Reputation</span>',
        "**Employee Sentiment:**": '<span class="label-chip">Employee Sentiment</span>',
        "**Culture:**": '<span class="label-chip">Culture</span>',
        "**Acquisitions:**": '<span class="label-chip">Acquisitions</span>',
        "**Product Launches:**": '<span class="label-chip">Product Launches</span>',
        "**Partnerships:**": '<span class="label-chip">Partnerships</span>',
        "**Key Risks & Challenges:**": '<span class="label-chip">Key Risks & Challenges</span>',
        "**Growth Opportunities & Strategic Insights:**": '<span class="label-chip">Growth & Insights</span>',
    }

    for raw, chip in replacements.items():
        text = text.replace(raw, chip)

    return text
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
base_dir = BASE_DIR
sys.path.append(str(base_dir.parent.parent))
from shared.ui_settings import load_ui_settings, get_theme_palette

C_USE_ROOT_FOLDER = os.getenv("USE_ROOT_DRIVE_FOLDER", "0") in ("1", "True", "true")
COMPANY_RESEARCH_DIR = Path.home() / "Google Drive" / "Company Research"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_SERVICE: Optional[object] = None
DRIVE_FOLDER_ID: Optional[str] = None
TOKEN_CLIENT_SECRETS = base_dir.parent.parent / "shared" / "tokens.json"
TOKENS_PATH = base_dir.parent.parent / "shared" / "oauth_tokens.json"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _locate_config_path() -> Path:
    """Prefer a nearby bot-assets/config.json; fallback to the script folder."""
    parent = BASE_DIR.parent

    logger.info("Scanning for bot configuration files near %s", parent)

    # Try known folder names first
    preferred_names = [
        "bot-Assets",
        "bot-assets",
        "bot-Assetts",
        "bot-Assessets",
        "bot-Assessments",
    ]
    for name in preferred_names:
        candidate = parent / name / "config.json"
        if candidate.exists():
            logger.info("Found config in preferred folder %s", candidate)
            return candidate

    # Fall back to any bot* directory that contains config.json
    for candidate_dir in parent.iterdir():
        if not candidate_dir.is_dir():
            continue
        candidate_name = candidate_dir.name.lower()
        if candidate_name.startswith("bot") and (candidate_dir / "config.json").exists():
            logger.info("Found config in bot directory %s", candidate_dir / "config.json")
            return candidate_dir / "config.json"

    fallback = BASE_DIR / "config.json"
    logger.info("Using fallback config path %s", fallback)
    return fallback


CONFIG_PATH = _locate_config_path()

MANUAL_ANALYSIS_PROMPT = """
You are an experienced market researcher. Provide a deep analysis of {company} formatted as structured Markdown.
Return the response as a professional company intelligence report that is easy to read, clearly spaced, and uses headings, subheadings, and bullet points.
Include the following sections, each introduced with a Markdown heading (##):
- Company Overview
- Business Model & Core Offerings
- Market Position & Competitive Landscape
- Revenue & Scale (Approximate)
- Customer Perception & Brand Reputation
- Employee Sentiment & Culture
- Recent Notable Events
- Key Risks & Challenges
- Growth Opportunities & Strategic Insights
- Evaluation Highlights (use bullet points for this final recap)

Emphasize approximate figures when you are unsure, avoid unsupported claims, and keep each section concise but informative.
""".strip()


def prompt_for_company_name() -> Optional[str]:
    """Ask for a manual company name before checking email."""
    result: dict[str, Optional[str]] = {"value": None}

    settings = load_ui_settings()
    theme = get_theme_palette(settings)
    font_size = int(settings.default_font_size * settings.font_scale)
    control_pad = 18 if settings.force_large_controls else 10

    root = tk.Tk()
    root.title("Manual Company Analysis")
    root.overrideredirect(True)
    width, height = 380, 220
    root.geometry(f"{width}x{height}")
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.attributes("-topmost", True)
    root.configure(bg=theme["bg"])

    style = ttk.Style(root)
    style.configure("Custom.TFrame", background=theme["bg"])
    style.configure("Border.TFrame", background=theme["bg"], relief="ridge", borderwidth=2)
    style.configure("Custom.TLabel", background=theme["bg"], foreground=theme["fg"], font=("Segoe UI", font_size + 2, "bold"))
    style.configure(
        "Custom.TEntry",
        fieldbackground=theme["entry_bg"],
        background=theme["entry_bg"],
        foreground=theme["fg"],
        font=("Segoe UI", font_size),
    )
    style.configure("Custom.TButton", background=theme["button_bg"], foreground=theme["fg"], font=("Segoe UI", font_size))

    header = ttk.Frame(root, style="Custom.TFrame")
    header.pack(fill="x", padx=0, pady=(0, 4))
    title = ttk.Label(header, text="Manual Company Analysis", style="Custom.TLabel", font=("Segoe UI", 11, "bold"))
    title.pack(side="left", padx=12, pady=6)

    def start_drag(event):
        root._drag_x = event.x
        root._drag_y = event.y

    def do_drag(event):
        root.geometry(f"+{root.winfo_x() + event.x - root._drag_x}+{root.winfo_y() + event.y - root._drag_y}")

    header.bind("<ButtonPress-1>", start_drag)
    header.bind("<B1-Motion>", do_drag)

    def close(value: Optional[str] = None) -> None:
        result["value"] = value
        root.destroy()

    def on_analyze() -> None:
        name = entry.get().strip()
        close(name if name else None)

    frame = ttk.Frame(root, padding=control_pad, style="Border.TFrame")
    frame.pack(fill="both", expand=True)

    label = ttk.Label(frame, text="Enter company name", style="Custom.TLabel")
    label.pack(anchor="w")

    entry = ttk.Entry(
        frame,
        style="Custom.TEntry",
    )
    entry.pack(fill="x", pady=(control_pad, control_pad))
    entry.focus()
    entry.bind("<Return>", lambda event: on_analyze())

    buttons = ttk.Frame(frame, style="Custom.TFrame")
    buttons.pack(fill="x", pady=(control_pad, 0))

    cancel_btn = ttk.Button(
        buttons,
        text="Cancel",
        command=lambda: close(None),
        style="Custom.TButton",
    )
    cancel_btn.pack(anchor="e", padx=control_pad, pady=(0, control_pad))

    def center_window() -> None:
        root.update_idletasks()
        w = root.winfo_width()
        h = root.winfo_height()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"+{(sw - w)//2}+{(sh - h)//2}")

    center_window()
    root.protocol("WM_DELETE_WINDOW", lambda: close(None))
    root.mainloop()
    return result["value"]


def load_config() -> Dict[str, object]:
    """Load email + API configuration."""
    logger.info("Loading configuration from %s", CONFIG_PATH)
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing config file: {CONFIG_PATH}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {CONFIG_PATH}: {exc}") from exc


def _decode_mime_header(value: Optional[str]) -> str:
    """Decode MIME headers (Subject, From)."""
    if not value:
        return ""
    parts: List[str] = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(charset or "utf-8", "replace"))
            except Exception:
                parts.append(text.decode("utf-8", "replace"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def get_openai_client(cfg: Dict[str, object]) -> OpenAI:
    """Construct an OpenAI client from config/environment."""
    api_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing OpenAI API key. Set openai_api_key in config.json or OPENAI_API_KEY env var.")
    logger.info("Constructing OpenAI client")
    return OpenAI(api_key=api_key)




def _search_args(cfg: Dict[str, object], include_sender: bool = True) -> List[str]:
    """Build IMAP SEARCH filters for primary unseen mail."""
    args: List[str] = []
    raw_terms: List[str] = ["category:primary"]

    subject_term = (cfg.get("subject_term") or "").strip()
    if subject_term:
        raw_terms.append(f'subject:"{subject_term}"')

    if raw_terms:
        args.extend(["X-GM-RAW", f"\"{' '.join(raw_terms)}\""])

    sender = None
    if include_sender:
        sender = cfg.get("gmail_from_filter") or next(
            (s for s in cfg.get("gmail_from_filters", []) if s), None
        )
        if sender:
            args.extend(["FROM", f"\"{sender}\""])

    args.append("UNSEEN")
    return args


def extract_company_info(body: str, cfg: Dict[str, object]) -> Dict[str, object]:
    """Send the email body to OpenAI to extract company info per job."""
    if not body:
        return {"jobs": []}

    logger.info("Extracting company info from email body (~%d chars)", len(body))
    client = get_openai_client(cfg)
    model = cfg.get("openai_model") or "gpt-4o-mini"
    temperature = cfg.get("openai_temperature")
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 0.1

    logger.info("Sending company inference request to OpenAI using model %s", model)
    response = client.responses.create(
        model=model,
        instructions=COMPANY_INFO_PROMPT,
        input=body,
        temperature=temperature,
    )


    raw = getattr(response, "output_text", None)
    if not raw:
        try:
            first = response.output[0]
            parts: List[str] = []
            for content in getattr(first, "content", []):
                text_part = getattr(content, "text", None)
                if text_part:
                    value = getattr(text_part, "value", None)
                    if isinstance(value, str):
                        parts.append(value)
            raw = "\n".join(parts)
        except Exception:
            return {"jobs": [], "error": "Unable to parse AI response"}

    raw = str(raw).strip()
    logger.info("Received raw AI output (%d chars)", len(raw))
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"jobs": [], "raw": raw, "error": "JSON decode failed"}


def analyze_company_manually(company_name: str, cfg: Dict[str, object]) -> str:
    """Ask OpenAI for a deep summary when a company name is provided manually."""
    logger.info("Requesting manual company analysis for %s", company_name)
    client = get_openai_client(cfg)
    model = cfg.get("openai_model") or "gpt-5.1"
    temperature = cfg.get("openai_temperature")
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 0.35

    logger.info("Calling ChatCompletions API with model %s", model)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a concise research analyst."},
            {"role": "user", "content": MANUAL_ANALYSIS_PROMPT.format(company=company_name)},
        ],
        temperature=temperature,
        max_tokens=1200,
    )

    choices = getattr(response, "choices", [])
    if not choices:
        raise ValueError("OpenAI returned no analysis.")

    content = getattr(choices[0].message, "content", "")
    if not content:
        raise ValueError("OpenAI returned an empty manual analysis.")

    return content.strip()


def normalize_analysis_markdown(raw_text: str, company_name: str, helper_name: str = "Information") -> str:
    """Convert raw EI text into canonical Markdown with headings."""
    lines = [line.rstrip() for line in raw_text.splitlines()]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    header_lines = [
        "# Company Intelligence Report",
        f"## {company_name}",
        f"_Generated via EI helper: {helper_name} · {now}_",
        "",
    ]

    normalized: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            normalized.append("")
            i += 1
            continue

        title_match: Optional[str] = None
        for title in SECTION_TITLES:
            if line == title or line == title.rstrip(":"):
                title_match = title.rstrip(":")
                break

        if title_match is not None:
            if normalized and normalized[-1] != "":
                normalized.append("")
            normalized.append(f"## {title_match}")
            normalized.append("")
            i += 1
            continue

        normalized.append(line)
        i += 1

    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()

    return "\n".join(header_lines + normalized) + "\n"


def convert_markdown_bold(text: str) -> str:
    """
    Converts **text** into proper HTML bold tags and removes raw **.
    """
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def extract_canonical_company_name(analysis_text: str, fallback: str) -> str:
    """
    Try to extract the 'real' company name from the EI analysis text.
    We look for a heading or phrase that includes 'Company Intelligence Report'
    and grab the name in front of it.

    If nothing is found, we return the fallback (the original user input).
    """
    m = re.search(r"^#\s+(.+?)\s+Company Intelligence Report", analysis_text, re.MULTILINE)
    if m:
        return m.group(1).strip()

    m = re.search(r"^(.+?)\s+Company Intelligence Report", analysis_text, re.MULTILINE)
    if m:
        return m.group(1).strip()

    m = re.search(r"Company:\s*(.+)", analysis_text)
    if m:
        return m.group(1).strip()

    return fallback.strip()


def resolve_logo_url(raw_url: str, company_name: str) -> str:
    """Return an accessible logo URL, trying Clearbit affordances when needed."""
    def accessible(url: str) -> bool:
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, method=method)
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status < 400:
                        return True
            except (HTTPError, URLError, ValueError):
                continue
        return False

    if raw_url and accessible(raw_url):
        return raw_url

    slug = re.sub(r"[^A-Za-z0-9]", "", company_name).lower()
    tlds = ["com", "org", "net", "io", "tech"]
    for tld in tlds:
        candidate = f"https://logo.clearbit.com/{slug}.{tld}"
        if accessible(candidate):
            return candidate

    return raw_url


def ensure_drive_credentials() -> Credentials:
    creds = None
    if TOKENS_PATH.exists():
        creds = Credentials.from_authorized_user_file(TOKENS_PATH, DRIVE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired OAuth token")
            creds.refresh(Request())
        else:
            if not TOKEN_CLIENT_SECRETS.exists():
                raise FileNotFoundError(f"Missing OAuth client secrets at {TOKEN_CLIENT_SECRETS}")
            logger.info("Launching OAuth consent flow for Drive access")
            flow = InstalledAppFlow.from_client_secrets_file(str(TOKEN_CLIENT_SECRETS), DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        TOKENS_PATH.write_text(creds.to_json(), encoding="utf-8")
        logger.info("Persisted OAuth credentials to %s", TOKENS_PATH)
    return creds


def get_drive_service():
    global DRIVE_SERVICE
    if DRIVE_SERVICE:
        logger.info("Reusing cached Google Drive service")
        return DRIVE_SERVICE
    logger.info("Initializing Google Drive service via OAuth identity")
    creds = ensure_drive_credentials()
    DRIVE_SERVICE = build("drive", "v3", credentials=creds)
    return DRIVE_SERVICE


def ensure_drive_folder(service):
    global DRIVE_FOLDER_ID
    if C_USE_ROOT_FOLDER:
        logger.info("Configured to use Drive root folder directly")
        return "root"
    if DRIVE_FOLDER_ID:
        logger.info("Using cached Drive folder ID %s", DRIVE_FOLDER_ID)
        return DRIVE_FOLDER_ID
    query = f"name='{COMPANY_RESEARCH_DIR.name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    logger.info("Searching for Drive folder with query %s", query)
    resp = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    files = resp.get("files", [])
    if files:
        logger.info("Found existing Drive folder %s", files[0]["id"])
        DRIVE_FOLDER_ID = files[0]["id"]
        return DRIVE_FOLDER_ID
    metadata = {"name": COMPANY_RESEARCH_DIR.name, "mimeType": "application/vnd.google-apps.folder"}
    logger.info("Creating Drive folder %s", COMPANY_RESEARCH_DIR.name)
    folder = service.files().create(body=metadata, fields="id").execute()
    DRIVE_FOLDER_ID = folder["id"]
    return DRIVE_FOLDER_ID


def sanitize_company_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text.strip())


def parse_normalized_analysis(normalized_text: str) -> Tuple[str, str, str, str, List[dict[str, List[str] | str]]]:
    lines = normalized_text.splitlines()
    title_line = ""
    subtitle_line = ""
    metadata_line = ""
    logo_url = ""
    idx = 0
    if idx < len(lines) and lines[idx].startswith("# "):
        title_line = lines[idx][2:].strip()
        idx += 1
    if idx < len(lines) and lines[idx].startswith("## "):
        subtitle_line = lines[idx][3:].strip()
        idx += 1
    if idx < len(lines) and lines[idx].startswith("_") and lines[idx].endswith("_"):
        metadata_line = lines[idx].strip("_")
        idx += 1
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("## "):
            break
        idx += 1
    sections: List[dict[str, List[str] | str]] = []
    current_section = None
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue
        if line.startswith("## "):
            if current_section:
                sections.append(current_section)
            current_section = {"title": line[3:].strip(), "items": []}
        elif current_section:
            current_section["items"].append(line)
        idx += 1
    if current_section:
        sections.append(current_section)
    return title_line, subtitle_line, metadata_line, logo_url, sections


def build_html_from_sections(title: str, subtitle: str, metadata: str, logo_html: str, sections: List[dict[str, List[str] | str]]) -> str:
    body = []
    for section in sections:
        title_text = section["title"]
        highlight = " highlight" if title_text == "Evaluation Highlights" else ""
        items = section["items"]
        if items:
            list_html = "<ul>\n" + "\n".join(f"        <li>{item}</li>" for item in items) + "\n      </ul>\n"
        else:
            list_html = ""
        body.append(f"""      <div class="section{highlight}">
        <h2>{html.escape(title_text)}</h2>
{list_html}      </div>""")
    body_content = "\n".join(body)
    body_content = emphasize_key_labels(body_content)
    html_template = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Company Intelligence Report – {html.escape(subtitle or title)}</title>
    <style>
      :root {{
        --bg-main: #02040c;
        --bg-card: #0d1428;
        --accent-primary: #66ff99;
        --accent-secondary: #7ae8ff;
        --text-main: #f0f3ff;
        --text-muted: #a9b0d6;
        --border-soft: rgba(255, 255, 255, 0.08);
        --shadow-deep: 0 25px 80px rgba(0, 0, 0, 0.85);
        --radius-xl: 26px;
        --radius-md: 18px;
      }}
      body {{
        margin: 0;
        padding: 0;
        font-family: "Segoe UI", system-ui, sans-serif;
        background: radial-gradient(circle at top, #182045, #02040c 65%);
        color: var(--text-main);
        font-size: 21px;
        line-height: 1.85;
      }}
      .container {{
        max-width: 980px;
        margin: 40px auto;
        padding: 30px 30px 28px;
        background: linear-gradient(145deg, var(--bg-card), #080c1a);
        border-radius: var(--radius-xl);
        box-shadow: var(--shadow-deep);
        border: 1px solid var(--border-soft);
      }}
      .header-row {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 24px;
      }}
      .header-text {{
        flex: 1;
      }}
      h1 {{
        font-size: 34px;
        color: var(--accent-primary);
        letter-spacing: 0.05em;
        margin: 0 0 4px 0;
      }}
      h2 {{
        font-size: 24px;
        color: var(--accent-secondary);
        margin-top: 6px;
      }}
      .logo-block img {{
        width: 96px;
        height: 96px;
        object-fit: contain;
        border-radius: 12px;
        border: 1px solid var(--border-soft);
        background: rgba(255, 255, 255, 0.08);
      }}
      .section {{
        margin-top: 26px;
        padding: 22px 24px;
        border-radius: var(--radius-md);
        background: radial-gradient(circle at top left, rgba(102,255,153,0.12), transparent 55%);
        border: 1px solid var(--border-soft);
      }}
      .section.highlight {{
        background: linear-gradient(135deg, rgba(102,255,153,0.2), rgba(10,18,10,0.95));
        border-left: 4px solid var(--accent-primary);
      }}
      ul {{
        margin: 14px 0 0 22px;
      }}
      li {{
        margin-bottom: 7px;
      }}
      li::marker {{
        color: var(--accent-secondary);
      }}
      strong {{
        color: #ffd27f;
        font-weight: 700;
      }}
      .label-chip {{
        display: inline-flex;
        align-items: center;
        padding: 4px 12px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.4);
        background: rgba(102, 255, 153, 0.14);
        font-size: 0.85em;
        letter-spacing: 0.05em;
        color: var(--accent-primary);
        margin-bottom: 6px;
        margin-right: 8px;
        text-transform: uppercase;
      }}
      footer {{
        margin-top: 38px;
        padding-top: 18px;
        font-size: 14px;
        color: var(--text-muted);
        border-top: 1px solid var(--border-soft);
        text-align: right;
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header-row">
        <div class="header-text">
          <h1>{html.escape(title or 'Company Intelligence Report')}</h1>
          <h2>{html.escape(subtitle)}</h2>
          <p>{html.escape(metadata)}</p>
        </div>
        {logo_html}
      </div>
{body_content}
      <footer>Generated via EI Markdown → HTML pipeline.</footer>
    </div>
  </body>
</html>
"""
    return html_template


def wait_for_preview_confirmation():
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "Preview ready",
        "The report preview opened in your browser.\n"
        "Close the tab or window when you’re done, then click OK to continue.",
    )
    root.destroy()


def upload_html_to_drive(html_content: str, file_name: str, company_tag: str) -> Tuple[str, str]:
    """Upload the generated HTML into Company Research via Drive API."""
    service = get_drive_service()
    folder_id = ensure_drive_folder(service)
    media = MediaIoBaseUpload(io.BytesIO(html_content.encode("utf-8")), mimetype="text/html")
    metadata = {"name": file_name, "parents": [folder_id]}
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        logger.info("Uploading %s to Drive (attempt %d/%d)", file_name, attempt, max_attempts)
        try:
            created = (
                service.files()
                .create(body=metadata, media_body=media, fields="id")
                .execute()
            )
            logger.info("Upload succeeded, file ID %s", created["id"])
            return created["id"], folder_id
        except (HttpError, SocketTimeout, TimeoutError) as exc:
            if attempt == max_attempts:
                logger.error("Upload failed after %d attempts: %s", attempt, exc)
                raise
            time.sleep(1.0 + attempt * 0.5)
    return created["id"], folder_id


def move_html_report_local(html_path: Path, company_tag: str) -> Path:
    COMPANY_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Moving HTML report %s into local Company Research folder", html_path.name)
    for old_html in COMPANY_RESEARCH_DIR.glob("information_analysis_*.html"):
        if company_tag in old_html.name:
            old_html.unlink()
    target = COMPANY_RESEARCH_DIR / html_path.name
    if target.exists():
        target.unlink()
    shutil.move(str(html_path), str(target))
    return target


def clean_scripts_reports(html_path: Path) -> None:
    """Remove the per-run HTML report file from the Scripts folder."""
    logger.info("Cleaning temporary HTML report %s", html_path)
    attempts = 3
    while attempts > 0:
        try:
            if html_path.exists():
                html_path.unlink()
            break
        except PermissionError:
            attempts -= 1
            time.sleep(0.3)
        except Exception:
            break


def render_html_report(normalized_text: str, company_name: str) -> Tuple[str, str]:
    """Generate the HTML string for the structured analysis."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", company_name.strip())
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"information_analysis_{safe_name}_{timestamp_file}.html"
    logger.info("Rendering HTML report %s for %s", filename, company_name)
    strong_text = convert_markdown_bold(normalized_text)
    title_line, subtitle_line, metadata_line, logo_url, sections = parse_normalized_analysis(strong_text)
    logo_html = ""
    logo_url = resolve_logo_url(logo_url, subtitle_line or company_name)
    if logo_url:
        escaped_logo = html.escape(logo_url, quote=True)
        alt_text = html.escape(f"{subtitle_line or company_name} logo")
        logo_html = f'<div class="logo-block"><img src="{escaped_logo}" alt="{alt_text}" loading="lazy" /></div>'
    html_content = build_html_from_sections(title_line, subtitle_line or company_name, metadata_line, logo_html, sections)
    return filename, html_content


def persist_html_to_disk(html_content: str, file_name: str) -> Path:
    """Persist the HTML to disk when a local fallback is needed."""
    html_path = BASE_DIR / file_name
    html_path.write_text(html_content, encoding="utf-8")
    return html_path

def save_html_report(html_content: str, company_name: str) -> Path:
    """Persist the generated HTML to disk."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", company_name.strip())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"information_analysis_{safe_name}_{timestamp}.html"
    out_path = base_dir / filename
    logger.info("Saving generated HTML content to %s", out_path)
    out_path.write_text(html_content, encoding="utf-8")
    logger.info("HTML content persisted to %s", out_path)
    return out_path



if __name__ == "__main__":
    cfg = load_config()
    logger.info("CompanyV2 entry point reached")

    manual_name = prompt_for_company_name()
    if manual_name:
        logger.info("Manual company name provided: %s", manual_name)
        try:
            manual_output = analyze_company_manually(manual_name, cfg)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Manual analysis failed: %s", exc)
            print("Unable to run manual analysis.")
            print(f"Details: {exc}")
        else:
            print(f"\n--- Manual Company Analysis: {manual_name} ---")
            canonical_name = extract_canonical_company_name(manual_output, manual_name)
            logger.info("Canonical company name resolved to %s", canonical_name)
            safe_name = sanitize_company_name(canonical_name)
            normalized_output = normalize_analysis_markdown(manual_output, canonical_name)
            print(normalized_output)
            try:
                html_filename, html_content = render_html_report(normalized_output, canonical_name)
                preview_path = persist_html_to_disk(html_content, html_filename)
                preview_url = preview_path.as_uri()
                webbrowser.open_new_tab(preview_url)
                logger.info("Preview opened in browser at %s", preview_url)
                print(f"HTML preview opened at {preview_url}")
                wait_for_preview_confirmation()
                drive_id = None
                try:
                    drive_id, _ = upload_html_to_drive(html_content, html_filename, safe_name)
                    drive_url = f"https://drive.google.com/file/d/{drive_id}/view"
                    logger.info("Preview uploaded to Drive as %s", drive_url)
                    print(f"HTML uploaded to Drive at {drive_url}")
                except (HttpError, URLError, HTTPError, SocketTimeout, TimeoutError):
                    logger.warning("Drive upload failed; falling back to local folder.")
                    moved_html = move_html_report_local(preview_path, safe_name)
                    display_url = moved_html.as_uri()
                    logger.info("Preview moved locally to %s", display_url)
                    webbrowser.open_new_tab(display_url)
                    print(f"HTML moved locally to {display_url}")
                finally:
                    clean_scripts_reports(preview_path)
            except Exception as exc:
                print("Failed to render HTML preview.")
                print(f"Details: {exc}")
        sys.exit(0)
    body = ""

