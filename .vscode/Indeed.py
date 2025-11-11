#!/usr/bin/env python3
"""
Indeed.py — fetch latest Indeed email from Gmail, extract job info with AI,
and append a nicely formatted row to Google Sheets.

Input priority:
  1) --text (explicit body)       2) --file (read from path)
  3) Default: fetch latest Gmail message from donotreply@indeed.com

Requires:
  - config.json (in the same folder as this script) with:
      {
        "service_account_json": "sa_key.json",
        "spreadsheet_id": "YOUR_SHEET_ID_HERE",
        "worksheet_name": "Inbox",
        "openai_model": "gpt-4o-mini",
        "openai_temperature": 0.1,
        "gmail_user": "you@example.com",
        "gmail_app_password": "your-16-char-app-password",
        "gmail_folder": "INBOX",
        "gmail_from_filter": "donotreply@indeed.com"
      }
  - Environment var OPENAI_API_KEY set to a valid API key.
"""

from pathlib import Path
from typing import Iterable, List, Set, Tuple, Dict, Any
import os
import sys
import re
import json
import argparse
from datetime import datetime

# Always operate relative to this script's folder
base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

# ---------------- URL extraction ----------------
URL_RE = re.compile(r"https?://[^\s>')\\]]+", re.IGNORECASE)

def extract_urls(text: str) -> List[str]:
    if not text:
        return []
    return list(dict.fromkeys(URL_RE.findall(text)))  # unique, preserve order

# ---------------- AI analysis ----------------
def ai_analyze_email(body: str, model: str, temperature: float = 0.1) -> Dict[str, Any]:
    """
    Calls OpenAI Chat Completions with a constrained JSON output spec.
    Requires OPENAI_API_KEY in environment.
    Falls back gracefully if anything fails.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY in environment.",
            "data": None,
        }
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        system = (
            "You are a helpful assistant that extracts job posting details from plain email bodies. "
            "Return ONLY JSON with keys: urls(list), title, company, location, summary(list of 1-5 bullets), "
            "seniority(optional), salary(optional), source(optional), confidence(0-1). "
            "If a field is unknown, use null. 'urls' must reflect only actual links present."
        )
        user = f"EMAIL BODY:\\n{body}"
        payload = {
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        # Ensure urls are present; if the model missed them, fill from regex:
        if "urls" not in parsed or not isinstance(parsed.get("urls"), list) or not parsed["urls"]:
            parsed["urls"] = extract_urls(body)
        return {"ok": True, "error": None, "data": parsed}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}

# ---------------- Google Sheets helpers ----------------
def get_gspread_clients(sa_json_path: str):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(sa_json_path, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc, creds

def ensure_headers(ws, headers: List[str]):
    existing = ws.row_values(1)
    if existing and [h.strip() for h in existing] == headers:
        return
    ws.update("A1", [headers])

def append_row(ws, row: List[Any]):
    ws.append_row(row, value_input_option="USER_ENTERED")

def pretty_format_sheet(spreadsheet_id: str, worksheet_title: str, creds):
    from googleapiclient.discovery import build
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    # find sheetId for the target worksheet
    ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    for s in ss["sheets"]:
        if s["properties"]["title"] == worksheet_title:
            sheet_id = s["properties"]["sheetId"]
            break
    if sheet_id is None:
        return

    # Batch requests: bold header, freeze row 1, alternating banding, auto-resize all columns with data.
    requests = [
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(textFormat,horizontalAlignment)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "addBanding": {
                "bandedRange": {
                    "range": {"sheetId": sheet_id},
                    "rowProperties": {
                        "firstBandColor": {"red": 0.95, "green": 0.95, "blue": 0.95},
                        "secondBandColor": {"red": 1, "green": 1, "blue": 1},
                    },
                }
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 20,
                }
            }
        },
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()

# ---------------- Config ----------------
def load_config(cfg_path: str) -> Dict[str, Any]:
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------------- Gmail fetch ----------------
import imaplib, email

def get_latest_indeed_email(user: str, app_password: str, folder: str = "INBOX", from_filter: str = "donotreply@indeed.com") -> str:
    """Connect to Gmail IMAP and return the body of the most recent Indeed email (text/plain preferred, fallback to HTML)."""
    print("[INFO] Connecting to Gmail…")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user, app_password)
    typ, _ = mail.select(folder)
    if typ != "OK":
        print(f"[ERROR] Could not select folder: {folder}")
        try: mail.logout()
        except: pass
        return ""

    # Search by FROM
    typ, data = mail.search(None, f'(FROM "{from_filter}")')
    if typ != "OK":
        print("[ERROR] Gmail search failed.")
        try: mail.logout()
        except: pass
        return ""

    ids = data[0].split()
    if not ids:
        print("[WARN] No matching Indeed emails found.")
        try: mail.logout()
        except: pass
        return ""

    latest_id = ids[-1]
    typ, msg_data = mail.fetch(latest_id, "(RFC822)")
    if typ != "OK":
        print("[ERROR] Failed to fetch email content.")
        try: mail.logout()
        except: pass
        return ""

    msg = email.message_from_bytes(msg_data[0][1])
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    try:
                        body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                    except Exception:
                        body = payload.decode("utf-8", errors="ignore")
                    break
        # Fallback to text/html if no plain part found
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        try:
                            body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                        except Exception:
                            body = payload.decode("utf-8", errors="ignore")
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
            except Exception:
                body = payload.decode("utf-8", errors="ignore")

    try: mail.logout()
    except: pass
    print("[INFO] Retrieved latest Indeed email.")
    return (body or "").strip()

# ---------------- Main ----------------
def main():
    parser = argparse.ArgumentParser(description="AI-enriched email-to-Sheets formatter")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--file", help="Path to a text file containing the email body")
    parser.add_argument("--text", help="Raw email body text")
    args = parser.parse_args()

    # Load config
    try:
        cfg = load_config(args.config)
        print(f"[INFO] Using config: {args.config}")
    except FileNotFoundError:
        print(f"[ERROR] Config not found: {args.config}")
        sys.exit(1)

    sa_json = cfg.get("service_account_json", "sa_key.json")
    sheet_id = cfg["spreadsheet_id"]
    worksheet_name = cfg.get("worksheet_name", "Inbox")
    model = cfg.get("openai_model", "gpt-4o-mini")
    temperature = float(cfg.get("openai_temperature", 0.1))

    gmail_user = cfg.get("gmail_user")
    gmail_app_password = cfg.get("gmail_app_password")
    gmail_folder = cfg.get("gmail_folder", "INBOX")
    gmail_from_filter = cfg.get("gmail_from_filter", "donotreply@indeed.com")

    # Acquire body (args override Gmail)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            body = f.read()
        print(f"[INFO] Loaded body from file: {args.file}")
    elif args.text:
        body = args.text
        print("[INFO] Loaded body from --text")
    else:
        if not (gmail_user and gmail_app_password):
            print("[ERROR] Missing gmail_user/gmail_app_password in config.json, and no --text/--file provided.")
            sys.exit(2)
        body = get_latest_indeed_email(gmail_user, gmail_app_password, folder=gmail_folder, from_filter=gmail_from_filter)

    body = (body or "").strip()
    if not body:
        print("[ERROR] No email body retrieved.")
        sys.exit(2)

    # Extract URLs regardless
    print("[INFO] Extracting URLs…")
    urls = extract_urls(body)
    print(f"[INFO] Found {len(urls)} URL(s)")

    # AI analyze
    print("[INFO] Calling OpenAI for structured parse…")
    ai = ai_analyze_email(body, model=model, temperature=temperature)
    if ai["ok"]:
        data = ai["data"] or {}
    else:
        data = {"urls": urls, "title": None, "company": None, "location": None, "summary": []}

    # Harmonize fields
    title = (data.get("title") or "").strip() or ""
    company = (data.get("company") or "").strip() or ""
    location = (data.get("location") or "").strip() or ""
    summary_list = data.get("summary") or []
    if isinstance(summary_list, str):
        summary_list = [summary_list]
    summary_text = " • ".join([s.strip() for s in summary_list if s and isinstance(s, str)])
    ai_conf = data.get("confidence")
    try:
        ai_conf = float(ai_conf) if ai_conf is not None else None
    except Exception:
        ai_conf = None

    url_list = data.get("urls") or urls
    first_url = url_list[0] if url_list else ""
    all_urls = "; ".join(url_list) if url_list else ""

    # Sheets
    try:
        print("[INFO] Connecting to Google Sheets…")
        gc, creds = get_gspread_clients(sa_json)
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(worksheet_name)
        print("[INFO] Connected to worksheet successfully")
    except Exception as e:
        print(f"[ERROR] Google Sheets open failed: {e}")
        sys.exit(3)

    headers = [
        "Timestamp",
        "Title",
        "Company",
        "Location",
        "First URL",
        "All URLs",
        "AI Summary",
        "AI Confidence",
    ]
    ensure_headers(ws, headers)

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        title,
        company,
        location,
        first_url,
        all_urls,
        summary_text,
        f"{ai_conf:.2f}" if isinstance(ai_conf, float) else "",
    ]

    print("[INFO] Appending row…")
    append_row(ws, row)

    # Pretty formatting (safe to call repeatedly)
    try:
        print("[INFO] Applying pretty formatting…")
        pretty_format_sheet(sheet_id, worksheet_name, creds)
    except Exception as e:
        print(f"[WARN] Formatting skipped: {e}")

    print("[OK] Row appended.")
    if not ai["ok"]:
        print(f"[WARN] AI step failed: {ai['error']}")
    else:
        print("[OK] AI enrichment applied.")

if __name__ == "__main__":
    main()
