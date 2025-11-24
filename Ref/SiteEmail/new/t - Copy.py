import imaplib, json, sys, time
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials

from gmail_search_utils import (
    IMAP_HOST, search_unseen_uids, fetch_headers_peek,
    mark_seen_by_uid, DedupeCache, stable_identity
)

CONFIG_FILE = "config.json"

def load_config(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def open_sheet(sa_json_path: str, spreadsheet_id: str, worksheet_name: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(sa_json_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=20)
        # Write header row
        ws.append_row(["processed_at","gm_msgid","message_id","uid","mailbox","subject","from","date_header"], value_input_option="USER_ENTERED")
    return ws

def append_row(ws, row):
    ws.append_row(row, value_input_option="USER_ENTERED")

def main():
    cfg = load_config(CONFIG_FILE)

    USER = cfg["user"]
    APP_PASSWORD = cfg["app_password"]
    SUBJECT_TERM = cfg.get("subject_term", "672-7323")
    SA_JSON = cfg["service_account_json"]
    SPREADSHEET_ID = cfg["spreadsheet_id"]
    WORKSHEET_NAME = cfg.get("worksheet_name", "Inbox")

    # Open Sheets first to fail fast if auth is wrong
    try:
        ws = open_sheet(SA_JSON, SPREADSHEET_ID, WORKSHEET_NAME)
    except Exception as e:
        print(f"[ERROR] Google Sheets authorization/open failed: {e}")
        sys.exit(1)

    # Connect IMAP
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        imap.login(USER, APP_PASSWORD)
    except imaplib.IMAP4.error as e:
        print(f"[ERROR] IMAP login failed: {e}")
        sys.exit(1)

    cache = DedupeCache("processed_ids.json")
    processed = 0

    try:
        uids, mailbox = search_unseen_uids(imap, SUBJECT_TERM, include_all_mail=True)
        if not uids:
            print("No matching UNSEEN messages found.")
            return

        print(f"Found {len(uids)} matching UNSEEN message(s) in {mailbox}.")
        for uid in uids:
            subject, sender, msgid, date_hdr = fetch_headers_peek(imap, uid)
            ident = stable_identity(imap, uid, msgid)

            # Skip if already processed
            if ident and cache.seen(ident):
                print(f"  -> already processed (dedupe). Skipping: {subject}")
                continue

            # Append to Sheet
            processed_at = datetime.now(timezone.utc).isoformat()
            row = [processed_at, ident or "", msgid or "", uid.decode(), mailbox, subject, sender, date_hdr]
            try:
                append_row(ws, row)
                print(f"  -> appended to Sheet: {subject}")
            except Exception as e:
                print(f"[ERROR] Append failed (will not mark read): {e}")
                continue

            # Mark read and record dedupe
            mark_seen_by_uid(imap, uid)
            
            if ident:
                cache.add(ident)
            processed += 1

        print(f"Done. Processed {processed} message(s).")
    finally:
        imap.logout()

if __name__ == "__main__":
    main()
