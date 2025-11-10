Gmail Poller Fix — UNSEEN + UID-safe + Dedupe by Message-ID/X-GM-MSGID
=====================================================================

What this gives you
-------------------
1) Searches unread messages matching a subject term using Gmail RAW (`X-GM-RAW`) with `is:unread`.
2) Falls back to standard IMAP UID search if RAW isn't available.
3) Optionally searches `[Gmail]/All Mail` so category tabs don't hide messages.
4) Reads with BODY.PEEK so it won't flip `\Seen` inadvertently.
5) Marks messages read using UID flags only (no sequence numbers).
6) Prevents re-processing across folders and runs using a local dedupe cache keyed by X-GM-MSGID
   (stable across labels) or, if unavailable, by Message-ID header.

Quick start
-----------
1) Open `search_and_process_example.py`.
2) Set `USER`, `APP_PASSWORD`, and `SUBJECT_TERM` near the top.
3) Run:  python search_and_process_example.py
4) The script prints what it found, processes once, marks as read,
   and writes dedupe fingerprints to `processed_ids.json`.

Integrate into your poller
--------------------------
- Drop `gmail_search_utils.py` into your project.
- Import and use `search_unseen_uids(...)`, `fetch_headers_peek(...)`,
  `mark_seen_by_uid(...)`, and `DedupeCache` in your existing flow.
- Keep all UID operations (SEARCH/FETCH/STORE) in UID mode and avoid mixing sequence numbers.

Notes
-----
- Your diagnostic output shows:
    INBOX: unread matches = 1
    All Mail: multiple matches (some read, some unread)
  That means the subject filter is correct, but you can see duplicates across labels.
  Using X-GM-MSGID for dedupe eliminates duplicates even when the same message appears
  in INBOX and All Mail simultaneously.

Security
--------
- Consider using environment variables or a keyring instead of storing the app password in code.
- You can also modify the example to `getpass.getpass()` to prompt at runtime.
