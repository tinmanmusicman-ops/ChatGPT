#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail → Google Sheets poller (title-based or ID-based open)
- Auth to Sheets via service_account.json (+ Drive scope for title search)
- Auth to Gmail via IMAP using app password (from .env)
- Appends basic message info to the target worksheet
- Optional: mark processed emails as read

Required:
  - service_account.json in the same directory OR set SERVICE_ACCOUNT_FILE
  - .env with:
        GMAIL_USER=your_email@gmail.com
        GMAIL_PASS=your_app_password
        # One of the two:
        # SPREADSHEET_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        # SPREADSHEET_NAME=Inbox Log
        WORKSHEET_NAME=Sheet1
        GMAIL_FOLDER=INBOX
        SEARCH_QUERY=UNSEEN
        MARK_READ=true

Run:
  python poll_gmail_to_sheet.py
"""
import os
import sys
import time
import imaplib
import email
import logging
from email.header import decode_header, make_header
from typing import List, Tuple, Optional

import gspread
from dotenv import load_dotenv

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gmail_to_sheets_poller")

# ---------- Helpers ----------
def getenv_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

def getenv_str(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    if val is None or str(val).strip() == "":
        return default
    return val

def load_env() -> None:
    # Load .env if present (don’t override existing env vars)
    load_dotenv(override=False)

# ---------- Google Sheets ----------
def authorize_sheets():
    """
    Returns a gspread Worksheet object using either SPREADSHEET_ID or SPREADSHEET_NAME.
    Includes Drive metadata scope so client.open(title) works.
    """
    service_account_file = getenv_str("SERVICE_ACCOUNT_FILE", "service_account.json")
    if not os.path.exists(service_account_file):
        raise FileNotFoundError(
            f"Service account file not found: {service_account_file}. "
            "Place service_account.json next to this script or set SERVICE_ACCOUNT_FILE."
        )

    client = gspread.service_account(
        filename=service_account_file,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.metadata.readonly",  # required for title search
        ],
    )

    spreadsheet_id = getenv_str("SPREADSHEET_ID")
    spreadsheet_name = getenv_str("SPREADSHEET_NAME")
    worksheet_name = getenv_str("WORKSHEET_NAME", "Sheet1")

    if spreadsheet_id:
        sh = client.open_by_key(spreadsheet_id)
    elif spreadsheet_name:
        sh = client.open(str(spreadsheet_name))
    else:
        raise RuntimeError("Set either SPREADSHEET_ID or SPREADSHEET_NAME in your .env")

    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        # Create the worksheet if it doesn't exist
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=20)
        # Optionally set a header row
        ws.append_row(["Date", "From", "Subject", "Snippet", "Message-ID"])
    return ws

# ---------- Gmail (IMAP) ----------
def connect_imap():
    user = getenv_str("GMAIL_USER")
    pw = getenv_str("GMAIL_PASS")

    if not user:
        raise RuntimeError("GMAIL_USER is not set. Check your .env")
    if not pw:
        raise RuntimeError("GMAIL_PASS is not set. Use a Gmail App Password in your .env")

    imap_host = getenv_str("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))

    mail = imaplib.IMAP4_SSL(imap_host, imap_port)
    mail.login(user, pw)
    return mail

def decode_mime(s: Optional[str]) -> str:
    if not s:
        return ""
    try:
        decoded = str(make_header(decode_header(s)))
    except Exception:
        decoded = s
    return decoded

def get_text_snippet(msg) -> str:
    """
    Pull a short text snippet from the email body (first text/plain part found).
    """
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = str(part.get("Content-Disposition") or "")
                if ctype == "text/plain" and "attachment" not in disp.lower():
                    payload = part.get_payload(decode=True) or b""
                    return (payload.decode(part.get_content_charset() or "utf-8", errors="replace")).strip()[:500]
        else:
            if msg.get_content_type() == "text/plain":
                payload = msg.get_payload(decode=True) or b""
                return (payload.decode(msg.get_content_charset() or "utf-8", errors="replace")).strip()[:500]
    except Exception:
        return ""
    return ""


def _seqs_to_uids(mail, seq_ids: list[bytes]) -> list[bytes]:
    """Convert IMAP sequence numbers -> stable UIDs."""
    uids: list[bytes] = []
    for seq in seq_ids:
        typ, data = mail.fetch(seq, "(UID)")
        if typ == "OK" and data and isinstance(data[0], tuple):
            # Example: b'123 (UID 4567)'
            line = data[0][0]
            # Extract the last token as UID
            parts = line.split()
            uid = parts[-1].rstrip(b')')
            uids.append(uid)
    return uids

def search_messages(mail, folder: str, _query_ignored: str) -> List[bytes]:
    """
    Find UNSEEN messages whose subject contains '672-7323'.
    Prefer Gmail X-GM-RAW with category:primary + is:unread,
    fall back to standard IMAP UID search, then to [All Mail].
    Always returns UIDs (bytes).
    """
    import imaplib
    from typing import List

    # 1) Open the requested folder read-write so flags persist
    typ, _ = mail.select(folder, readonly=False)
    if typ != "OK":
        raise RuntimeError(f"Could not select folder {folder}")

    # 2) Gmail RAW — IMPORTANT: include is:unread
    forced_query = 'category:primary subject:"672-7323" is:unread'
    log.info(f"Using Gmail RAW query: {forced_query}")

    uids: List[bytes] = []
    try:
        # X-GM-RAW must be a single quoted string; UID everywhere for consistency
        typ, data = mail.uid("SEARCH", "X-GM-RAW", f'"{forced_query}"')
        if typ == "OK" and data and data[0]:
            uids = data[0].split()
    except imaplib.IMAP4.error as e:
        log.warning(f"X-GM-RAW failed ({e}); trying IMAP UID SUBJECT+UNSEEN.")

    # 3) Fallback: standard IMAP search, still in UID space and still UNSEEN
    if not uids:
        # Avoid quotes on the term to allow partial matches (exact quotes are too strict)
        typ, data = mail.uid("SEARCH", None, "(UNSEEN SUBJECT 672-7323)")
        if typ == "OK" and data and data[0]:
            uids = data[0].split()

    # 4) Final fallback: All Mail (still UNSEEN), in case the message isn't in INBOX/Primary
    if not uids and folder != '"[Gmail]/All Mail"':
        log.info('No matches; falling back to "[Gmail]/All Mail".')
        typ, _ = mail.select('"[Gmail]/All Mail"', readonly=False)
        if typ == "OK":
            try:
                typ, data = mail.uid("SEARCH", "X-GM-RAW", f'"{forced_query}"')
                if typ == "OK" and data and data[0]:
                    uids = data[0].split()
                else:
                    typ, data = mail.uid("SEARCH", None, "(UNSEEN SUBJECT 672-7323)")
                    if typ == "OK" and data and data[0]:
                        uids = data[0].split()
            except imaplib.IMAP4.error as e:
                log.warning(f"All Mail search failed ({e}).")

    log.debug(f"Found {len(uids)} matching UNSEEN message(s).")
    return uids



"""
def search_messages(mail, folder: str, _query_ignored: str) -> List[bytes]:
    
    Force Primary + subject contains '672-7323' using Gmail's X-GM-RAW.
    Clean and compatible with Gmail IMAP servers.
    
    forced_query = 'category:primary subject:"672-7323"'
    # Select mailbox
    typ, _ = mail.select(folder, readonly=False)
    if typ != "OK":
        raise RuntimeError(f"Could not select folder {folder}")

    log.info(f"Using Gmail RAW query: {forced_query}")

    # Gmail requires the argument to be quoted, as a str, not bytes
    try:
        typ, data = mail.uid("SEARCH", None, "X-GM-RAW", f'"{forced_query}"')
    except imaplib.IMAP4.error as e:
        log.warning(f"X-GM-RAW failed ({e}); trying standard IMAP subject filter.")
        typ, data = mail.search(None, '(SUBJECT "672-7323")')

    if typ != "OK":
        log.error(f"IMAP SEARCH failed: {typ} {data}")
        return []

    ids = data[0].split() if data and data[0] else []
    log.debug(f"Found {len(ids)} matching message(s).")
    return ids
"""




def fetch_message(mail, msg_id: bytes, use_uid: bool = False):
    cmd = "UID FETCH" if use_uid else "FETCH"
    typ, data = mail.uid("FETCH", msg_id, "(RFC822)") if use_uid else mail.fetch(msg_id, "(RFC822)")
    if typ != "OK" or not data or data[0] is None:
        return None
    raw = data[0][1]
    return email.message_from_bytes(raw)

def mark_seen(mail, msg_id: bytes, use_uid: bool = False):
    if use_uid:
        mail.uid("STORE", msg_id, "+FLAGS", r"(\Seen)")
    else:
        mail.store(msg_id, "+FLAGS", r"(\Seen)")

# ---------- Main logic ----------
def process_messages(ws, max_messages: int = 50):
    mail = connect_imap()
    folder = getenv_str("GMAIL_FOLDER", "INBOX")
    query = getenv_str("SEARCH_QUERY", "UNSEEN")
    mark_read = getenv_bool("MARK_READ", True)

    log.info(f"Searching folder '{folder}' with query '{query}'")
    ids = search_messages(mail, folder, query)
    if not ids:
        log.info("No messages found.")
        mail.logout()
        return 0

    # Process most recent first
    ids = ids[-max_messages:]

    added = 0
    for msg_id in ids:
        msg = fetch_message(mail, msg_id)
        if not msg:
            continue

        date = decode_mime(msg.get("Date"))
        from_ = decode_mime(msg.get("From"))
        subj = decode_mime(msg.get("Subject"))
        mid = decode_mime(msg.get("Message-ID"))
        snippet = get_text_snippet(msg)

        ws.append_row([date, from_, subj, snippet, mid])
        added += 1

        if mark_read:
            mark_seen(mail, msg_id)

    mail.logout()
    log.info(f"Appended {added} messages to the sheet.")
    return added

def main():
    try:
        load_env()
        ws = authorize_sheets()
        processed = process_messages(ws, max_messages=int(os.environ.get("MAX_MESSAGES", "50")))
        if processed == 0:
            log.info("Done. Nothing to append.")
        else:
            log.info(f"Done. Appended {processed} rows.")
    except Exception as e:
        log.exception("Google Sheets authorization/open failed. Exiting." if isinstance(e, (gspread.exceptions.APIError, FileNotFoundError, RuntimeError)) else "Unexpected error")
        sys.exit(1)

if __name__ == "__main__":
    main()
