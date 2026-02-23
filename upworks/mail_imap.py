from __future__ import annotations

import imaplib
import re
from email import message_from_bytes, policy
from email.message import EmailMessage


class ImapError(RuntimeError):
    pass


class ImapMailbox:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        mailbox: str,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._mailbox = mailbox
        self._conn: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "ImapMailbox":
        conn: imaplib.IMAP4_SSL | None = None
        try:
            conn = imaplib.IMAP4_SSL(self._host, self._port)
            login_status, _ = conn.login(self._user, self._password)
            if login_status != "OK":
                raise ImapError("IMAP login failed")
            select_status, _ = conn.select(self._mailbox)
            if select_status != "OK":
                raise ImapError(f"Unable to select mailbox '{self._mailbox}'")
            self._conn = conn
            return self
        except ImapError:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
            raise
        except imaplib.IMAP4.error as exc:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
            raise ImapError(f"IMAP connect/login failed ({exc})") from exc
        except Exception as exc:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
            raise ImapError(f"IMAP connection setup failed ({exc})") from exc

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn.logout()
            self._conn = None

    def _connection(self) -> imaplib.IMAP4_SSL:
        if self._conn is None:
            raise ImapError("IMAP connection is not open")
        return self._conn

    def _select_mailbox(self, mailbox: str) -> None:
        conn = self._connection()
        status, _ = conn.select(mailbox)
        if status != "OK":
            raise ImapError(f"Unable to select mailbox '{mailbox}'")

    def search_uids(self, search_criteria: str, max_results: int) -> list[str]:
        conn = self._connection()
        # Gmail supports X-GM-RAW so we can reuse the same query format as n8n.
        try:
            status, data = conn.uid("SEARCH", None, "X-GM-RAW", f'"{search_criteria}"')
        except imaplib.IMAP4.error as exc:
            raise ImapError(f"IMAP SEARCH failed for criteria: {search_criteria} ({exc})") from exc
        if status != "OK":
            raise ImapError(f"IMAP SEARCH failed for criteria: {search_criteria}")
        if not data or not data[0]:
            return []
        uids = data[0].decode("utf-8").strip().split()
        return uids[:max_results]

    def fetch_message(self, uid: str) -> EmailMessage:
        conn = self._connection()
        status, data = conn.uid("FETCH", uid, "(RFC822)")
        if status != "OK" or not data:
            raise ImapError(f"IMAP FETCH failed for uid {uid}")

        raw_email: bytes | None = None
        for part in data:
            if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
                raw_email = part[1]
                break

        if raw_email is None:
            raise ImapError(f"IMAP FETCH returned no RFC822 payload for uid {uid}")

        parsed = message_from_bytes(raw_email, policy=policy.default)
        if not isinstance(parsed, EmailMessage):
            raise ImapError(f"Failed to parse RFC822 payload for uid {uid}")
        return parsed

    def mark_as_read(self, uid: str) -> None:
        conn = self._connection()
        status, _ = conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        if status != "OK":
            raise ImapError(f"IMAP STORE failed when marking uid {uid} as read")

    def ensure_label_exists(self, label_name: str) -> None:
        conn = self._connection()
        status, data = conn.list()
        if status != "OK":
            raise ImapError("IMAP LIST failed while checking labels")

        label_exists = False
        quoted_label = f'"{label_name}"'
        end_pattern = re.compile(rf'"{re.escape(label_name)}"$')
        for row in data or []:
            if not isinstance(row, bytes):
                continue
            text = row.decode("utf-8", errors="ignore")
            if end_pattern.search(text):
                label_exists = True
                break

        if label_exists:
            return

        create_status, _ = conn.create(quoted_label)
        if create_status != "OK":
            raise ImapError(f"IMAP CREATE failed for label '{label_name}'")

    def add_label(self, uid: str, label_name: str) -> None:
        conn = self._connection()
        status, _ = conn.uid("STORE", uid, "+X-GM-LABELS", f'("{label_name}")')
        if status != "OK":
            raise ImapError(f"IMAP add label failed for uid {uid} label '{label_name}'")

    def move_to_label(self, uid: str, label_name: str) -> None:
        conn = self._connection()
        status, _ = conn.uid("MOVE", uid, f'"{label_name}"')
        if status == "OK":
            return

        # Fallback if MOVE is unavailable.
        self.add_label(uid, label_name)
        self.remove_inbox_label(uid)

    def remove_inbox_label(self, uid: str) -> None:
        conn = self._connection()
        current_mailbox = self._mailbox

        # Read Gmail stable message id from INBOX UID context.
        fetch_status, fetch_data = conn.uid("FETCH", uid, "(X-GM-MSGID)")
        if fetch_status != "OK" or not fetch_data:
            raise ImapError(f"IMAP fetch X-GM-MSGID failed for uid {uid}")
        raw_fetch = " ".join(
            part.decode("utf-8", errors="ignore") if isinstance(part, bytes) else str(part)
            for part in fetch_data
        )
        match = re.search(r"X-GM-MSGID\s+(\d+)", raw_fetch)
        if not match:
            raise ImapError(f"Unable to parse X-GM-MSGID for uid {uid}")
        x_gm_msgid = match.group(1)

        # Switch to All Mail, resolve mailbox-specific UID there, remove Inbox label, then switch back.
        self._select_mailbox('"[Gmail]/All Mail"')
        search_status, search_data = conn.uid("SEARCH", None, "X-GM-MSGID", x_gm_msgid)
        if search_status != "OK" or not search_data or not search_data[0]:
            raise ImapError(f"Unable to resolve All Mail UID for X-GM-MSGID {x_gm_msgid}")
        all_mail_uid = search_data[0].decode("utf-8").strip().split()[0]

        status, _ = conn.uid("STORE", all_mail_uid, "-X-GM-LABELS", "(\\Inbox)")
        if status != "OK":
            self._select_mailbox(current_mailbox)
            raise ImapError(f"IMAP remove Inbox label failed for uid {uid}")

        verify_status, verify_data = conn.uid("FETCH", all_mail_uid, "(X-GM-LABELS)")
        if verify_status != "OK":
            self._select_mailbox(current_mailbox)
            raise ImapError(f"IMAP label verification failed for uid {uid}")
        verify_raw = " ".join(
            part.decode("utf-8", errors="ignore") if isinstance(part, bytes) else str(part)
            for part in (verify_data or [])
        )
        if "\\Inbox" in verify_raw or " INBOX" in verify_raw:
            self._select_mailbox(current_mailbox)
            raise ImapError(f"Inbox label still present for uid {uid} after remove operation")

        self._select_mailbox(current_mailbox)
