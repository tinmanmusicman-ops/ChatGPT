from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

import json
from datetime import datetime
from typing import Dict, Any, List as TypedList
import imaplib
import email
from email.header import decode_header

from openai import OpenAI

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError as e:
    raise SystemExit("Install gspread + google-auth") from e


EXTRACTION_PROMPT = """
You are a data extraction assistant.

Task:
Given the full HTML or plain-text body of an email that may contain multiple links, do the following:

1. Extract only job-related URLs:
   - Job posting links
   - Job application links
   - Company career pages
   - Job-detail pages

Ignore:
- Unsubscribe links
- Privacy policy links
- Tracking URLs
- Image URLs
- Support/FAQ links

2. For each job URL:
   - Infer job_name
   - Infer company_name
   - If unsure, return null

3. Output rules:
   - ONLY return a JSON object
   - MUST NOT use markdown or code fences
   - JSON must start with '{' and end with '}'

Structure:
{
  "jobs": [
    {
      "job_name": string|null,
      "company_name": string|null,
      "url": string
    }
  ]
}
"""


def load_config():
    cfg = base_dir / "config.json"
    return json.loads(cfg.read_text(encoding="utf-8"))


def get_openai_client(cfg):
    api_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def extract_jobs_from_email(body: str, cfg: Dict[str, Any]):
    if not body.strip():
        return []

    print(f"[DEBUG] Email length: {len(body)}")

    client = get_openai_client(cfg)
    response = client.responses.create(
        model=cfg.get("openai_model", "gpt-4.1-mini"),
        instructions=EXTRACTION_PROMPT.strip(),
        input=body,
        temperature=0.1,
    )

    raw = getattr(response, "output_text", None)

    if not raw:
        try:
            pieces = []
            first = response.output[0]
            for c in getattr(first, "content", []):
                t = getattr(c, "text", None)
                if t:
                    val = getattr(t, "value", None)
                    if isinstance(val, str):
                        pieces.append(val)
            raw = "\n".join(pieces)
        except:
            print("[ERROR] Could not extract text from API")
            return []

    raw = str(raw).strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    # Trim to JSON braces
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e != -1:
        raw = raw[s:e+1]

    try:
        data = json.loads(raw)
    except Exception as exc:
        print("[ERROR] JSON parse failed", exc)
        print("RAW:", raw)
        return []

    jobs = data.get("jobs", [])
    out = []
    for j in jobs:
        if isinstance(j, dict) and j.get("url"):
            out.append({
                "job_name": j.get("job_name"),
                "company_name": j.get("company_name"),
                "url": j.get("url")
            })

    print(f"[INFO] Extracted {len(out)} job(s)")
    return out


def get_gsheet_worksheet(cfg):
    sa = base_dir / cfg.get("service_account_json", "Glocal.json")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(sa), scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(cfg["spreadsheet_id"])
    return sh.worksheet(cfg["worksheet_name"])


def append_jobs_to_sheet(jobs, cfg):
    if not jobs:
        print("[INFO] No jobs to append.")
        return

    ws = get_gsheet_worksheet(cfg)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [[timestamp, j["job_name"] or "", j["company_name"] or "", j["url"]] for j in jobs]

    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"[OK] Appended {len(rows)} rows")


def get_unread_email_body(cfg):
    user = cfg["gmail_user"]
    pw = cfg["gmail_app_password"]

    print("[INFO] Connecting to Gmail (Primary + Unseen)…")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user, pw)

    # Search for UNSEEN emails in PRIMARY category only
    search_query = 'X-GM-RAW "category:primary" UNSEEN'

    mail.select("INBOX")
    typ, data = mail.search(None, *search_query.split())

    if typ != "OK":
        print("[WARN] Gmail search failed.")
        mail.logout()
        return ""

    ids = data[0].split()
    if not ids:
        print("[INFO] No unread emails in PRIMARY.")
        mail.logout()
        return ""

    msg_id = ids[0]
    print(f"[INFO] Fetching UID {msg_id.decode()}")

    typ, msg_data = mail.fetch(msg_id, "(RFC822)")
    if typ != "OK":
        print("[WARN] Fetch failed.")
        mail.logout()
        return ""

    # Mark as read
    mail.store(msg_id, "+FLAGS", "\\Seen")
    mail.logout()

    raw = msg_data[0][1]
    msg = email.message_from_bytes(raw)

    # Prefer HTML
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, "replace")
                if ctype == "text/html":
                    return text
                if ctype == "text/plain":
                    body_plain = text
        return body_plain if 'body_plain' in locals() else ""
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, "replace")

    return ""


def main():
    cfg = load_config()

    body = ""
    if cfg.get("debug_use_email_body_file"):
        f = base_dir / "email_body.txt"
        if f.exists():
            print("[INFO] Using local email_body.txt")
            body = f.read_text(encoding="utf-8")

    if not body:
        body = get_unread_email_body(cfg)

    if not body.strip():
        print("[INFO] No email body found.")
        return

    jobs = extract_jobs_from_email(body, cfg)
    append_jobs_to_sheet(jobs, cfg)


if __name__ == "__main__":
    main()
