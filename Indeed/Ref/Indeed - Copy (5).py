#!/usr/bin/env python3
"""
Indeed.py — fetch latest job-alert email from Gmail (supports multiple senders),
extract job info with AI, and append a nicely formatted row to Google Sheets.

This build adds:
- Dual-sender search via `gmail_from_filters` (falls back to `gmail_from_filter`).
- Optional Gmail category filter via X-GM-RAW (Primary/Promotions, etc.).
- Broader Gmail search scopes to fix "No matching messages found" when messages
  aren't labeled INBOX:
    "gmail_search_scope": "inbox" | "anywhere" | "all_mail"
    - inbox    -> search only INBOX (classic IMAP behavior)
    - anywhere -> use X-GM-RAW 'in:anywhere from:"sender"' (search across all mailboxes)
    - all_mail -> select the special All Mail and search there (if server exposes it)
  If your server/language exposes All Mail under a different name, set it in
  "gmail_all_mail_label" (default "[Gmail]/All Mail").
- Diagnostic logging: on no-match, we print the last few "From:" headers in INBOX
  to help confirm actual sender strings.
- NEW (2025‑11‑12): Mark as read happens **after** the body is extracted.
- NEW (2025‑11‑12): Optional `mark_read_thread` to mark all messages in the Gmail conversation.
Patched (2025‑11‑12): Fixed UID dedupe (bytes vs str) in _consider().

Config (config.json in same folder), example:
{
  "service_account_json": "sa_key.json",
  "spreadsheet_id": "YOUR_SHEET_ID_HERE",
  "worksheet_name": "Inbox",
  "openai_model": "gpt-4o-mini",
  "openai_temperature": 0.1,
  "gmail_user": "you@example.com",
  "gmail_app_password": "your-16-char-app-password",
  "gmail_folder": "INBOX",
  "gmail_from_filters": [
    "jobalerts-noreply@linkedin.com",
    "donotreply@match.indeed.com"
  ],
  "gmail_use_category": false,
  "gmail_category": "primary",
  "gmail_only_unseen": false,
  "gmail_search_scope": "anywhere",
  "gmail_all_mail_label": "[Gmail]/All Mail",
  "mark_read": true,
  "mark_read_thread": false
}
"""

# --- Standard header (per user's preference) ---
from ast import Return
from pathlib import Path
from typing import Iterable, List, Set, Tuple, Dict, Any, Optional
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

# ---------------- Standard libs ----------------
import sys
import re
import json
from datetime import datetime


# ---------------- URL extraction ----------------
URL_RE = re.compile(r"https?://[^\\s>')\\\\]]+", re.IGNORECASE)

def extract_urls(text: str) -> List[str]:
    if not text:
        return []
    return list(dict.fromkeys(URL_RE.findall(text)))  # unique, preserve order

# ---------------- AI analysis ----------------
def ai_analyze_email(body: str, model: str, temperature: float = 0.1) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY") or "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"

    if not api_key:
        return {"ok": False, "error": "Missing OPENAI_API_KEY in environment.", "data": None}
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
    try:
        from googleapiclient.discovery import build
    except Exception:
        return
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    for s in ss.get("sheets", []):
        if s["properties"]["title"] == worksheet_title:
            sheet_id = s["properties"]["sheetId"]
            break
    if sheet_id is None:
        return
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
                "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 20}
            }
        },
    ]
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()

# ---------------- Config ----------------
def load_config(cfg_path: str) -> Dict[str, Any]:
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- De-dupe state (idempotency) ----------------
def _state_path(default_name: str = ".indeed_state.json") -> Path:
    try:
        return base_dir / default_name
    except Exception:
        return Path(default_name).resolve()

def _load_state(path: Optional[str] = None) -> Dict[str, Any]:
    fp = Path(path) if path else _state_path()
    if not fp.exists():
        return {"processed_uids": []}
    try:
        with fp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("processed_uids"), list):
            data["processed_uids"] = []
        return data
    except Exception:
        return {"processed_uids": []}

def _save_state(state: Dict[str, Any], path: Optional[str] = None):
    fp = Path(path) if path else _state_path()
    try:
        # cap size to avoid unbounded growth
        if isinstance(state.get("processed_uids"), list) and len(state["processed_uids"]) > 2000:
            state["processed_uids"] = state["processed_uids"][-1000:]
        with fp.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[WARN] Could not write state file: {e}")

# ---------------- Gmail fetch helpers ----------------
import imaplib, email
imaplib.Debug = 4

def _quoted_raw(s: str) -> bytes:
    # Ensure proper quoting/encoding for X-GM-RAW commands when using UID SEARCH
    return ('"%s"' % s.replace('"', '\\"')).encode('utf-8')

def _search_uid_anywhere(mail: imaplib.IMAP4_SSL, sender: str, unseen_only: bool = False,
                         use_category: bool = False, category: Optional[str] = None) -> Optional[bytes]:
    """
    Search across all mail using Gmail X-GM-RAW with 'in:anywhere'. Returns newest UID or None.
    """
    raw_terms = [f'in:anywhere', f'from:"{sender}"']
    if unseen_only:
        raw_terms.append('is:unread')
    if use_category and category:
        raw_terms.append(f'category:{category}')
    raw_query = " ".join(raw_terms)
    print("RAW QUERY:", raw_query)
    try:
        typ, data = mail.uid('search', None, 'X-GM-RAW', raw_query)
        if typ == "OK" and data and data[0]:
            ids = data[0].split()
            return ids[-1] if ids else None
    except Exception:
        return None
    return None

def _search_uid_in_folder(mail: imaplib.IMAP4_SSL, folder: str, sender: str, unseen_only: bool = False,
                          use_category: bool = False, category: Optional[str] = None) -> Optional[bytes]:
    """
    Search inside a selected folder. Tries X-GM-RAW if category requested, else IMAP SEARCH.
    """
    mail.select(folder)
    # Try RAW if category is requested
    if use_category and category:
        raw_terms = [f'from:"{sender}"', f'category:{category}']
        if unseen_only:
            raw_terms.append('is:unread')
        raw_query = " ".join(raw_terms)
        try:
            print(f"[TRACE] RAW command about to send: UID SEARCH X-GM-RAW {_quoted_raw(raw_query)}")
            typ, data = mail.uid('SEARCH', 'X-GM-RAW', _quoted_raw(raw_query))
            if typ == "OK" and data and data[0]:
                ids = data[0].split()
                return ids[-1] if ids else None
        except Exception:
            pass
    # Fallback classic IMAP
    criteria = ['FROM', sender]
    if unseen_only:
        criteria.append('UNSEEN')
    typ, data = mail.search(None, *criteria)
    if typ != "OK" or not data or not data[0]:
        return None
    ids = data[0].split()
    return ids[-1] if ids else None

def _fetch_body_by_uid(mail: imaplib.IMAP4_SSL, uid: bytes) -> str:
    """
    Fetch RFC822 for the given UID and return the decoded text body (plain first, else HTML).
    (No flag changes in this function; marking as read happens after extraction.)
    """
    typ, msg_data = mail.uid('fetch', uid, '(RFC822)')
    if typ != "OK" or not msg_data or not msg_data[0]:
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
    return (body or "").strip()

def _mark_seen(mail: imaplib.IMAP4_SSL, uid: bytes, mark_read_thread: bool = False):
    """
    Mark the message as \\Seen. If mark_read_thread=True, mark the whole Gmail conversation
    using X-GM-THRID to find sibling UIDs.
    """
    try:
        # Mark this message
        mail.uid('store', uid, '+FLAGS', '\\Seen')
    except Exception as e:
        print(f"[WARN] Could not mark UID {uid} seen: {e}")
        return

    if not mark_read_thread:
        return

    # Try to fetch thread id and set all siblings to Seen
    try:
        typ, thr = mail.uid('fetch', uid, '(X-GM-THRID)')
        if typ == 'OK' and thr and thr[0] and isinstance(thr[0], tuple):
            import re as _re
            header = thr[0][0] if isinstance(thr[0][0], (bytes, bytearray)) else b''
            m = _re.search(rb'X-GM-THRID\s+(\d+)', header)
            if m:
                thrid = m.group(1).decode('ascii', errors='ignore')
                typ, sibs = mail.uid('search', None, 'X-GM-THRID', thrid)
                if typ == 'OK' and sibs and sibs[0]:
                    for s_uid in sibs[0].split():
                        try:
                            mail.uid('store', s_uid, '+FLAGS', '\\Seen')
                        except Exception as e2:
                            print(f"[WARN] Could not mark sibling UID {s_uid} seen: {e2}")
    except Exception as e:
        print(f"[WARN] Thread mark failed: {e}")

def _list_recent_from_headers(mail: imaplib.IMAP4_SSL, folder: str, limit: int = 10) -> List[str]:
    out = []
    try:
        mail.select(folder)
        typ, data = mail.search(None, 'ALL')
        if typ != "OK" or not data or not data[0]:
            return out
        ids = data[0].split()
        tail = ids[-limit:]
        for uid in tail:
            typ, hdr = mail.uid('fetch', uid, '(RFC822.HEADER)')
            if typ == "OK" and hdr and hdr[0] and isinstance(hdr[0], tuple):
                import email as py_email
                msg = py_email.message_from_bytes(hdr[0][1])
                out.append(msg.get('From', '(no From)'))
    except Exception:
        pass
    return out

def fetch_latest_email_body_multi(user: str, app_password: str, folder: str,
                                  senders: List[str],
                                  unseen_only: bool = False,
                                  use_category: bool = False,
                                  category: Optional[str] = None,
                                  mark_read: bool = True,
                                  mark_read_thread: bool = False,
                                  search_scope: str = "inbox",
                                  all_mail_label: str = "[Gmail]/All Mail") -> str:
    """
    For a list of senders, finds the newest email among them and returns its body.
    Search scope behavior (in order):
      - inbox: only in the provided folder (e.g., INBOX)
      - anywhere: X-GM-RAW in:anywhere across all mail
      - all_mail: select the special All Mail and search
    Marks messages as read *after* body extraction if mark_read=True.
    """
    print("[INFO] Connecting to Gmail…")
    
 
    mail = imaplib.IMAP4_SSL("imap.gmail.com")

    mail.login(user, app_password)

    candidates: List[Tuple[bytes, str, str]] = []  # (uid, INTERNALDATE, sender_str)

    state = _load_state(cfg.get("dedupe_state_file")) if "cfg" in globals() else _load_state()
    processed = set(str(u) for u in state.get("processed_uids", []))

    def _consider(uid: Optional[bytes], label: str, s: str):
        if not uid:
            return
        uid_str = uid.decode(errors="ignore") if isinstance(uid, (bytes, bytearray)) else str(uid)
        if uid_str in processed:
            print(f"[INFO] Skipping already-processed UID {uid_str}")
            return
        typ, data = mail.uid('fetch', uid, '(INTERNALDATE)')
        if typ == "OK" and data and data[0]:
            try:
                parts = data[0].decode('utf-8', errors='ignore').split('"')
                internal_date = parts[-2] if len(parts) >= 2 else ""
            except Exception:
                internal_date = ""
        else:
            internal_date = ""
        print(f"[INFO] Candidate from {s} via {label}: UID {uid.decode(errors='ignore')} @ {internal_date}")
        candidates.append((uid, internal_date, s))

    for s in senders:
        # 1) INBOX (or configured folder)
        uid = _search_uid_in_folder(mail, folder, s, unseen_only, use_category, category)
        if uid:
            _consider(uid, folder, s)
            continue

        # 2) ANYWHERE via X-GM-RAW
        if search_scope.lower() == "anywhere":
            uid = _search_uid_anywhere(mail, s, unseen_only, use_category, category)
            if uid:
                _consider(uid, "in:anywhere", s)
                continue

        # 3) ALL MAIL if configured
        if search_scope.lower() == "all_mail":
            try:
                uid = _search_uid_in_folder(mail, all_mail_label, s, unseen_only, use_category, category)
                if uid:
                    _consider(uid, all_mail_label, s)
                    continue
            except Exception:
                pass

        print(f"[INFO] No messages found for {s}.")

    if not candidates:
        # Diagnostics: show last few "From" headers in INBOX to verify actual addresses
        print("[WARN] No matching emails found across provided senders.")
        print("[DIAG] Recent INBOX From headers (last 10):")
        for frm in _list_recent_from_headers(mail, folder, limit=10):
            print(f"       - {frm}")
        try: mail.logout()
        except Exception: pass
        return ""

    # Pick newest by INTERNALDATE
    def _parse_dt(s: str) -> float:
        try:
            return datetime.strptime(s, "%d-%b-%Y %H:%M:%S %z").timestamp()
        except Exception:
            return 0.0

    best_uid, _, _ = max(candidates, key=lambda tup: _parse_dt(tup[1]))
    body = _fetch_body_by_uid(mail, best_uid)

    # Mark read AFTER extraction
    if mark_read:
        _mark_seen(mail, best_uid, mark_read_thread=mark_read_thread)

    try: mail.logout()
    except Exception: pass
    print("[INFO] Retrieved latest job-alert email.")
    return body, best_uid

# ---------------- Main ----------------
def main():
    cfg_path = os.getenv("INDEED_CONFIG", "config.json")
    try:
        global cfg
        cfg = load_config(cfg_path)
        print(f"[INFO] Using config: {cfg_path}")
    except FileNotFoundError:
        print(f"[ERROR] Config not found: {cfg_path}")
        sys.exit(1)

    sa_json = cfg.get("service_account_json", "sa_key.json")
    sheet_id = cfg["spreadsheet_id"]
    worksheet_name = cfg.get("worksheet_name", "Inbox")
    model = cfg.get("openai_model", "gpt-4o-mini")
    temperature = float(cfg.get("openai_temperature", 0.1))

    gmail_user = cfg.get("gmail_user")
    gmail_app_password = cfg.get("gmail_app_password")
    gmail_folder = cfg.get("gmail_folder", "INBOX")

    gmail_from_filter = cfg.get("gmail_from_filter")
    gmail_from_filters = cfg.get("gmail_from_filters")
    senders = []
    if gmail_from_filters and isinstance(gmail_from_filters, list):
        senders = gmail_from_filters
    elif gmail_from_filter:
        senders = [gmail_from_filter]
    else:
        senders = ["jobalerts-noreply@linkedin.com", "donotreply@match.indeed.com"]

    gmail_use_category = bool(cfg.get("gmail_use_category", False))
    gmail_category = cfg.get("gmail_category")  # e.g., "primary"
    gmail_only_unseen = bool(cfg.get("gmail_only_unseen", True))
    gmail_search_scope = (cfg.get("gmail_search_scope") or "inbox").lower()
    gmail_all_mail_label = cfg.get("gmail_all_mail_label", "[Gmail]/All Mail")
    mark_read = bool(cfg.get("mark_read", True))
    mark_read_thread = bool(cfg.get("mark_read_thread", False))

    if not (gmail_user and gmail_app_password):
        print("[ERROR] Missing gmail_user/gmail_app_password in config.json.")
        sys.exit(2)

    result = fetch_latest_email_body_multi(
        gmail_user,
        gmail_app_password,
        folder=gmail_folder,
        senders=senders,
        unseen_only=gmail_only_unseen,
        use_category=gmail_use_category,
        category=(gmail_category or None),
        mark_read=mark_read,
        mark_read_thread=mark_read_thread,
        search_scope=gmail_search_scope,
        all_mail_label=gmail_all_mail_label,
    )

#    if not result or not isinstance(result, (tuple, list)) or len(result) != 2:
#       print("[WARN] No email body returned by fetch; skipping this cycle.")
#    return
 
    try:
        body, processed_uid = result
        body = (body or "").strip()
    except:
        return
    if not body:
        print("[ERROR] No email body retrieved.")
        return


    print("[INFO] Extracting URLs…")
    urls = extract_urls(body)
    print(f"[INFO] Found {len(urls)} URL(s)")

    print("[INFO] Calling OpenAI for structured parse…")
    ai = ai_analyze_email(body, model=model, temperature=temperature)
    if ai["ok"]:
        data = ai["data"] or {}
    else:
        data = {"urls": urls, "title": None, "company": None, "location": None, "summary": []}

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

    try:
        print("[INFO] Applying pretty formatting…")
 #       pretty_format_sheet(sheet_id, worksheet_name, creds)
    except Exception as e:
        print(f"[WARN] Formatting skipped: {e}")

    print("[OK] Row appended.")
    try:
        st = _load_state(cfg.get("dedupe_state_file"))
        arr = st.get("processed_uids", [])
        arr.append(processed_uid.decode(errors="ignore") if isinstance(processed_uid, (bytes, bytearray)) else str(processed_uid))
        st["processed_uids"] = arr
        _save_state(st, cfg.get("dedupe_state_file"))
        print("[OK] Dedupe state updated.")
    except Exception as e:
        print(f"[WARN] Could not update dedupe state: {e}")

    if not ai["ok"]:
        print(f"[WARN] AI step failed: {ai['error']}")
    else:
        print("[OK] AI enrichment applied.")

if __name__ == "__main__":
    main()
