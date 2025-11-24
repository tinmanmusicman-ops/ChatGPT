from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os, json, imaplib, email, inspect, re, time
from email.header import decode_header
from datetime import datetime
from openai import OpenAI

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    raise SystemExit("Install gspread + google-auth")

EXTRACTION_PROMPT = """
You are a data extraction assistant.
Extract job-related URLs only.
Output JSON only.
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
        mail.store(uid, "+FLAGS", "\\Seen")
        mail.logout()
        print(f"[INFO] Marked UID {uid} as read.")
    except Exception as e:
        print(f"[WARN] Could not mark {uid} read: {e}")

def is_relevant_job_email(body: str) -> bool:
    if not body:
        return False
    text = body.lower()
    job_keywords = ("job","jobs","view job","apply now","new job")
    if not any(k in text for k in job_keywords):
        return False
    domains = ("indeed.com","linkedin.com/jobs")
    if not any(d in body for d in domains):
        return False
    return True

def extract_jobs_from_email(body, cfg):
    print(f"[INFO] Line {inspect.currentframe().f_lineno} AI extraction started…")
    client = get_openai_client(cfg)
    response = client.responses.create(
        model=cfg.get("openai_model","gpt-4.1-mini"),
        instructions=EXTRACTION_PROMPT.strip(),
        input=body,
        temperature=0.1,
    )
    raw = getattr(response,"output_text",None)
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
                "url":j.get("url")
            })
    print(f"[INFO] AI extraction finished. {len(jobs)} job(s).")
    return jobs

def get_unread_email_body(cfg):
    mail=imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(cfg["gmail_user"], cfg["gmail_app_password"])
    mail.select("INBOX")
    typ,data=mail.search(None,'X-GM-RAW','"category:primary"','UNSEEN')
    if typ!="OK":
        mail.logout()
        return None
    ids=data[0].split()
    if not ids:
        mail.logout()
        return None
    msg_id=ids[0]
    uid=msg_id.decode()
    typ,msg_data=mail.fetch(msg_id,"(RFC822)")
    if typ!="OK":
        mail.logout()
        return None
    raw=msg_data[0][1]
    msg=email.message_from_bytes(raw)
    body=""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition()=="attachment":
                continue
            payload=part.get_payload(decode=True)
            if payload:
                text=payload.decode(part.get_content_charset() or "utf-8","replace")
                if part.get_content_type()=="text/html" and not body:
                    body=text
                elif part.get_content_type()=="text/plain" and not body:
                    body=text
    else:
        payload=msg.get_payload(decode=True)
        if payload:
            body=payload.decode(msg.get_content_charset() or "utf-8","replace")
    mail.logout()
    return body,uid

def get_gsheet_worksheet(cfg):
    sa=base_dir/cfg.get("service_account_json","Glocal.json")
    scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds=Credentials.from_service_account_file(str(sa),scopes=scopes)
    client=gspread.authorize(creds)
    sh=client.open_by_key(cfg["spreadsheet_id"])
    return sh.worksheet(cfg["worksheet_name"])

def append_jobs_to_sheet(jobs,cfg):
    ws=get_gsheet_worksheet(cfg)
    ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows=[[ts,j["job_name"] or "",j["company_name"] or "",j["url"]] for j in jobs]
    ws.append_rows(rows,value_input_option="USER_ENTERED")
    print(f"[OK] Appended {len(rows)} row(s).")

def main():
    cfg=load_config()

    if cfg.get("debug_use_email_body_file"):
        f=base_dir/"email_body.txt"
        if f.exists():
            body=f.read_text()
            uid=None
        else:
            body=None
            uid=None
    else:
        result=get_unread_email_body(cfg)
        if not result:
            print("[INFO] No email body found.")
            return
        body,uid=result

    if not body or not body.strip():
        print("[INFO] Empty body.")
        return

    if not is_relevant_job_email(body):
        print("[INFO] Not job-related. Leaving UNREAD.")
        return

    jobs=extract_jobs_from_email(body,cfg)
    if not jobs:
        print("[INFO] Looked job-related but no jobs extracted.")
        return

    append_jobs_to_sheet(jobs,cfg)

    if uid:
        mark_email_as_read(cfg,uid)

    print("[OK] Done.")

if __name__=="__main__":
    main()
