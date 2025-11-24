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
    raise SystemExit(
        "Missing Google Sheets dependencies. "
        "Install with: pip install gspread google-auth"
    ) from e


EXTRACTION_PROMPT = """
You are a data extraction assistant.

Task:
Given the full HTML or plain-text body of an email that may contain multiple links, do the following:

1. Scan the email body and extract ONLY URLs that are clearly job-related, such as:
   - Job posting links
   - Job application links
   - Company career pages
   - Job-detail pages

   Ignore non-job links such as:
   - Unsubscribe links
   - Privacy policy / terms links
   - Generic help, support, or FAQ links
   - Tracking pixels or image URLs

2. For each job-related URL you find:
   - Analyze the surrounding text (near the link) to infer:
     - job_name  → the job title, e.g. "Customer Service Representative"
     - company_name → the company or employer, e.g. "Best Buy Health"
   - If you are not sure about a field, set it to null instead of guessing wildly.

3. Output format:
   - Return ONLY valid JSON.
   - Do NOT include any explanations, comments, or extra text.
   - The JSON must have a top-level key "jobs" whose value is a list of job objects.
   - Each job object must have exactly these keys:
       - "job_name"      (string or null)
       - "company_name"  (string or null)
       - "url"           (string, the full job-related URL)
"""


def load_config() -> Dict[str, Any]:
    """Load config.json from the script directory."""
    cfg_path = base_dir / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json not found at {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_openai_client(cfg: Dict[str, Any]) -> OpenAI:
    """Create an OpenAI client using the API key from config.json or environment."""
    api_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key found. "
            "Set 'openai_api_key' in config.json or OPENAI_API_KEY in the environment."
        )
    return OpenAI(api_key=api_key)


def extract_jobs_from_email(body: str, cfg: Dict[str, Any]) -> TypedList[Dict[str, Any]]:
    """Call OpenAI to extract job_name, company_name, and url from the email body."""
    if not body or not body.strip():
        print("[WARN] Empty email body passed to extract_jobs_from_email.")
        return []

    # Debug: log what we're about to send to OpenAI
    body_len = len(body)
    preview = body[:400].replace("\n", "\\n").replace("\r", "\\r")
    print(f"[DEBUG] Email body length: {body_len} characters")
    print(f"[DEBUG] Email body preview (first 400 chars): {preview}")

    if cfg.get("debug_dump_email_body"):
        dump_path = base_dir / "email_body_used.txt"
        try:
            dump_path.write_text(body, encoding="utf-8")
            print(f"[DEBUG] Full email body dumped to {dump_path.name}")
        except Exception as e:
            print(f"[WARN] Failed to dump email body to file: {e!r}")

    client = get_openai_client(cfg)
    model = cfg.get("openai_model", "gpt-4.1-mini")
    temperature = cfg.get("openai_temperature", 0.1)

    print("[INFO] Calling OpenAI for structured job extraction…")

    response = client.responses.create(
        model=model,
        instructions=EXTRACTION_PROMPT.strip(),
        input=body,
        temperature=temperature,
    )

    # Try to get plain text from the Responses API
    raw_text = getattr(response, "output_text", None)

    if not raw_text:
        try:
            pieces = []
            first_output = response.output[0]
            for c in getattr(first_output, "content", []):
                txt_obj = getattr(c, "text", None)
                if txt_obj is None:
                    continue
                val = getattr(txt_obj, "value", None)
                if isinstance(val, str):
                    pieces.append(val)
                elif isinstance(txt_obj, str):
                    pieces.append(txt_obj)
            raw_text = "\n".join(pieces).strip()
        except Exception as e:
            print(f"[ERROR] Could not extract text from OpenAI response: {e!r}")
            return []

    if not raw_text or not str(raw_text).strip():
        print("[ERROR] OpenAI response text empty or whitespace; skipping JSON parse.")
        return []

    if not isinstance(raw_text, str):
        raw_text = str(raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print("[ERROR] Failed to parse JSON from OpenAI response:", e)
        print("Raw text was:")
        print(raw_text)
        return []

    jobs = data.get("jobs", [])
    if not isinstance(jobs, list):
        print("[WARN] 'jobs' key not found or not a list in JSON response.")
        return []

    cleaned: TypedList[Dict[str, Any]] = []
    for idx, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            print(f"[WARN] Skipping non-dict job entry at index {idx}: {job!r}")
            continue

        job_name = job.get("job_name")
        company_name = job.get("company_name")
        url = job.get("url")

        if not url:
            print(f"[WARN] Skipping job with no URL at index {idx}.")
            continue

        cleaned.append(
            {
                "job_name": job_name if isinstance(job_name, str) else None,
                "company_name": company_name if isinstance(company_name, str) else None,
                "url": str(url),
            }
        )

    print(f"[INFO] Extracted {len(cleaned)} job(s) from email body.")
    return cleaned


def get_gsheet_worksheet(cfg: Dict[str, Any]):
    """Authorize with Google Sheets and return the target worksheet."""
    sa_filename = cfg.get("service_account_json", "Glocal.json")
    sa_path = base_dir / sa_filename
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account file not found at: {sa_path}")

    spreadsheet_id = cfg["spreadsheet_id"]
    worksheet_name = cfg["worksheet_name"]

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
    client = gspread.authorize(creds)

    print("[INFO] Connecting to Google Sheets…")
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)
    print(f"[INFO] Connected to worksheet: {worksheet_name}")
    return ws


def append_jobs_to_sheet(jobs: TypedList[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    """Append each job as a new row in the target Google Sheet."""
    if not jobs:
        print("[INFO] No jobs to append to Google Sheet.")
        return

    ws = get_gsheet_worksheet(cfg)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for job in jobs:
        job_name = job.get("job_name") or ""
        company_name = job.get("company_name") or ""
        url = job.get("url") or ""
        rows.append([timestamp, job_name, company_name, url])

    print(f"[INFO] Appending {len(rows)} row(s) to Google Sheet…")
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print("[OK] Rows appended successfully.")


def _decode_mime_words(s: str) -> str:
    """Decode MIME-encoded words in email headers (helper, not strictly needed for body)."""
    decoded_fragments = []
    for frag, enc in decode_header(s):
        if isinstance(frag, bytes):
            try:
                decoded_fragments.append(frag.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                decoded_fragments.append(frag.decode("utf-8", errors="replace"))
        else:
            decoded_fragments.append(frag)
    return "".join(decoded_fragments)


def get_unread_email_body(cfg: Dict[str, Any]) -> str:
    """
    Connect to Gmail via IMAP and return the body of the first unread email
    in the INBOX for the configured account.
    """
    gmail_user = cfg.get("gmail_user") or cfg.get("user")
    gmail_pass = cfg.get("gmail_app_password") or cfg.get("app_password")
    if not gmail_user or not gmail_pass:
        raise RuntimeError("Missing gmail_user or gmail_app_password in config.json")

    only_unseen = cfg.get("gmail_only_unseen", True)
    mark_read = cfg.get("mark_read", True)

    print("[INFO] Connecting to Gmail via IMAP…")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_user, gmail_pass)
    mail.select("INBOX")

    search_criteria = "(UNSEEN)" if only_unseen else "ALL"
    typ, data = mail.search(None, search_criteria)
    if typ != "OK":
        print(f"[WARN] IMAP search failed with status: {typ}")
        mail.logout()
        return ""

    msg_ids = data[0].split()
    if not msg_ids:
        print("[INFO] No matching emails found (likely no unread messages).")
        mail.logout()
        return ""

    # Take the first unread email (oldest unread)
    msg_id = msg_ids[0]
    print(f"[INFO] Fetching email UID: {msg_id.decode('ascii', errors='ignore')}")

    typ, msg_data = mail.fetch(msg_id, "(RFC822)")
    if typ != "OK":
        print(f"[WARN] Failed to fetch email body for {msg_id!r}.")
        mail.logout()
        return ""

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    # Optionally mark as read
    if mark_read:
        try:
            mail.store(msg_id, "+FLAGS", "\\Seen")
            print("[INFO] Marked email as read.")
        except Exception as e:
            print(f"[WARN] Failed to mark email as read: {e!r}")

    mail.logout()

    # Prefer HTML, fall back to plain text
    body_html = None
    body_text = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "").lower()

            if "attachment" in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None

            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")

            if content_type == "text/html" and body_html is None:
                body_html = text
            elif content_type == "text/plain" and body_text is None:
                body_text = text
    else:
        # Not multipart – simple message
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body_text = payload.decode(charset, errors="replace")
            except LookupError:
                body_text = payload.decode("utf-8", errors="replace")

    body = body_html or body_text or ""
    if not body.strip():
        print("[WARN] Retrieved email but body appears to be empty.")
    else:
        print("[INFO] Email body retrieved successfully.")

    return body


def main() -> None:
    """Entry point.

    Normal mode:
      - Load config.json
      - Connect to Gmail and fetch the first unread email body from INBOX
      - Call OpenAI to extract job data
      - Append one row per job to the configured Google Sheet

    Debug mode (optional):
      - If config.json has "debug_use_email_body_file": true
        and ./email_body.txt exists, use the contents of that file
        as the email body instead of calling Gmail.
    """
    cfg = load_config()

    body = ""
    if cfg.get("debug_use_email_body_file"):
        email_body_path = base_dir / "email_body.txt"
        if email_body_path.exists():
            body = email_body_path.read_text(encoding="utf-8")
            print(f"[INFO] Loaded email body from {email_body_path.name} (debug mode).")
        else:
            print("[WARN] debug_use_email_body_file is true but email_body.txt not found.")
    if not body:
        body = get_unread_email_body(cfg)

    if not body or not body.strip():
        print("[INFO] No email body to process. Exiting without calling OpenAI or Sheets.")
        return

    jobs = extract_jobs_from_email(body, cfg)
    append_jobs_to_sheet(jobs, cfg)


if __name__ == "__main__":
    main()
