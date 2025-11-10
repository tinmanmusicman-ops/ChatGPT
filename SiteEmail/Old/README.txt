Gmail → Google Sheets Poller
============================
Updated: 2025-11-09

What this does
--------------
- Reads emails from Gmail via IMAP (defaults to UNSEEN in INBOX)
- Appends date, from, subject, body snippet, and Message-ID to a Google Sheet
- Can mark processed emails as read

One-time setup
--------------
1) Enable APIs in your Google Cloud project:
   - Google Sheets API
   - Google Drive API
2) Create/download a service account key JSON and save it as:
   service_account.json  (place it beside the script)
   Then share your target Google Sheet with the service account *email* as Editor.
3) Install Python requirements:
   pip install -r requirements.txt
4) Copy .env.example to .env and fill your values.

.env keys
---------
GMAIL_USER / GMAIL_PASS : Your Gmail address and *App Password* (not your regular password)
SPREADSHEET_ID or SPREADSHEET_NAME : Choose one (ID is safest)
WORKSHEET_NAME : The sheet tab to write to (default Sheet1)
GMAIL_FOLDER / SEARCH_QUERY : IMAP search settings (e.g., UNSEEN)
MARK_READ : true/false to mark processed emails as read
MAX_MESSAGES : cap how many messages to append per run
SERVICE_ACCOUNT_FILE : optional absolute path to your JSON key

Run it
------
python poll_gmail_to_sheet.py

Troubleshooting
---------------
- If you see "Google Sheets authorization/open failed":
    * Confirm service_account.json exists
    * Confirm the Sheet is shared with the service account email (Editor)
    * Make sure Sheets + Drive APIs are enabled in the same project
- If you see "GMAIL_USER is not set":
    * Ensure .env exists and keys are filled, then rerun
