# Upwork Email -> AI -> Sheets (Python)

Deterministic Python workflow that:
- reads unread Upwork emails from IMAP
- extracts job details per email
- dedupes by `Message ID` against Google Sheets
- evaluates each new job with OpenAI (strict JSON)
- appends only accepted jobs to Sheets
- writes structured logs

## 1. Setup

```powershell
cd c:\ChatGPT\upworks
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Config

Use `C:\ChatGPT\shared\Global.json` directly.

Required key names in `Global.json`:
- `gmail_user`
- `gmail_app_password`
- `openai_api_key`
- `LEADGEN_OPENAI_MODEL`
- `spreadsheet_id`
- `type`
- `project_id`
- `private_key_id`
- `private_key`
- `client_email`
- `client_id`
- `auth_uri`
- `token_uri`
- `auth_provider_x509_cert_url`
- `client_x509_cert_url`

Optional Upwork keys (if omitted, internal constants are used):
- `jobs_raw_query`
- `jobs_allowed_sender_domain`
- `jobs_max_emails_per_run`
- `jobs_worksheet_name`
- `jobs_message_id_column`
- `jobs_done_label_name`
- `jobs_ai_model`
- `jobs_ai_temperature`
- `jobs_ai_max_tokens`
- `openai_timeout_ms`
- `jobs_detail_noise_phrase`

Worksheet must include these columns in row 1:
   - Existing n8n columns are supported directly (`Timestamp`, `Do Bid`, `URL`, `Job Description`, `Price`, `MessageID`).
   - Alias columns are also accepted (`Message ID`, `MessagID`, etc.).

## 3. Run

```powershell
python main.py --config C:\ChatGPT\shared\Global.json
```

If no unread Upwork emails are found, run exits cleanly and logs:
`No unread Upwork emails`

## Notes

- Fail-fast on missing config/headers/credentials/lock.
- Extraction and AI JSON errors are logged and skipped per email.
- Atomicity for local concurrency is enforced with file lock `run.lock`.
- For accepted jobs written to Sheets, mailbox actions run in this order:
  - add label `jobs_done_label_name` (default `Upwork`)
  - remove Inbox label
  - mark as read
