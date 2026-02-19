# HSST/Python -> n8n Structural Mirror Mapping

Source Python: `ai-bots/Security/scripts/SiteCheck.py`
Target n8n: `ai-bots/n8n/Security/n8n_security_hsst_structural_mirror.json`

## A) 1:1 Mapping Table

| Python step/function | n8n node name |
|---|---|
| main() entry | Manual Trigger / Schedule Trigger |
| load_config() + load_shared_defaults() | 01 load_config + load_shared_defaults |
| normalize_credentials() | 02 normalize_credentials |
| search term assembly + now_local_iso() | 03 build_search_query + now_local_iso |
| open_sheet() (sheet access) | 04 open_sheet (read header) |
| ensure_header() header check | 05 ensure_header (evaluate) |
| ensure_header() branch | 06 IF header_missing |
| ensure_header() append header | 07 ensure_header (append) |
| config carry-forward for loop phase | 08 rehydrate_config |
| open_imap() + search_uids() | 09 search_uids (Gmail get many) |
| fetch_rfc822() | 10 fetch_rfc822 (Gmail get) |
| extract_text_from_msg() + cleaner pipeline + body_contains_sc_marker() | 11 extract_text_from_msg + body_contains_sc_marker |
| marker gate | 12 IF body_contains_sc_marker |
| strip_sc_marker() + whitespace normalize | 13 strip_sc_marker |
| append_rows() | 14 append_rows (Google Sheets) |
| mark_read_thread branch gate | 15 IF mark_read_thread |
| get_thread_id() | 16 get_thread_id (Gmail thread get) |
| list_uids_in_thread() | 17 list_uids_in_thread (expand) |
| mark_seen() for thread members | 18 mark_seen (thread messages) |
| mark_read message branch gate | 19 IF mark_read |
| mark_seen() for single message | 20 mark_seen (single message) |

## B) Workflow Deliverable

- File created: `ai-bots/n8n/Security/n8n_security_hsst_structural_mirror.json`
- Uses native Google nodes:
  - `n8n-nodes-base.gmail`
  - `n8n-nodes-base.googleSheets`
- Data is passed step-by-step across discrete nodes (no single-node Python wrapper).

## C) Non-direct Matches (n8n-native closest equivalent)

1. Python IMAP protocol (`open_imap`) does not exist as a native Gmail node protocol in n8n.
- Closest n8n-native equivalent used: Gmail node operations (`message.getAll`, `message.get`, `message.markAsRead`, `thread.get`) via Google OAuth.

2. Python `resolve_service_account_path()` uses local service-account file path resolution.
- Closest n8n-native equivalent used: Google Sheets node with credential-managed auth in n8n (no file path resolution node).

3. Python logger setup (`setup_logger`) is process-level logging.
- Closest n8n-native equivalent: execution logs + node outputs/errors in n8n runtime.
