# Gmail → Google Sheets Poller (High-Detail Logging)

This tool watches your Gmail inbox for **UNREAD** messages whose **Subject** contains a marker (e.g., `672-7323`). When found, it extracts the body text and appends a new row to your Google Sheet (timestamp, content).

## What it does
- Polls Gmail via **IMAP**.
- Matches messages with subject containing the value of `PHONE_MARKER`.
- Appends `[timestamp, content]` to the first worksheet of the spreadsheet named in `SPREADSHEET_NAME`.
- Highest-detail logging to console and to `./logs/poller.log` (rotating).

## One-time setup
1. **Install Python packages**
   ```bash
   pip install -r requirements.txt
   ```

2. **Google Sheets access (service account)**
   - Create a Google Cloud **Service Account** and download a **JSON key** file.
   - Save it as `service_account.json` in this folder.
   - In Google Sheets, open your spreadsheet (e.g., **LGBTQ**) and **Share** it with the service account's email (Editor).

3. **Environment variables**
   - Copy `.env.example` to `.env` and fill in:
     ```
     GMAIL_USER=your@gmail.com
     GMAIL_APP_PASSWORD=your_app_password
     PHONE_MARKER=672-7323
     SPREADSHEET_NAME=LGBTQ
     ```

   - (Optional) Adjust poll interval, timezone, etc. in `.env`.

4. **Security reminder**
   - Never commit your real `.env` or `service_account.json` to public repos.
   - If you’ve shared an app password, regenerate it and update `.env`.

## Run
```bash
python poll_gmail_to_sheet.py
```

## Columns
- Column 1: timestamp (ISO, local TZ by default: `America/Los_Angeles`)
- Column 2: content (email body text; HTML is stripped)

## Troubleshooting
- Logs are written to `./logs/poller.log` (up to ~5 MB per file, 5 backups).
- Ensure the service account has **Editor** access to the sheet.
- If the sheet name or worksheet index is wrong, update `.env` (see `.env.example`).

