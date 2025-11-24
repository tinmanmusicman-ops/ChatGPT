from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os, json, imaplib, email, inspect, re, time, logging
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
    from googleapiclient.discovery import build
except ImportError:
    raise SystemExit("Install gspread + google-auth")

EXTRACTION_PROMPT = """
You are a data extraction assistant.

Task:
Given the email subject and the full HTML or plain-text body of an email that may contain multiple links, do the following:

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
   - Infer whether the role is remote, hybrid, or on-site (call this field work_arrangement). If unclear, return null.
   - Infer salary information (exact figure or range if provided; otherwise null)
   - Infer the location. Prefer explicit location info in the email body; if the body lacks it, extract just the City and State from the subject line.
   - If unsure, return null
   - Build a field named SWOT that contains a detailed SWOT + automation analysis for the company. For each label (Strengths, Weaknesses, Opportunities, Threats), provide 1�2 sentences filled with concrete facts from the email: capabilities, differentiators, product lines, customer/region focus, hiring or automation cues, metrics/ranges, competitive or regulatory risks. If a section still lacks evidence after scanning the job description, company summary, and subject line, explicitly state "Strengths: null" (etc.) rather than inventing information.

3. For each job URL, also extract a single field called decision_factors:
   - A short, compact description using only info from the email.
   - Include things like:
     - salary / pay range
     - remote / hybrid / on-site
     - location (city/state or “multiple locations”)
     - job type (full-time, part-time, contract, etc.)
     - schedule hints (weekends, evenings, flexible)
   - Keep it to 1–2 sentences max.
   - If there is not enough info, set decision_factors to null.
   
   

      
   
   Generate a company_summary for the company, based only on information available in the email body. The summary should briefly describe the company’s type (e.g., staffing agency, tech company, healthcare provider) and any clearly stated details (e.g., location, industry, pay range hints, “Easily apply”, etc.).
   What is the physical address for the company that is associated with the URL info
      

   Do NOT invent or guess exact numbers such as employee count, revenue, founding year, or precise history. If those details are not explicitly mentioned in the email, keep the summary high-level and avoid specific statistics.

If there is not enough information to say anything meaningful about the company, set company_summary to null.


3. Output rules:
   - ONLY return a JSON object
   - MUST NOT use markdown or code fences
   - JSON must start with '{' and end with '}'
   - The SWOT field must include the full SWOT analysis with at least three distinct factual points across the Strengths/Weaknesses/Opportunities/Threats segments whenever information is available; set SWOT to null only when absolutely no company detail exists in the email.

   


 tructure:
{
  "jobs": [
    {
      "job_name": string|null,
      "company_name": string|null,
      "url": string,
      "company_summary": string|null,
      "work_arrangement": string|null,
      "salary": string|null,
      "decision_factors": string|null,
      "SWOT": string|null,
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

COLUMN_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]

SHEET_HEADERS = [
    "Timestamp",
    "Elapsed Seconds",
    "Job Link",
    "Company",
    "Location",
    "Work Arrangement",
    "Salary",
    "Company Summary",
    "Decision Factors",
    "Source Email",
    "SWOT",
]

_FORWARDED_FROM_PATTERN = re.compile(
    r"^\s*>?\s*From:\s*(?:.*<([^>]+)>|([^ \r\n]+@[^ \r\n]+))",
    re.IGNORECASE | re.MULTILINE,
)
_CITY_STATE_PATTERN = re.compile(r"([A-Za-z][A-Za-z .'-]+,\s?[A-Z]{2})(?=[^A-Za-z]|$)")


def _decode_mime_header(value: str | None) -> str:
    """Decode MIME-encoded headers (like Subject) into a readable string."""
    if not value:
        return ""
    parts = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(charset or "utf-8", "replace"))
            except Exception:
                parts.append(text.decode("utf-8", "replace"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def _extract_city_state_from_subject(subject: str) -> str:
    """Extract the last 'City, ST' pattern from a subject line, if present."""
    if not subject:
        return ""
    match = None
    for match in _CITY_STATE_PATTERN.finditer(subject):
        pass
    return match.group(1).strip() if match else ""


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

#    print(f"[INFO] Line {inspect.currentframe().f_lineno} AI extraction started…")
 
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

def extract_jobs_from_email(body, cfg, subject=""):
    print(f"\n[INFO] Line {inspect.currentframe().f_lineno} AI extraction started…")
    ai_start = time.time()
    ai_start_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[INFO] AI request sent at {ai_start_timestamp}")

    client = get_openai_client(cfg)
    formatted_subject = (subject or "").strip()
    if formatted_subject:
        model_input = f"Email Subject:\n{formatted_subject}\n\nEmail Body:\n{body}"
    else:
        model_input = body
    response = client.responses.create(
        model=cfg.get("openai_model","gpt-4.1-mini"),
        instructions=EXTRACTION_PROMPT.strip(),
        input=model_input,
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
                "work_arrangement": j.get("work_arrangement"),
                "salary": j.get("salary"),
                "location": j.get("location"),
                "decision_factors": j.get("decision_factors"),
                "SWOT": j.get("SWOT"),
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
    subject = _decode_mime_header(msg.get("Subject", ""))

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
        return "", None, source_email, subject

    try:
        mail.uid("COPY", uid, "Processed")
        mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
        mail.expunge()
    except Exception:
        pass
    mail.logout()
    return body, uid, source_email, subject
# end of copy email

_GSHEET_WORKSHEET = None
_GSHEET_EXISTING_URLS = None
_DRIVE_SERVICE = None
_CLEARED_THIS_RUN = False


def get_gsheet_worksheet(cfg):
    print("[INFO] Obtaining Google Sheet worksheet.")
    global _GSHEET_WORKSHEET
    if _GSHEET_WORKSHEET is not None:
        return _GSHEET_WORKSHEET

    sa = base_dir / cfg.get("service_account_json", "Glocal.json")
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


def _clear_data_rows_and_comments(ws, cfg, start_row: int = 2):
    """Remove all data rows (and associated comments) starting at start_row."""
    last_col = COLUMN_LETTERS[len(SHEET_HEADERS) - 1]
    clear_range = f"A{start_row}:{last_col}"
    try:
        ws.batch_clear([clear_range])
        print(f"[INFO] Cleared worksheet range {clear_range}.")
    except Exception as exc:
        print(f"[WARN] Failed to clear worksheet values: {exc}")

    drive = _get_drive_service(cfg)
    file_id = ws.spreadsheet.id
    removed = 0
    page_token = None
    target_col = COLUMN_LETTERS.index("K")

    while True:
        resp = drive.comments().list(
            fileId=file_id,
            pageToken=page_token,
            fields="nextPageToken, comments(id, anchor)"
        ).execute()
        for comment in resp.get("comments", []):
            anchor_blob = comment.get("anchor")
            if not anchor_blob:
                continue
            try:
                anchor_data = json.loads(anchor_blob).get("rangedCommentAnchor")
            except (json.JSONDecodeError, AttributeError):
                continue
            if not anchor_data:
                continue
            start_row_idx = anchor_data.get("startRowIndex")
            start_col_idx = anchor_data.get("startColumnIndex")
            if start_row_idx is None or start_col_idx is None:
                continue
            if start_col_idx != target_col:
                continue
            if start_row_idx + 1 < start_row:
                continue
            try:
                drive.comments().delete(fileId=file_id, commentId=comment["id"]).execute()
                removed += 1
            except Exception as exc:
                print(f"[WARN] Failed to delete Drive comment {comment.get('id')}: {exc}")
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    if removed:
        print(f"[INFO] Removed {removed} Drive comment(s) from column K.")


def _get_drive_service(cfg):
    """Create (or reuse) Drive API client for sheet comments."""
    global _DRIVE_SERVICE
    if _DRIVE_SERVICE is not None:
        return _DRIVE_SERVICE

    sa = base_dir / cfg.get("service_account_json", "Glocal.json")
    if not sa.exists():
        raise SystemExit(f"Missing Google service account file: {sa}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(sa), scopes=scopes)
    _DRIVE_SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _DRIVE_SERVICE


def _create_ttt_comment(ws, cfg, row_number, col_idx, note_text):
    """Attach a Drive comment to the TTT cell for better readability."""
    drive = _get_drive_service(cfg)
    try:
        sheet_id = int(ws.id)
    except (TypeError, ValueError):
        sheet_id = ws.id
    anchor = json.dumps({
        "rangedCommentAnchor": {
            "sheetId": sheet_id,
            "startRowIndex": row_number - 1,
            "endRowIndex": row_number,
            "startColumnIndex": col_idx,
            "endColumnIndex": col_idx + 1,
        }
    })
    body = {
        "content": note_text,
        "anchor": anchor,
    }
    result = drive.comments().create(
        fileId=ws.spreadsheet.id,
        body=body,
        fields="id",
    ).execute()
    print(f"[DEBUG] Created Drive comment {result.get('id')} for row {row_number} col {col_idx+1}")


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
        ws.update(range_name="A1:K1", values=[SHEET_HEADERS])
        print("[INFO] Sheet headers refreshed.")
    except Exception as exc:
        print(f"[WARN] Failed to update sheet headers: {exc}")

def _ensure_wrap_clip(ws):
    '''Ensure sheet columns retain CLIP wrapping.'''
    try:
        ws.format('A:J', {'wrapStrategy': 'CLIP'})
    except Exception as exc:
        print(f"[WARN] Failed to enforce wrap strategy: {exc}")


def append_jobs_to_sheet(jobs,cfg,from_email,elapsed):
    print("[INFO] Preparing to append jobs to Google Sheet.")
    if not jobs:
        print("[INFO] No jobs to append.")
        return

    ws = get_gsheet_worksheet(cfg)
    _ensure_sheet_headers(ws)
    _ensure_wrap_clip(ws)
    existing_urls = _get_existing_sheet_urls(ws)
    now = datetime.now()
    ts_cell = now.strftime("%Y-%m-%d %H:%M:%S")
    ts_note = now.strftime("%A, %B %d, %I:%M %p")
    try:
        current_row_count = len(ws.get_all_values())
    except Exception:
        current_row_count = ws.row_count or 1
    row_base = current_row_count + 1

    def _escape_for_formula(text: str | None) -> str:
        return (text or "").replace('"', '""')

    def _cell_value(value):
        """Convert nested structures into a plain string for Google Sheets."""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return str(value)
    heading_pattern = re.compile(
        r"(Strengths\s*[:\-]|Weaknesses\s*[:\-]|Opportunities\s*[:\-]|Threats\s*[:\-])",
        re.IGNORECASE,
    )

    def _format_swot_text(text) -> str:
        value = text
        if isinstance(value, (dict, list)):
            try:
                value = json.dumps(value, ensure_ascii=False)
            except Exception:
                value = str(value)
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        parts = heading_pattern.split(cleaned)
        if len(parts) <= 1:
            return cleaned
        sections = []
        lead = parts[0].strip()
        if lead:
            sections.append(lead)
        for heading, body in zip(parts[1::2], parts[2::2]):
            entry = f"{heading.strip()} {body.strip()}".strip()
            if entry:
                sections.append(entry)
        return "\n\n".join(sections)

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
        swot_value = _format_swot_text(job.get("SWOT"))

        row_values = [
            ts_cell if i == 0 else "",
            f"{elapsed:.3f}" if i == 0 else "",
            hyperlink,
            _cell_value(job.get("company_name")),
            _cell_value(job.get("location")),
            _cell_value(job.get("work_arrangement")),
            _cell_value(job.get("salary")),
            _cell_value(job.get("company_summary")),
            _cell_value(job.get("decision_factors")),
            _cell_value(from_email if i == 0 else ""),
            _cell_value(swot_value),
        ]
        rows.append(row_values)
        if url:
            new_urls.append(url)
        note_rows.append(
            [
                ts_note if i == 0 else "",
                f"{elapsed:.3f}" if i == 0 else "",
                _cell_value(url or job_name),
                _cell_value(job.get("company_name")),
                _cell_value(job.get("location")),
                _cell_value(job.get("work_arrangement")),
                _cell_value(job.get("salary")),
                _cell_value(job.get("company_summary")),
                _cell_value(job.get("decision_factors")),
                _cell_value(from_email if i == 0 else ""),
                _cell_value(swot_value),
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
                note_text = (note or "").strip()
                if not note_text:
                    continue
                if col_idx >= len(COLUMN_LETTERS):
                    continue
                if row_number == 1:
                    continue
                column_letter = COLUMN_LETTERS[col_idx]
                cell = f"{column_letter}{row_number}"
                try:
                    ws.update_note(cell, note_text)
                except Exception as exc:
                    print(f"[WARN] Failed to set note for {cell}: {exc}")
    except Exception as exc:
        print(f"[WARN] Failed to append rows to sheet: {exc}")


def process_email_payload(body, uid, from_email, cfg, subject="", context=""):
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

    jobs, elapsed = extract_jobs_from_email(trimmed_body, cfg, subject=subject)
    if not jobs:
        print(f"[INFO] Looked job-related but no jobs extracted{label}.")
        return False

    subject_text = (subject or "").strip()
    fallback_location = ""
    city_state_only = ""
    if subject_text:
        city_state_only = _extract_city_state_from_subject(subject_text)
        fallback_location = city_state_only or subject_text
    if fallback_location:
        lowered_subject = subject_text.lower()
        for job in jobs:
            loc = (job.get("location") or "").strip()
            if not loc:
                job["location"] = fallback_location
            elif city_state_only:
                loc_lower = loc.lower()
                if loc_lower == lowered_subject or lowered_subject in loc_lower:
                    job["location"] = city_state_only

    append_jobs_to_sheet(jobs, cfg, sender, elapsed)

    if uid:
        print(f"[OK] Done{label}.")
    return True




def main():
    print("[INFO] Starting email processing run.")

    cfg = load_config()
    if cfg.get("enable_google_debug_logging"):
        logging.getLogger("googleapiclient.discovery").setLevel(logging.DEBUG)
        logging.getLogger("googleapiclient.http").setLevel(logging.DEBUG)
        logging.getLogger("uritemplate").setLevel(logging.DEBUG)
        print("[INFO] Google API debug logging enabled.")

    global _CLEARED_THIS_RUN
    if cfg.get("clear_sheet_before_run") and not _CLEARED_THIS_RUN:
        ws = get_gsheet_worksheet(cfg)
        _clear_data_rows_and_comments(ws, cfg, start_row=2)
        _CLEARED_THIS_RUN = True

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
            subject=cfg.get("debug_subject", ""),
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

        body, uid, from_email, subject = result
        processed = process_email_payload(body, uid, from_email, cfg, subject=subject)
        processed_any = processed_any or processed
        processed_count += 1

    print(f"\n[INFO] Run finished. Processed {processed_count} email(s).")

if __name__=="__main__":
    main()
