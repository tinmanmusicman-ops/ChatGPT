#!/usr/bin/env python3
"""
Indeed.py
- Polls Gmail for messages FROM a specific sender (Indeed)
- Appends only [Timestamp, URL(s)] to a Google Sheet tab named "Indeed"
- Cleans text (HTML -> plain text, removes boilerplate, footers, quotes) [for fallback only]
- De-duplicates via a hidden worksheet "_processed_uids_indeed"
- Optional mark-as-read for message or entire thread
- Uses the same config.json and service account as your existing framework
"""

import email
import imaplib
import json
import logging
import os
import re
import sys
import html as ihtml
from datetime import datetime
from email.header import decode_header, make_header
from typing import Iterable, List, Set, Tuple
from pathlib import Path

import gspread
import pytz


CONFIG_FILE = "config.json"
LOG_FILE = "gmail_to_sheets.log"

# Default sender (can be overridden in config.json with key: "from_address")
DEFAULT_FROM_ADDRESS = "donotreply@match.indeed.com"

# Target worksheet/tab for output
TARGET_WORKSHEET = "Indeed"

# Hidden worksheet for de-duplication specific to this script
PROCESSED_SHEET = "_processed_uids_indeed"


# ------------ Logging ------------
def setup_logger():
    base_dir = Path(__file__).resolve().parent
    os.chdir(base_dir)

    logger = logging.getLogger("gmail_to_sheets_indeed")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            if os.path.exists(LOG_FILE + ".1"):
                os.remove(LOG_FILE + ".1")
            os.replace(LOG_FILE, LOG_FILE + ".1")
    except Exception:
        pass
    h = logging.FileHandler(LOG_FILE, encoding="utf-8")
    f = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    h.setFormatter(f)
    logger.addHandler(h)
    s = logging.StreamHandler(sys.stdout)
    s.setFormatter(f)
    logger.addHandler(s)
    return logger


log = setup_logger()


# ------------ Config ------------
def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    required = ["user", "app_password", "spreadsheet_id", "service_account_json"]
    for k in required:
        if not cfg.get(k):
            raise KeyError(f"Missing required config key: '{k}'")

    # Optional keys
    cfg.setdefault("subject_term", "")
    # For TESTING right now, we default unseen_only to False.
    # When you are ready to go live, set this to True (or set in config.json).
    cfg.setdefault("unseen_only", False)  # <-- change to True later if desired
    cfg.setdefault("max_per_run", 50)
    cfg.setdefault("mark_read", False)
    cfg.setdefault("mark_read_thread", False)
    cfg.setdefault("timezone", "America/Los_Angeles")
    cfg.setdefault("from_address", DEFAULT_FROM_ADDRESS)
    return cfg


# ------------ IMAP ------------
def open_imap(user: str, app_password: str, readonly: bool) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(user, app_password)
    typ, _ = imap.select("INBOX", readonly=readonly)
    if typ != "OK":
        raise RuntimeError("Unable to select INBOX")
    return imap


def search_uids(
    imap: imaplib.IMAP4_SSL,
    unseen_only: bool,
    subject_term: str,
    from_address: str,
) -> List[bytes]:
    parts = []
    if unseen_only:
        parts.append("UNSEEN")
    if subject_term:
        parts += ["SUBJECT", f'"{subject_term}"']
    if from_address:
        parts += ["FROM", f'"{from_address}"']
    if not parts:
        parts = ["ALL"]
    log.info("Searching with IMAP terms: %s", " ".join(parts))
    typ, data = imap.uid("SEARCH", None, *parts)
    if typ != "OK" or not data:
        return []
    return data[0].split() if data[0] else []


def fetch_rfc822(imap: imaplib.IMAP4_SSL, uid: bytes) -> email.message.Message:
    if isinstance(uid, bytes):
        uid = uid.decode()
    typ, data = imap.uid("FETCH", uid, "(RFC822)")
    if typ != "OK" or not data or data[0] is None:
        raise RuntimeError(f"FETCH failed for UID {uid}")
    raw = data[0][1]
    return email.message_from_bytes(raw)


def get_thread_id(imap: imaplib.IMAP4_SSL, uid: bytes) -> str:
    if isinstance(uid, bytes):
        uid = uid.decode()
    typ, data = imap.uid("FETCH", uid, "(X-GM-THRID)")
    if typ != "OK" or not data or not data[0]:
        return ""
    tokens = data[0].decode(errors="ignore").split()
    return tokens[-1].rstrip(")") if tokens else ""


def list_uids_in_thread(imap: imaplib.IMAP4_SSL, thrid: str) -> List[bytes]:
    typ, data = imap.uid("SEARCH", None, "X-GM-THRID", thrid)
    if typ != "OK" or not data:
        return []
    return data[0].split() if data[0] else []


def mark_seen(imap: imaplib.IMAP4_SSL, uids: Iterable[bytes]):
    for u in uids:
        if isinstance(u, bytes):
            u = u.decode()
        imap.uid("STORE", u, "+FLAGS", r"(\Seen)")


# ------------ Cleaners (for fallback text parsing) ------------
ZW_CHARS = u"\u200B\u200C\u200D\uFEFF"
RE_SCRIPT_STYLE = re.compile(r"<\s*(script|style)[^>]*>.*?</\s*\1\s*>", re.IGNORECASE | re.DOTALL)
RE_TAG = re.compile(r"<[^>]+>")
RE_BR = re.compile(r"<\s*br\s*/?>", re.IGNORECASE)
RE_P = re.compile(r"</\s*p\s*>", re.IGNORECASE)
RE_QUOTED = re.compile(
    r"(?m)^\s*(On .+ wrote:|> .+|>.+|-----Original Message-----|From: .+|Sent: .+|Subject: .+)\s*$"
)
RE_SIGNATURE = re.compile(r"(?mi)^\s*(--|—)\s*$")
RE_ANGLE_URL = re.compile(r"<\s*https?://[^>]+>")
BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*help\s+center\s*$", re.I),
    re.compile(r"^\s*help\s+forum\s*$", re.I),
    re.compile(r"this email was sent to you because you indicated that you.*receive email notifications for text messages", re.I),
    re.compile(r"if you don\'t want to receive such.*", re.I),
    re.compile(r"update your email notification settings", re.I),
    re.compile(r"google\s+llc", re.I),
    re.compile(r"amphitheatre\s+pkwy", re.I),
    re.compile(r"mountain\s+view\s+ca", re.I),
    re.compile(r"^\s*your\s+account\s*$", re.I),
    re.compile(r"^>+\s*.*$", re.I),
]

BOILERPLATE_START_PATTERNS = [
    re.compile(r"this email was sent to you because you indicated", re.I),
    re.compile(r"if you don\'t want to receive", re.I),
    re.compile(r"help\s+center", re.I),
    re.compile(r"help\s+forum", re.I),
    re.compile(r"update your email notification settings", re.I),
    re.compile(r"google\s+llc", re.I),
    re.compile(r"amphitheatre", re.I),
    re.compile(r"mountain\s+view\s+ca", re.I),
    re.compile(r"your\s+account", re.I),
]


def truncate_at_footer(text: str) -> str:
    earliest = None
    for pat in BOILERPLATE_START_PATTERNS:
        m = pat.search(text)
        if m:
            idx = m.start()
            if earliest is None or idx < earliest:
                earliest = idx
    if earliest is not None:
        return text[:earliest].rstrip()
    return text


def _drop_boilerplate_lines(lines):
    kept = []
    for ln in lines:
        up = ln.strip()
        if not up:
            kept.append(ln)
            continue
        if any(p.search(up) for p in BOILERPLATE_PATTERNS):
            continue
        kept.append(ln)
    text = "\n".join(kept)
    text = re.sub(r"^(?:\s*\n)+", "", text)
    text = re.sub(r"(?:\s*\n)+$", "", text)
    return text.split("\n")


def _post_filters(text: str) -> str:
    text = RE_ANGLE_URL.sub(" ", text)
    text = truncate_at_footer(text)
    lines = text.split("\n")
    lines = _drop_boilerplate_lines(lines)
    text = "\n".join(lines)
    text = re.sub(r"\bIf you don\'t.*$", "", text, flags=re.I)
    text = re.sub(r"\bsuch\s*\.$", "", text)
    return text


def html_to_clean_text(html: str) -> str:
    html = ihtml.unescape(html)
    html = RE_SCRIPT_STYLE.sub(" ", html)
    html = RE_BR.sub("\n", html)
    html = RE_P.sub("\n", html)
    html = RE_ANGLE_URL.sub(" ", html)
    text = RE_TAG.sub(" ", html)
    text = truncate_at_footer(text)

    text = re.sub(r"\r\n", "\n", text)
    lines = text.split("\n")
    cleaned_lines = []
    for ln in lines:
        if RE_QUOTED.search(ln):
            continue
        if RE_SIGNATURE.match(ln):
            break
        cleaned_lines.append(ln)

    filtered = _drop_boilerplate_lines(cleaned_lines)

    text = "\n".join(filtered)
    text = text.translate({ord(c): None for c in ZW_CHARS})
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = "\n".join([ln.strip() for ln in text.split("\n")])
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\b(such\s*\.)$", "", text)
    text = re.sub(r"\bIf you don\'t.*$", "", text, flags=re.I)
    return text.strip()


def extract_text_from_msg(msg: email.message.Message) -> str:
    """Fallback cleaner that returns human-readable text if no URLs were found."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    body = body.replace("\r\n", "\n")
                    body = re.sub(r"[ \t]{2,}", " ", body)
                    body = "\n".join(ln.strip() for ln in body.split("\n"))
                    body = re.sub(r"\n{3,}", "\n\n", body)
                    body = _post_filters(body.strip())
                    return body
                except Exception:
                    continue
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/html" and "attachment" not in disp:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    html = part.get_payload(decode=True).decode(charset, errors="replace")
                    return _post_filters(html_to_clean_text(html))
                except Exception:
                    continue
    else:
        ctype = msg.get_content_type()
        try:
            if ctype == "text/plain":
                charset = msg.get_content_charset() or "utf-8"
                body = msg.get_payload(decode=True).decode(charset, errors="replace")
                body = body.replace("\r\n", "\n")
                body = re.sub(r"[ \t]{2,}", " ", body)
                body = "\n".join(ln.strip() for ln in body.split("\n"))
                body = re.sub(r"\n{3,}", "\n\n", body)
                body = _post_filters(body.strip())
                return body
            elif ctype == "text/html":
                charset = msg.get_content_charset() or "utf-8"
                html = msg.get_payload(decode=True).decode(charset, errors="replace")
                return _post_filters(html_to_clean_text(html))
        except Exception:
            pass

    try:
        subj = str(make_header(decode_header(msg.get("Subject", "") or ""))).strip()
    except Exception:
        subj = msg.get("Subject", "") or ""
    return _post_filters(subj or "(no content)")


# ------------ URL Extraction Helpers ------------
def _extract_urls_from_text(text: str) -> List[str]:
    """Extract raw URLs from visible text."""
    pattern = re.compile(r"https?://[^\s\"'>]+", re.IGNORECASE)
    return pattern.findall(text or "")


def _extract_urls_from_html(html: str) -> List[str]:
    """Extract URLs from href attributes in HTML body and from bare text."""
    href_pat = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.IGNORECASE)
    urls = href_pat.findall(html or "")
    urls += _extract_urls_from_text(html or "")
    return urls


def extract_urls_from_msg(msg: email.message.Message) -> List[str]:
    """Walk the message payload and extract all hyperlink targets.
    Prefers href URLs in HTML, falls back to raw URLs in text/plain.
    Returns a de-duplicated list preserving first-seen order.
    """
    urls: List[str] = []

    def _extend(items: List[str]):
        for u in items:
            if u and u not in urls:
                urls.append(u)

    if msg.is_multipart():
        # Prefer HTML to capture true link targets
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/html" and "attachment" not in disp:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    html = part.get_payload(decode=True).decode(charset, errors="replace")
                    _extend(_extract_urls_from_html(html))
                except Exception:
                    pass
        # Also check text/plain for any naked URLs
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    _extend(_extract_urls_from_text(body))
                except Exception:
                    pass
    else:
        try:
            ctype = msg.get_content_type()
            if ctype == "text/html":
                charset = msg.get_content_charset() or "utf-8"
                html = msg.get_payload(decode=True).decode(charset, errors="replace")
                _extend(_extract_urls_from_html(html))
            elif ctype == "text/plain":
                charset = msg.get_content_charset() or "utf-8"
                body = msg.get_payload(decode=True).decode(charset, errors="replace")
                _extend(_extract_urls_from_text(body))
        except Exception:
            pass

    return urls


# ------------ Sheets helpers ------------
def open_sheet(service_account_json: str, spreadsheet_id: str, worksheet_name: str):
    gc = gspread.service_account(filename=service_account_json)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=2)
    return sh, ws


def ensure_header(ws):
    try:
        values = ws.get_all_values()
    except Exception:
        values = []
    if not values:
        ws.append_row(["Timestamp", "URL(s)"], value_input_option="USER_ENTERED")


def get_or_create_processed_ws(sh):
    try:
        ws = sh.worksheet(PROCESSED_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=PROCESSED_SHEET, rows=1000, cols=1)
    return ws


def load_processed_set(ws) -> Set[str]:
    vals = ws.col_values(1)
    return set(v.strip() for v in vals if v and v.strip().isdigit())


def append_processed(ws, new_uids: Iterable[str]):
    rows = [[u] for u in new_uids]
    if rows:
        ws.append_rows(rows, value_input_option="RAW")


# ------------ Time ------------
def now_local_iso(tz_name: str) -> str:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime("%A %Y-%m-%d %H:%M:%S")


# ------------ Main ------------
def main():
    cfg = load_config(CONFIG_FILE)
    user = cfg["user"]
    app_password = cfg["app_password"]
    spreadsheet_id = cfg["spreadsheet_id"]
    service_account_json = cfg["service_account_json"]

    subject_term = cfg.get("subject_term", "")
    unseen_only = bool(cfg.get("unseen_only", False))  # NOTE: testing default False
    max_per_run = int(cfg.get("max_per_run", 50))
    mark_read = bool(cfg.get("mark_read", False))
    mark_read_thread = bool(cfg.get("mark_read_thread", False))
    tz_name = cfg.get("timezone", "America/Los_Angeles")
    from_address = cfg.get("from_address", DEFAULT_FROM_ADDRESS)

    log.info(
        "Starting Indeed poller (from=%s | max=%s | unseen_only=%s | mark_read=%s | thread=%s)",
        from_address, max_per_run, unseen_only, mark_read, mark_read_thread
    )

    imap = open_imap(user, app_password, readonly=not (mark_read or mark_read_thread))
    try:
        uids = search_uids(imap, unseen_only, subject_term, from_address)
        if not uids:
            log.info("No matching messages found.")
            return

        sh, out_ws = open_sheet(service_account_json, spreadsheet_id, TARGET_WORKSHEET)
        ensure_header(out_ws)
        processed_ws = get_or_create_processed_ws(sh)
        processed = load_processed_set(processed_ws)

        new_uids = [u for u in uids if (u.decode() if isinstance(u, bytes) else u) not in processed]
        if not new_uids:
            log.info("All matching messages already processed.")
            return

        todo = new_uids[:max_per_run]
        log.info("Processing %d new message(s).", len(todo))

        rows: List[Tuple[str, str]] = []
        processed_to_add: List[str] = []
        mark_list: List[bytes] = []

        ts = now_local_iso(tz_name)

        for uid in todo:
            msg = fetch_rfc822(imap, uid)
            urls = extract_urls_from_msg(msg)

            # Fallback to cleaned text only if absolutely no URLs found
            if not urls:
                clean_text = extract_text_from_msg(msg)
                urls = _extract_urls_from_text(clean_text)

            url_text = "\n".join(urls) if urls else "(no links found)"
            rows.append((ts, url_text))

            uid_str = uid.decode() if isinstance(uid, bytes) else uid
            processed_to_add.append(uid_str)

            if mark_read_thread:
                thrid = get_thread_id(imap, uid)
                if thrid:
                    thread_uids = list_uids_in_thread(imap, thrid)
                    mark_list.extend(thread_uids)
                else:
                    mark_list.append(uid)
            elif mark_read:
                mark_list.append(uid)

        if rows:
            out_ws.append_rows(rows, value_input_option="USER_ENTERED")
            log.info("Appended %d row(s).", len(rows))

        append_processed(processed_ws, processed_to_add)
        log.info("Recorded %d UID(s) as processed.", len(processed_to_add))

        if (mark_read or mark_read_thread) and mark_list:
            mark_seen(imap, mark_list)
            log.info("Marked %d message(s) as \\Seen.", len(mark_list))

    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Fatal error: %s", e)
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
