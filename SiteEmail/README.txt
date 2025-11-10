Gmail ➜ Google Sheets Poller (UID-safe, deduped, mark-as-read)
==============================================================

This package polls Gmail by IMAP, finds UNREAD messages that match a subject term,
appends a row to Google Sheets, marks each message as READ, and never reprocesses
the same message (dedupe via Gmail X-GM-MSGID / Message-ID).

Contents
--------
- poll_gmail_to_sheet.py         : Main poller
- gmail_search_utils.py          : IMAP helpers (UID-safe search/fetch/mark + dedupe)
- config.json                    : Configuration template (fill this in)
- processed_ids.json             : Dedupe store (auto-managed)
- run_poller.bat                 : Windows runner
- requirements.txt               : Python dependencies
- README.txt                     : This file

What gets appended to the sheet
-------------------------------
Columns (in this order):
  A) processed_at     : UTC ISO timestamp when row was appended
  B) gm_msgid         : Gmail's stable message ID (best dedupe key)
  C) message_id       : RFC Message-ID (fallback dedupe key)
  D) uid              : IMAP UID within current mailbox
  E) mailbox          : The mailbox the search selected (INBOX or [Gmail]/All Mail)
  F) subject
  G) from
  H) date_header      : Raw Date header string

Quick Start
-----------
1) Install Python 3.9+.
2) Open a terminal in this folder and install deps:
      pip install -r requirements.txt
3) Create a Google Cloud Service Account and enable **Google Sheets API**:
   - https://console.cloud.google.com/  → APIs & Services → Enable APIs and Services → Google Sheets API
   - Create Credentials → Service Account → download JSON key (keep it private).
4) Share your target Google Sheet with the **client_email** from that JSON (Editor access).
   - In Google Sheets: Share → add the service account email.
5) Edit config.json:
   - "user": your Gmail address
   - "app_password": your 16-character Gmail App Password (no spaces)
   - "subject_term": the subject term to match (e.g., "672-7323")
   - "spreadsheet_id": Google Sheets ID (the long ID in the URL)
   - "worksheet_name": target tab name (will be created if missing)
   - "service_account_json": path/filename of the JSON key (e.g., "sa_key.json" placed next to this script)
6) Put the service account JSON key file in the same folder and ensure the "service_account_json" path in config.json matches.
7) Double-click run_poller.bat (or run: python poll_gmail_to_sheet.py)

Notes
-----
- The search checks INBOX first, then falls back to "[Gmail]/All Mail" if needed.
- All IMAP operations use UID forms to avoid sequence/UID mismatches.
- Reading uses BODY.PEEK so it won't set \Seen implicitly; we mark read explicitly on success.
- Dedupe uses X-GM-MSGID when available (stable across labels), otherwise Message-ID.
- To reprocess from scratch, delete processed_ids.json (or remove specific IDs).

Troubleshooting
---------------
- IMAP auth fails → ensure you use a Gmail **App Password** (with 2FA on), not your normal password.
- Sheets auth fails → make sure the Sheet is shared with the service account email from your JSON.
- Permission denied on append → the service account must have Editor access to the Sheet.
- No rows appear → confirm the worksheet name exists; if not, the script will attempt to create it.
