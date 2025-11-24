# Migration Log

## 2025-11-23

- **Security**: Re-aligned `scripts/poll_gmail_to_sheet_advanced.py` with the shared `Global.json` defaults and normalized Gmail credentials so the driver now relies on the per-project `bot-assets/config.json` while still merging service account data and env overrides.
- **Security**: Replaced the placeholder Fax config with a minimal Security-specific `bot-assets/config.json` that points to the shared service account, spreadsheet, and behavior flags so the project can be self-contained.
- **Security**: Updated `README.md` to describe the Security project layout and how the driver resolves shared secrets.
