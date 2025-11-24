# Security Project

This workspace hosts the Gmail-to-Sheet poller that scans a shared inbox for incoming threats and appends cleaned message summaries to the designated worksheet.

- `scripts/poll_gmail_to_sheet_advanced.py` is the primary driver. It expects a per-project `bot-assets/config.json` with spreadsheet identifiers, sheet names, and behavior flags (mark read, subject filters, etc.). The script merges those values with shared defaults from `shared/Global.json` so credentials and badges can be centralized.
- `bot-assets/` stores the config plus any auxiliary files the driver owns.
- `source/` is for notes, specs, or documentation.

Keep the `Global.json` service account and Gmail secrets in `shared/`; the driver resolves those automatically when `service_account_json` points back to the shared file.
