import imaplib, email, json, re
from typing import List, Optional, Tuple

IMAP_HOST = "imap.gmail.com"

def open_mailbox(imap: imaplib.IMAP4_SSL, mailbox: str, readonly: bool = False) -> None:
    typ, _ = imap.select(mailbox, readonly=readonly)
    if typ != "OK":
        raise RuntimeError(f"Could not select folder {mailbox}")

def _uid_search(imap: imaplib.IMAP4_SSL, *args) -> List[bytes]:
    typ, data = imap.uid("SEARCH", *args)
    return data[0].split() if typ == "OK" and data and data[0] else []

def search_unseen_uids(imap: imaplib.IMAP4_SSL, subject_term: str, include_all_mail: bool = True) -> Tuple[List[bytes], str]:
    """
    Return (UIDs, selected_mailbox) for UNSEEN messages matching subject_term.
    Prefers Gmail RAW (with is:unread), falls back to IMAP UID SEARCH.
    Optionally checks [Gmail]/All Mail if INBOX is empty.
    Keeps the mailbox selected that produced the results so subsequent FETCH/STORE work.
    """
    # 1) Try INBOX first
    open_mailbox(imap, "INBOX", readonly=True)
    selected = "INBOX"

    # Gmail RAW with is:unread
    forced_query = f'subject:{subject_term} is:unread'
    uids = _uid_search(imap, "X-GM-RAW", f'"{forced_query}"')
    if not uids:
        # IMAP fallback: partial subject + UNSEEN (no quotes -> partial match)
        uids = _uid_search(imap, None, f"(UNSEEN SUBJECT {subject_term})")

    # 2) Optional All Mail fallback if nothing found in INBOX
    if not uids and include_all_mail:
        try:
            open_mailbox(imap, '"[Gmail]/All Mail"', readonly=True)
            selected = "[Gmail]/All Mail"
            uids = _uid_search(imap, "X-GM-RAW", f'"{forced_query}"')
            if not uids:
                uids = _uid_search(imap, None, f"(UNSEEN SUBJECT {subject_term})")
        except imaplib.IMAP4.error:
            # Keep selected as INBOX if All Mail isn't available
            selected = "INBOX"

    return uids, selected

def fetch_headers_peek(imap: imaplib.IMAP4_SSL, uid: bytes) -> Tuple[str, str, Optional[str], str]:
    """
    Returns (subject, from_, message_id, date_header). Uses BODY.PEEK to avoid flipping \Seen.
    """
    typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID DATE)])")
    if typ != "OK" or not data or not data[0]:
        return "", "", None, ""
    msg = email.message_from_bytes(data[0][1])
    subject = (msg.get("Subject") or "").strip()
    sender = (msg.get("From") or "").strip()
    message_id = (msg.get("Message-ID") or "").strip() or None
    date_header = (msg.get("Date") or "").strip()
    return subject, sender, message_id, date_header

def fetch_gm_msgid(imap: imaplib.IMAP4_SSL, uid: bytes) -> Optional[str]:
    """
    Fetch Gmail's stable X-GM-MSGID for UID; parse it from the FETCH response.
    This ID is stable across labels and the best key for dedupe.
    """
    typ, data = imap.uid("FETCH", uid, "(X-GM-MSGID)")
    if typ != "OK" or not data or not data[0]:
        return None
    part = data[0][0] if isinstance(data[0], tuple) else data[0]
    if isinstance(part, bytes):
        part = part.decode("utf-8", "ignore")
    m = re.search(r"X-GM-MSGID\s+(\d+)", part)
    return m.group(1) if m else None

def mark_seen_by_uid(imap: imaplib.IMAP4_SSL, uid: bytes) -> None:
    imap.uid("STORE", uid, "+FLAGS.SILENT", r"(\Seen)")

class DedupeCache:
    """
    Stores processed IDs (gm_msgid or message-id) in a JSON file to avoid re-processing.
    """
    def __init__(self, path: str = "processed_ids.json"):
        self.path = path
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = set(json.load(f))
        except Exception:
            self.data = set()

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(sorted(self.data), f, indent=2)

    def seen(self, ident: str) -> bool:
        return ident in self.data

    def add(self, ident: str) -> None:
        self.data.add(ident)
        self._save()

def stable_identity(imap: imaplib.IMAP4_SSL, uid: bytes, message_id_hdr: Optional[str]) -> Optional[str]:
    gm = fetch_gm_msgid(imap, uid)
    return gm or message_id_hdr
