from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os, json, imaplib, email, inspect, re, time
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime
from openai import OpenAI
import time
imaplib.Debug = 4
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
   - If unsure, return null
   
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

   


 tructure:
{
  "jobs": [
    {
      "job_name": string|null,
      "company_name": string|null,
      "url": string,
      "company_summary": string|null,
      "decision_factors": string|null
      "location": string|null
    }
  ]
}

"""

def load_config():
    return json.loads((base_dir / "config.json").read_text())

def get_openai_client(cfg):
    api_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def mark_email_as_read(cfg, uid):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(cfg["gmail_user"], cfg["gmail_app_password"])
        mail.select("INBOX")
 
        res_lbl, data_lbl = mail.uid("FETCH", uid, "(X-GM-LABELS)")
        print("[DEBUG] CURRENT LABELS:", res_lbl, data_lbl)
        input(">>> PAUSED — press Enter to continue...")
 
 #
        mail.uid("STORE", uid, "+X-GM-LABELS", "(\\P)")
        mail.uid("STORE", uid, "-X-GM-LABELS", "(\\Inbox)")
        print(f"[INFO] Labeled UID {uid} as Processed.")
 #
 
 
        mail.logout()
        print(f"[INFO] Marked UID {uid} as read.")
    except Exception as e:
        print(f"[WARN] Could not mark {uid} read: {e}")
 
 

def extract_original_sender_from_body(body: str) -> str | None:
    """
    Try to detect the original sender in a forwarded email body.

    Looks for lines like:
      From: Name <email@example.com>
      From: email@example.com
    """
    if not body:
        return None

    pattern = re.compile(
        r"^From:\s*(?:.*<([^>]+)>|([^ \r\n]+@[^ \r\n]+))",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(body)
    if not match:
        return None

    email_addr = match.group(1) or match.group(2)
#    breakpoint()
    return email_addr.strip()

def is_relevant_job_email(body: str) -> bool:
    if not body:
        return False
    text = body.lower()
    job_keywords = ("linkedin", "automation", "jobalerts", "job_alert", "job alert","job","jobs","view job","apply now","new job")
    if not any(k in text for k in job_keywords):
        return False
    domains = ("indeed","linkedin")
    if not any(d in body for d in domains):
        return False
    return True

def extract_jobs_from_email(body, cfg):
    print(f"[INFO] Line {inspect.currentframe().f_lineno} AI extraction started…")
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
    jobs=[]
    for j in data.get("jobs",[]):
        if isinstance(j,dict) and j.get("url"):
            jobs.append({
                "job_name":j.get("job_name"),
                "company_name":j.get("company_name"),
                "company_summary":j.get("company_summary"),
                "location": j.get("location"),
                "decision_factors": j.get("decision_factors"),
                "url":j.get("url")
            })
    print(f"[INFO] AI extraction finished. {len(jobs)} job(s).")
#    breakpoint()
    return jobs, elapsed


def get_unread_email_body(cfg):
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

    try:
        mail.uid("STORE", uid, "+X-GM-LABELS", "(Processed)")
    except Exception:
        pass

    mail.logout()
    return body, uid, source_email


def get_gsheet_worksheet(cfg):
    sa=base_dir/cfg.get("service_account_json","Glocal.json")
    scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds=Credentials.from_service_account_file(str(sa),scopes=scopes)
    client=gspread.authorize(creds)
    sh=client.open_by_key(cfg["spreadsheet_id"])
    return sh.worksheet(cfg["worksheet_name"])

def append_jobs_to_sheet(jobs,cfg,from_email,elapsed):

    ws=get_gsheet_worksheet(cfg)
    ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
 
 
 
    rows = [
 
    [
        ts if i == 0 else "",
        f"{elapsed:.3f}" if i == 0 else "",
        f'=HYPERLINK("{j["url"]}", "{j["job_name"] or "Job Link"}")',
        j["company_name"] or "",
        j["location"] or "",
        j["company_summary"] or "",
        j["decision_factors"] or "",
        from_email if i == 0 else ""
    ]
 
    for i, j in enumerate(jobs)
    ]
 




#    rows=[[ts,j["job_name"] or "",j["company_name"] or "",j["url"],j["company_summary"] or ""] for j in jobs]
    ws.append_rows(rows,value_input_option="USER_ENTERED")
    print(f"[OK] Appended {len(rows)} row(s).")




def main():
    cfg = load_config()

    if cfg.get("debug_use_email_body_file"):
        f = base_dir / "email_body.txt"
        if f.exists():
            body = f.read_text()
            uid = None
            from_email = None
        else:
            body = None
            uid = None
            from_email = None
    else:
        result = get_unread_email_body(cfg)
        if not result:
            print("[INFO] No email body found.")
            return
        body, uid, from_email = result

    if not body or not body.strip():
        print("[INFO] Empty body.")
        return

    if not is_relevant_job_email(body):
        print("[INFO] Not job-related.")
        return

    # from_email is captured here for future use (e.g., logging or sheet columns)
    if from_email:
        print(f"[INFO] Source email detected: {from_email}")

    jobs, elapsed = extract_jobs_from_email(body, cfg)
    if not jobs:
        print("[INFO] Looked job-related but no jobs extracted.")
        return

    append_jobs_to_sheet(jobs, cfg, from_email, elapsed)

# moved successful file to Processed folder
    if uid:
        mark_email_as_read(cfg, uid)

    print("[OK] Done.")

if __name__=="__main__":
    main()
