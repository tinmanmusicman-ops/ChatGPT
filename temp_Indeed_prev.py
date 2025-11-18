from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os, json, imaplib, email, inspect, re, time
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime
from openai import OpenAI
import time
imaplib.Debug = 1
base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    raise SystemExit("Install gspread + google-auth")

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
   - Infer salary information (exact figure or range if provided; otherwise null)
   - If unsure, return null
   
3. For each job URL, also extract a single field called decision_factors:
   - A short, compact description using only info from the email.
   - Include things like:
     - salary / pay range
     - remote / hybrid / on-site
     - location (city/state or ΓÇ£multiple locationsΓÇ¥)
     - job type (full-time, part-time, contract, etc.)
     - schedule hints (weekends, evenings, flexible)
   - Keep it to 1ΓÇô2 sentences max.
   - If there is not enough info, set decision_factors to null.
   
   

      
   
   Generate a company_summary for the company, based only on information available in the email body. The summary should briefly describe the companyΓÇÖs type (e.g., staffing agency, tech company, healthcare provider) and any clearly stated details (e.g., location, industry, pay range hints, ΓÇ£Easily applyΓÇ¥, etc.).
   What is the physical address for the company that is associated with the URL info
      

   Do NOT invent or guess exact numbers such as employee count, revenue, founding year, or precise history. If those details are not explicitly mentioned in the email, keep the summary high-level and avoid specific statistics.

If there is not enough information to say anything meaningful about the company, set company_summary to null.


3. Output rules:
   - ONLY return a JSON object
   - MUST NOT use markdown or code fences
   - JSON must start with '{' and end with '}'

   


 tructure:
{
  "jobs": [
    {
      "job_name": string|null,
      "company_name": string|null,
      "url": string,
      "company_summary": string|null,
      "salary": string|null,
      "decision_factors": string|null
      "location": string|null
    }
  ]
}

"""

JOB_KEYWORDS = (
    "linkedin",
    "automation",
    "jobalerts",
    "jobalert",
    "job_alert",
    "job alert",
    "job",
    "jobs",
    "view job",
    "view openings",
    "apply now",
    "new job",
)

JOB_DOMAINS = (
    "indeed",
    "linkedin",
)

COLUMN_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]

SHEET_HEADERS = [
    "Timestamp",
    "Elapsed Seconds",
    "Job Link",
    "Company",
    "Location",
    "Salary",
    "Company Summary",
    "Decision Factors",
    "Source Email",
]

_FORWARDED_FROM_PATTERN = re.compile(
    r"^\s*>?\s*From:\s*(?:.*<([^>]+)>|([^ \r\n]+@[^ \r\n]+))",
    re.IGNORECASE | re.MULTILINE,
)


def load_config():
    cfg_path = base_dir / "config.json"
    try:
        raw = cfg_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing config file: {cfg_path}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Malformed JSON in config file: {cfg_path}") from exc

def get_openai_client(cfg):
    print(f"\n[INFO] Calling get_openai_client(cfg)")
 
    api_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing OpenAI API key. Set openai_api_key in config.json or OPENAI_API_KEY env var.")
    return OpenAI(api_key=api_key)

#    print(f"[INFO] Line {inspect.currentframe().f_lineno} AI extraction startedΓÇª")
 
def mark_email_as_read(cfg, uid):
    print(f"\n[INFO] Calling mark_email_as_read for UID {uid}")
    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(cfg["gmail_user"], cfg["gmail_app_password"])
        mail.select("INBOX")

        res_lbl, data_lbl = mail.uid("FETCH", uid, "(X-GM-LABELS)")
        print("[DEBUG] CURRENT LABELS:", res_lbl, data_lbl)

        mail.uid("STORE", uid, "+X-GM-LABELS", "(\\Processed)")
        mail.uid("STORE", uid, "-X-GM-LABELS", "(\\Inbox)")
        print(f"[INFO] Labeled UID {uid} as Processed.")

        print(f"[INFO] Marked UID {uid} as read.")
    except Exception as e:
        print(f"[WARN] Could not mark {uid} read: {e}")
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
 
 #  print(f"[INFO] Calling ")

def extract_original_sender_from_body(body: str) -> str | None:
    print(f"\n[INFO] Calling extract_original_sender_from_body(body: str)")

    """
    Try to detect the original sender in a forwarded email body.

    Looks for lines like:
      From: Name <email@example.com>
      From: email@example.com
    """
    if not body:
        print("[DEBUG] extract_original_sender_from_body: empty body")
        return None

    separator = "-----Original Message-----"
    forwarded_section = body.split(separator, 1)[-1] if separator in body else body

    matches = list(_FORWARDED_FROM_PATTERN.finditer(forwarded_section))
    if not matches:
        print("[DEBUG] extract_original_sender_from_body: no From lines found")
        return None

    for match in reversed(matches):
        email_addr = match.group(1) or match.group(2)
        if email_addr:
            sender = email_addr.strip()
            print(f"[DEBUG] extract_original_sender_from_body: found {sender}")
            return sender
    print("[DEBUG] extract_original_sender_from_body: matches lacked addresses")
    return None

def is_relevant_job_email(body: str) -> bool:
    print("[INFO] Checking whether email appears job-related.")
    if not body:
        return False
    text = body.lower()
    if not any(k in text for k in JOB_KEYWORDS):
        return False
    if not any(d in text for d in JOB_DOMAINS):
        return False
    return True

def extract_jobs_from_email(body, cfg):
    print(f"\n[INFO] Line {inspect.currentframe().f_lineno} AI extraction startedΓÇª")
    ai_start = time.time()
    ai_start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[INFO] AI request sent at {ai_start_timestamp}")

    client = get_openai_client(cfg)
    response = client.responses.create(
        model=cfg.get("openai_model","gpt-4.1-mini"),
        instructions=EXTRACTION_PROMPT.strip(),
        input=body,
        temperature=0.1,
    )

    ai_end = time.time()
    elapsed = ai_end - ai_start
    print(f"[INFO] AI response received at "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] AI processing time: {elapsed:.3f} seconds")
    raw = getattr(response,"output_text",None)
#    breakpoint()
    if not raw:
        try:
            first = response.output[0]
            parts=[]
            for c in getattr(first,"content",[]):
                t=getattr(c,"text",None)
                if t:
                    v=getattr(t,"value",None)
                    if isinstance(v,str):
                        parts.append(v)
            raw="\n".join(parts)
        except:
            print("[ERROR] AI parse fail")
            return []
    raw=str(raw).strip()
    s,e=raw.find("{"),raw.rfind("}")
    if s!=-1 and e!=-1:
        raw=raw[s:e+1]
    try:
        data=json.loads(raw)
    except:
        print("[ERROR] JSON load fail")
        return []
    max_jobs = cfg.get("max_jobs_per_email", 5)
    try:
        max_jobs = int(max_jobs)
    except (TypeError, ValueError):
        max_jobs = 5
    if max_jobs < 1:
        max_jobs = 1

    jobs=[]
    for j in data.get("jobs",[]):
        if isinstance(j,dict) and j.get("url"):
            jobs.append({
                "job_name":j.get("job_name"),
                "company_name":j.get("company_name"),
                "company_summary":j.get("company_summary"),
                "salary": j.get("salary"),
                "location": j.get("location"),
                "decision_factors": j.get("decision_factors"),
                "url":j.get("url")
            })
            if len(jobs) >= max_jobs:
                break
    print(f"[INFO] AI extraction finished. {len(jobs)} job(s).")
#    breakpoint()
    return jobs, elapsed


def get_unread_email_body(cfg):
    print(f"\n[INFO] Line {inspect.currentframe().f_lineno} Calling get_unread_email_body(cfg)")
    
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(cfg["gmail_user"], cfg["gmail_app_password"])
    mail.select("INBOX")
        
    typ, data = mail.uid("SEARCH", None, 'X-GM-RAW', '"category:primary"', 'UNSEEN')
#    typ, data = mail.search(None, 'X-GM-RAW', '"category:primary"', 'UNSEEN')
    if typ != "OK":
        mail.logout()
        return None

    ids = data[0].split()
    if not ids:
        mail.logout()
        return None

    msg_id = ids[0]
    uid = msg_id.decode()

    typ, msg_data = mail.uid("FETCH", uid, "(RFC822)")
    if typ != "OK" or not msg_data:
        mail.logout()
        return None

    raw = msg_data[0][1]
    msg = email.message_from_bytes(raw)

    # Get the header From: address (e.g., Indeed, LinkedIn, etc.)
    from_header = (msg.get("From", "") or "").strip()
    name, addr = parseaddr(from_header)
    header_from_email = (addr or from_header).strip()

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            if part.get_content_type() == "text/html" and not body:
                body = text
            elif part.get_content_type() == "text/plain" and not body:
                body = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", "replace")

    # Prefer the original sender found in a forwarded block, if present
    original_from = extract_original_sender_from_body(body)
    if original_from:
        source_email = original_from.strip()
    else:
        source_email = header_from_email

# This section copies email to Processed and deletes the one in the Primary

    if not is_relevant_job_email(body):
        print("[INFO] Not job-related.")
        mail.uid("STORE", uid, "-FLAGS", "\\Seen")
        mail.uid("COPY", uid, "NotRead")
        mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
        mail.expunge()
        # Logout cleanly before returning to caller
        mail.logout()
        # Return an empty body so the caller continues the loop
        return "", None, source_email

    try:
        mail.uid("COPY", uid, "Processed")
        mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
        mail.expunge()
    except Exception:
        pass
    mail.logout()
    return body, uid, source_email
# end of copy email

_GSHEET_WORKSHEET = None
_GSHEET_EXISTING_URLS = None


def get_gsheet_worksheet(cfg):
    print("[INFO] Obtaining Google Sheet worksheet.")
    global _GSHEET_WORKSHEET
    if _GSHEET_WORKSHEET is not None:
        return _GSHEET_WORKSHEET

    sa = base_dir / cfg.get("service_account_json", "sa_key.json")
    if not sa.exists():
        raise SystemExit(f"Missing Google service account file: {sa}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(sa), scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet_id = cfg.get("spreadsheet_id")
    worksheet_name = cfg.get("worksheet_name")

    if not spreadsheet_id or not worksheet_name:
        raise SystemExit("spreadsheet_id and worksheet_name must be set in config.json")

    try:
        sh = client.open_by_key(spreadsheet_id)
    except gspread.SpreadsheetNotFound as exc:
        raise SystemExit(f"Spreadsheet not found: {spreadsheet_id}") from exc

    try:
        _GSHEET_WORKSHEET = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound as exc:
        raise SystemExit(f"Worksheet not found: {worksheet_name}") from exc

    return _GSHEET_WORKSHEET


def _get_existing_sheet_urls(ws):
    global _GSHEET_EXISTING_URLS
    if _GSHEET_EXISTING_URLS is not None:
        return _GSHEET_EXISTING_URLS

    urls = set()
    def _fetch_column(value_render_option):
        try:
            return ws.col_values(3, value_render_option=value_render_option)
        except Exception as exc:
            print(f"[WARN] Could not read sheet URLs (render={value_render_option}): {exc}")
            return None

    values = _fetch_column("FORMULA")
    if values is None:
        values = _fetch_column("UNFORMATTED_VALUE")
    if values is None:
        _GSHEET_EXISTING_URLS = urls
        return _GSHEET_EXISTING_URLS

    hyperlink_pattern = re.compile(r'^=HYPERLINK\("([^"]+)"', re.IGNORECASE)
    for value in values:
        value = (value or "").strip()
        if not value:
            continue
        match = hyperlink_pattern.match(value)
        if match:
            urls.add(match.group(1))
        elif value.startswith("http"):
            urls.add(value)

    _GSHEET_EXISTING_URLS = urls
    return _GSHEET_EXISTING_URLS


def _ensure_sheet_headers(ws):
    try:
        current = ws.row_values(1)
    except Exception as exc:
        print(f"[WARN] Could not read sheet headers: {exc}")
        return

    normalized = [cell.strip() for cell in current[:len(SHEET_HEADERS)]]
    if normalized == SHEET_HEADERS and len(current) == len(SHEET_HEADERS):
        return

    try:
        ws.update("A1:I1", [SHEET_HEADERS])
        print("[INFO] Sheet headers refreshed.")
    except Exception as exc:
        print(f"[WARN] Failed to update sheet headers: {exc}")

def append_jobs_to_sheet(jobs,cfg,from_email,elapsed):
    print("[INFO] Preparing to append jobs to Google Sheet.")
    if not jobs:
        print("[INFO] No jobs to append.")
        return

    ws = get_gsheet_worksheet(cfg)
    _ensure_sheet_headers(ws)
    existing_urls = _get_existing_sheet_urls(ws)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        current_row_count = len(ws.col_values(1, value_render_option="UNFORMATTED_VALUE"))
    except Exception:
        current_row_count = ws.row_count or 1
    row_base = current_row_count + 1

    def _escape_for_formula(text: str | None) -> str:
        return (text or "").replace('"', '""')

    rows = []
    new_urls = []
    note_rows = []
    for i, job in enumerate(jobs):
        url = job.get("url") or ""
        job_name = job.get("job_name") or "Job Link"
        if url and url in existing_urls:
            print(f"[INFO] Skipping duplicate job URL: {url}")
            continue
        hyperlink = (
            f'=HYPERLINK("{_escape_for_formula(url)}", "{_escape_for_formula(job_name)}")'
            if url
            else job_name
        )

        rows.append(
            [
                ts if i == 0 else "",
                f"{elapsed:.3f}" if i == 0 else "",
                hyperlink,
                job.get("company_name") or "",
                job.get("location") or "",
                job.get("salary") or "",
                job.get("company_summary") or "",
                job.get("decision_factors") or "",
                from_email if i == 0 else "",
            ]
        )
        if url:
            new_urls.append(url)
        note_rows.append(
            [
                ts if i == 0 else "",
                f"{elapsed:.3f}" if i == 0 else "",
                url or job_name,
                job.get("company_name") or "",
                job.get("location") or "",
                job.get("salary") or "",
                job.get("company_summary") or "",
                job.get("decision_factors") or "",
                from_email if i == 0 else "",
            ]
        )
    if not rows:
        print("[INFO] No new rows to append after removing duplicates.")
        return

    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        for url in new_urls:
            existing_urls.add(url)
        print(f"[OK] Appended {len(rows)} row(s).")
        for row_offset, note_values in enumerate(note_rows):
            row_number = row_base + row_offset
            for col_idx, note in enumerate(note_values):
                if not note:
                    continue
                column_letter = COLUMN_LETTERS[col_idx]
                cell = f"{column_letter}{row_number}"
                try:
                    ws.update_note(cell, note)
                except Exception as exc:
                    print(f"[WARN] Failed to set note for {cell}: {exc}")
    except Exception as exc:
        print(f"[WARN] Failed to append rows to sheet: {exc}")


def process_email_payload(body, uid, from_email, cfg, context=""):
    label = f" ({context})" if context else ""
    trimmed_body = body.strip() if body else ""

    if not trimmed_body:
        if from_email:
            print(f"[INFO] Skipping non-job or empty body from {from_email}{label}.")
        else:
            print(f"[INFO] Empty body{label}.")
        return False

    sender = (from_email or "").strip()
    if sender:
        print(f"[INFO] Source email detected{label}: {sender}")

    jobs, elapsed = extract_jobs_from_email(trimmed_body, cfg)
    if not jobs:
        print(f"[INFO] Looked job-related but no jobs extracted{label}.")
        return False

    append_jobs_to_sheet(jobs, cfg, sender, elapsed)

    if uid:
        print(f"[OK] Done{label}.")
    return True




def main():
    print("[INFO] Starting email processing run.")

    cfg = load_config()

    # Debug mode: use a saved email body from file, process once, and exit.
    if cfg.get("debug_use_email_body_file"):
        f = base_dir / "email_body.txt"
        if not f.exists():
            print(f"[WARN] Debug email body file not found: {f}")
            return

        body = f.read_text(encoding="utf-8", errors="ignore")
        from_email = cfg.get("debug_from_email")

        processed = process_email_payload(
            body=body,
            uid=None,
            from_email=from_email,
            cfg=cfg,
            context="debug mode",
        )
        if processed:
            print("[OK] Done (debug mode).")
        return

    # Normal mode: process up to N unseen emails per run.
    max_per_run = cfg.get("max_emails_per_run", 5)
    try:
        max_per_run = int(max_per_run)
    except (TypeError, ValueError):
        max_per_run = 5

    if max_per_run < 1:
        max_per_run = 1

    processed_count = 0
    processed_any = False

    while processed_count < max_per_run:
        try:
            result = get_unread_email_body(cfg)
        except Exception as exc:
            print(f"[WARN] Failed to fetch unread email: {exc}")
            break

        if not result:
            if not processed_any:
                print("[INFO] No email body found.")
            break

        body, uid, from_email = result
        processed = process_email_payload(body, uid, from_email, cfg)
        processed_any = processed_any or processed
        processed_count += 1

    print(f"\n[INFO] Run finished. Processed {processed_count} email(s).")

if __name__=="__main__":
    main()
