from __future__ import annotations

import email
import imaplib
import json
import os
import re
import sys
import webbrowser
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import html
import tkinter as tk
from tkinter import ttk
import urllib.request
from urllib.error import HTTPError, URLError

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


def _locate_config_path() -> Path:
    """Prefer a nearby bot-assets/config.json; fallback to the script folder."""
    parent = BASE_DIR.parent

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
            return candidate

    # Fall back to any bot* directory that contains config.json
    for candidate_dir in parent.iterdir():
        if not candidate_dir.is_dir():
            continue
        candidate_name = candidate_dir.name.lower()
        if candidate_name.startswith("bot") and (candidate_dir / "config.json").exists():
            return candidate_dir / "config.json"

    return BASE_DIR / "config.json"


CONFIG_PATH = _locate_config_path()

COMPANY_INFO_PROMPT = """
You are an AI Business Analyst.

Input:
- Email body text of a job-alert email.
- For each job-related URL contained in the email, extract the job details and determine the referenced company.
- For each company referenced in the email, produce an in-depth SWOT assessment (Strengths, Weaknesses, Opportunities, Threats) using only information from the email body and clear context around the job URL (no outside research).


Instructions:
1. Identify every distinct job URL in the email. Treat each as a unique job entry.
2. For each job entry:
   - Determine company_name from the surrounding text or the page/URL hints in the email.
   - Develop a company_info field containing a SWOT mini-brief. Each component must be labeled (e.g., "Strengths: ...; Weaknesses: ...") and highlight concrete details from the email: company overview, capabilities, differentiators, pain points, market positioning, hiring cues, or risks affecting customers/employees. When a component lacks evidence, explicitly note "Strengths: null" (etc.) rather than inventing information.
   - Capture the job URL itself in url.

3. Return a JSON object of the form:
{
  "jobs": [
    {
      "company_name": string|null,
      "url": string,
      "company_info": string|null
    }
  ]
}

Rules:
- Only use information present in the email content for company_info; do not fabricate or infer from outside knowledge.
- company_info must concisely cover Strengths, Weaknesses, Opportunities, and Threats (up to ~100 words) with each label spelled out. If every SWOT dimension is empty, set company_info to null.
- Always include each field (company_name, url, company_info) for every job object, even if company_info is null.
- Output only valid JSON (no markdown, code fences, or commentary).
""".strip()


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

If you know a trustworthy public logo URL for the company, add a line such as `Logo: https://example.com/logo.png` somewhere near the top of your response. Otherwise leave that detail out.

Emphasize approximate figures when you are unsure, avoid unsupported claims, and keep each section concise but informative.
""".strip()


def prompt_for_company_name() -> Optional[str]:
    """Ask for a manual company name before checking email."""
    result: dict[str, Optional[str]] = {"value": None}

    root = tk.Tk()
    root.title("Manual Company Analysis")
    root.resizable(False, False)
    width, height = 420, 140
    root.geometry(f"{width}x{height}")
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = int((screen_width - width) / 2)
    y = int((screen_height - height) / 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.attributes("-topmost", True)

    def close(value: Optional[str] = None) -> None:
        result["value"] = value
        root.destroy()

    def on_analyze() -> None:
        name = entry.get().strip()
        close(name if name else None)

    frame = ttk.Frame(root, padding="12")
    frame.pack(fill="both", expand=True)

    label = ttk.Label(frame, text="Enter company name (leave blank to fetch email):")
    label.pack(anchor="w")

    entry = ttk.Entry(frame)
    entry.pack(fill="x", pady=(6, 12))
    entry.focus()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    analyze_btn = ttk.Button(buttons, text="Analyze", command=on_analyze)
    analyze_btn.pack(side="right", padx=(4, 0))

    cancel_btn = ttk.Button(buttons, text="Cancel", command=lambda: close(None))
    cancel_btn.pack(side="right")

    root.protocol("WM_DELETE_WINDOW", lambda: close(None))
    root.mainloop()
    return result["value"]


def load_config() -> Dict[str, object]:
    """Load email + API configuration."""
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
    return OpenAI(api_key=api_key)


def _extract_body(msg: email.message.Message) -> str:
    """Return HTML body if present, otherwise plain text."""
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
            content_type = part.get_content_type()
            if content_type == "text/html" and not html_body:
                html_body = decoded
            elif content_type == "text/plain" and not text_body:
                text_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text_body = payload.decode(msg.get_content_charset() or "utf-8", "replace")

    return (html_body or text_body or "").strip()


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

    client = get_openai_client(cfg)
    model = cfg.get("openai_model") or "gpt-4o-mini"
    temperature = cfg.get("openai_temperature")
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 0.1

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
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"jobs": [], "raw": raw, "error": "JSON decode failed"}


def analyze_company_manually(company_name: str, cfg: Dict[str, object]) -> str:
    """Ask OpenAI for a deep summary when a company name is provided manually."""
    client = get_openai_client(cfg)
    model = cfg.get("openai_model") or "gpt-5.1"
    temperature = cfg.get("openai_temperature")
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 0.35

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


def save_analysis_markdown(formatted_text: str, company_name: str) -> Path:
    """Salvage the AI analysis into a polished Markdown report."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", company_name.strip())
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"information_analysis_{safe_name}_{timestamp_file}.md"
    path = BASE_DIR / filename

    normalized_content = formatted_text.strip()
    path.write_text(f"{normalized_content}\n", encoding="utf-8")
    return path


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


LOGO_REGEX = re.compile(r"logo:\s*\[.*?\]\((https?://[^\s)]+)\)", re.IGNORECASE)


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


def convert_markdown_to_html(markdown_text: str, company_name: str) -> Path:
    """Convert the Markdown report to styled HTML for viewing."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", company_name.strip())
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"information_analysis_{safe_name}_{timestamp_file}.html"
    path = BASE_DIR / filename

    markdown_text = convert_markdown_bold(markdown_text)
    lines = markdown_text.splitlines()
    title_line = ""
    subtitle_line = ""
    metadata_line = ""
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

    logo_url = ""
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped:
            idx += 1
            continue
        logo_match = LOGO_REGEX.match(stripped)
        if logo_match:
            logo_url = logo_match.group(1)
            idx += 1
            continue
        if stripped.startswith("## "):
            break
        idx += 1

    sections: List[dict[str, List[str] | str]] = []
    current_section: Optional[dict[str, List[str] | str]] = None

    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue

        if line.startswith("## "):
            if current_section:
                sections.append(current_section)
            section_title = line[3:].strip()
            current_section = {
                "title": section_title,
                "items": [],
            }
        elif line.startswith("- ") and current_section:
            current_section["items"].append(line[2:].strip())
        elif current_section:
            current_section["items"].append(line)

        idx += 1

    if current_section:
        sections.append(current_section)

    def build_section_html(section: dict[str, List[str] | str]) -> str:
        title = section["title"]
        items = section["items"]
        highlight_class = " highlight" if title == "Evaluation Highlights" else ""
        if items:
            list_html = "<ul>\n" + "\n".join(f"        <li>{item}</li>" for item in items) + "\n      </ul>\n"
        else:
            list_html = ""

        return f"""      <div class="section{highlight_class}">
        <h2>{html.escape(title)}</h2>
{list_html}      </div>"""
    body_sections = "\n".join(build_section_html(section) for section in sections)
    body_sections = emphasize_key_labels(body_sections)

    logo_html = ""
    logo_url = resolve_logo_url(logo_url, company_name)
    if logo_url:
        escaped_logo = html.escape(logo_url, quote=True)
        alt_text = html.escape(f"{company_name} logo")
        logo_html = f'<div class="logo-block"><img src="{escaped_logo}" alt="{alt_text}" loading="lazy" /></div>'

    html_template = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Company Intelligence Report – {html.escape(company_name)}</title>
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

      h1 {{
        font-size: 34px;
        color: var(--accent-primary);
        letter-spacing: 0.05em;
        margin: 0 0 4px 0;
      }}

      h2 {{
        font-size: 24px;
        color: var(--accent-secondary);
        margin-top: 18px;
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
        padding: 5px 14px;
        border-radius: 18px;
        border: 1px solid rgba(122, 232, 255, 0.35);
        background: linear-gradient(135deg, rgba(102, 255, 153, 0.18), rgba(122, 232, 255, 0.18));
        font-size: 0.82em;
        letter-spacing: 0.08em;
        color: #e8fff5;
        margin-bottom: 8px;
        margin-right: 8px;
        text-transform: uppercase;
        box-shadow: 0 0 10px rgba(122, 232, 255, 0.25);
      }}

      .header-row {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 24px;
      }}

      .header-text {{
        flex: 1;
      }}

      .logo-block img {{
        width: 96px;
        height: 96px;
        object-fit: contain;
        border-radius: 12px;
        border: 1px solid var(--border-soft);
        background: rgba(255, 255, 255, 0.08);
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
          <h1>{html.escape(title_line or 'Company Intelligence Report')}</h1>
          <h2>{html.escape(subtitle_line or company_name)}</h2>
          <p>{html.escape(metadata_line)}</p>
        </div>
        {logo_html}
      </div>
{body_sections}
      <footer>Generated via EI Markdown → HTML pipeline.</footer>
    </div>
  </body>
</html>
"""
    return save_html_report(html_template, company_name)


def save_html_report(html_content: str, company_name: str) -> Path:
    """Persist the generated HTML to disk."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", company_name.strip())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"information_analysis_{safe_name}_{timestamp}.html"
    out_path = base_dir / filename
    out_path.write_text(html_content, encoding="utf-8")
    return out_path


def fetch_unseen_primary(cfg: Dict[str, object]) -> Optional[Dict[str, str]]:
    """Grab the first unseen message in the Primary inbox."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    first_uid_bytes: Optional[bytes] = None
    revert_unseen = False
    try:
        mail.login(cfg["gmail_user"], cfg["gmail_app_password"])
        status, _ = mail.select("INBOX")
        if status != "OK":
            raise RuntimeError("Unable to select INBOX")

        search_args = _search_args(cfg, include_sender=True)
        status, data = mail.uid("SEARCH", None, *search_args)
        if status != "OK" or not data or not data[0]:
            print("[INFO] No unseen message matched sender filters; retrying without them.")
            search_args = _search_args(cfg, include_sender=False)
            status, data = mail.uid("SEARCH", None, *search_args)
            if status != "OK" or not data or not data[0]:
                return None

        first_uid_bytes = data[0].split()[0]
        status, msg_data = mail.uid("FETCH", first_uid_bytes, "(RFC822)")
        if status != "OK" or not msg_data:
            return None

        msg = email.message_from_bytes(msg_data[0][1])
        body_text = _extract_body(msg)

        if cfg.get("mark_read", True):
            mail.uid("STORE", first_uid_bytes, "+FLAGS", "(\\Seen)")
            revert_unseen = True

        return {
            "uid": first_uid_bytes.decode(),
            "subject": _decode_mime_header(msg.get("Subject")),
            "from": _decode_mime_header(msg.get("From")),
            "body": body_text,
        }
    finally:
        if revert_unseen and first_uid_bytes is not None:
            try:
                mail.uid("STORE", first_uid_bytes, "-FLAGS", "(\\Seen)")
            except Exception:
                pass
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    cfg = load_config()

    manual_name = prompt_for_company_name()
    if manual_name:
        try:
            manual_output = analyze_company_manually(manual_name, cfg)
        except Exception as exc:  # pylint: disable=broad-except
            print("Unable to run manual analysis.")
            print(f"Details: {exc}")
        else:
            print(f"\n--- Manual Company Analysis: {manual_name} ---")
            normalized_output = normalize_analysis_markdown(manual_output, manual_name)
            print(normalized_output)
            try:
                md_path = save_analysis_markdown(normalized_output, manual_name)
                print(f"\nStructured Markdown report saved at {md_path}")
            except Exception as exc:
                print("Failed to save Markdown report.")
                print(f"Details: {exc}")
            else:
                try:
                    html_path = convert_markdown_to_html(normalized_output, manual_name)
                    webbrowser.open_new_tab(html_path.as_uri())
                    print(f"HTML preview opened at {html_path}")
                except Exception as exc:
                    print("Failed to render HTML preview.")
                    print(f"Details: {exc}")
        sys.exit(0)

    email_payload = fetch_unseen_primary(cfg)
    body = ""

    if email_payload is None:
        print("No unseen email found in Primary.")
    else:
        body = email_payload["body"]
        print(f"Subject: {email_payload['subject']}")
        print(f"From: {email_payload['from']}")
        print("\n--- Email Body (first 400 chars) ---")
        print(body[:400])
        print("\n--- End ---")
        company_info = extract_company_info(body, cfg)
        print("\n--- AI Company Info ---")
        print(json.dumps(company_info, indent=2))
