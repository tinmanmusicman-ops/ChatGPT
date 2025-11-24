#!/usr/bin/env python3
"""
poll_gmail_to_sheet_advanced.py (clean-text edition, corrected)
- Reads config.json
- Appends only [Timestamp, Message Text]
- Cleans text: strips HTML, scripts, styles, links, footers, boilerplate, etc.
- Logs every matching message with no deduplication, so duplicates may appear if they still match the search.
- Optional mark-as-read or mark-thread-as-read
- Properly formatted (no syntax error)
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
from pathlib import Path
from typing import Iterable, List, Tuple

import gspread
import pytz

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR.parent / "bot-assets" / "config.json"
SHARED_CONFIG_PATH = SCRIPT_DIR.parent.parent / "shared" / "Global.json"
LOG_FILE = SCRIPT_DIR / "gmail_to_sheets.log"

# ------------ Logging ------------
def setup_logger():
    logger = logging.getLogger("gmail_to_sheets")
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
def load_shared_defaults() -> dict:
    data = {}
    if SHARED_CONFIG_PATH.exists():
        try:
            with SHARED_CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            pass
    env_user = os.getenv("GMAIL_USER")
    env_password = os.getenv("GMAIL_APP_PASSWORD")
    if env_user:
        data.setdefault("gmail_user", env_user)
    if env_password:
        data.setdefault("gmail_app_password", env_password)
    return data


def normalize_credentials(cfg: dict) -> None:
    if not cfg.get("user"):
        if cfg.get("gmail_user"):
            cfg["user"] = cfg["gmail_user"]
        elif cfg.get("email_user"):
            cfg["user"] = cfg["email_user"]
    if not cfg.get("app_password"):
        if cfg.get("gmail_app_password"):
            cfg["app_password"] = cfg["gmail_app_password"]
        elif cfg.get("email_password"):
            cfg["app_password"] = cfg["email_password"]


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    shared = load_shared_defaults()
    for key, value in shared.items():
        cfg.setdefault(key, value)

    normalize_credentials(cfg)

    required = ["user", "app_password", "spreadsheet_id", "worksheet_name", "service_account_json"]
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise KeyError(f"Missing required config keys: {missing}")

    cfg.setdefault("subject_term", "")
    cfg.setdefault("unseen_only", True)
    cfg.setdefault("max_per_run", 25)
    cfg.setdefault("mark_read", True)
    cfg.setdefault("mark_read_thread", True)
    cfg.setdefault("timezone", "America/Los_Angeles")
    return cfg


def resolve_service_account_path(cfg: dict) -> Path:
    sa_value = cfg["service_account_json"]
    sa_path = Path(sa_value)
    if not sa_path.is_absolute():
        sa_path = (SCRIPT_DIR.parent / sa_value).resolve()
    if not sa_path.exists():
        shared_candidate = SCRIPT_DIR.parent.parent / "shared" / sa_path.name
        if shared_candidate.exists():
            sa_path = shared_candidate
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account file not found: {sa_value}")
    return sa_path


def body_contains_sc_marker(text: str) -> bool:
    if not text:
        return False
    return text.startswith("SC") or "\nSC" in text or "\r\nSC" in text

# helper that strips the SC marker before logging rows
def strip_sc_marker(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"(?m)^\s*SC\s+", "", text, count=1)
    cleaned = re.sub(r"(?m)\r?\nSC\s+", "\n", cleaned)
    return cleaned


# ------------ IMAP ------------
def open_imap(user: str, app_password: str, readonly: bool) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(user, app_password)
    typ, _ = imap.select("INBOX", readonly=readonly)
    if typ != "OK":
        raise RuntimeError("Unable to select INBOX")
    return imap


def search_uids(imap: imaplib.IMAP4_SSL, unseen_only: bool, subject_term: str) -> List[bytes]:
    parts = []
    if unseen_only:
        parts.append("UNSEEN")
    if subject_term:
        parts += ["SUBJECT", f'"{subject_term}"']
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


# ------------ Cleaners ------------
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
BOILERPLATE_PHRASES = [
    # (kept for backwards-compat but superseded by regex patterns below)
    "HELP CENTER", "HELP FORUM",
    "This email was sent to you because you indicated that you'd like to receive email notifications for text messages",
    "update your email notification settings",
    "Google LLC", "Amphitheatre Pkwy", "Mountain View CA",
    "YOUR ACCOUNT"
]

# Regex boilerplate patterns (more flexible than exact phrases)
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
        # Exact phrase check
        if any(phrase.upper() in up.upper() for phrase in BOILERPLATE_PHRASES):
            continue
        # Regex patterns
        if any(p.search(up) for p in BOILERPLATE_PATTERNS):
            continue
        kept.append(ln)
    # Remove leading/trailing blank lines
    text = "\n".join(kept)
    text = re.sub(r"^(?:\s*\n)+", "", text)
    text = re.sub(r"(?:\s*\n)+$", "", text)
    return text.split("\n")

def _post_filters(text: str) -> str:
    text = RE_ANGLE_URL.sub(" ", text)
    # Truncate everything after the first detected footer marker
    text = truncate_at_footer(text)
    lines = text.split("\n")
    lines = _drop_boilerplate_lines(lines)
    text = "\n".join(lines)
    # Clean dangling 'such' fragments again just in case
    text = re.sub(r"\bIf you don\'t.*$", "", text, flags=re.I)
    text = re.sub(r"\bsuch\s*\.$", "", text)
    return text

    text = RE_ANGLE_URL.sub(" ", text)
    lines = text.split("\n")
    kept = []
    for ln in lines:
        up = ln.upper()
        if any(phrase.upper() in up for phrase in BOILERPLATE_PHRASES):
            continue
        kept.append(ln)
    return "\n".join(kept)


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

    # Drop boilerplate
    filtered = _drop_boilerplate_lines(cleaned_lines)

    text = "\n".join(filtered)
    text = text.translate({ord(c): None for c in ZW_CHARS})
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = "\n".join([ln.strip() for ln in text.split("\n")])
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Final polish: remove obvious dangling fragments
    text = re.sub(r"\b(such\s*\.)$", "", text)
    text = re.sub(r"\bIf you don\'t.*$", "", text, flags=re.I)
    return text.strip()


def extract_text_from_msg(msg: email.message.Message) -> str:
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
        ws.append_row(["Timestamp", "Message Text"], value_input_option="USER_ENTERED")


# ------------ Time ------------
def now_local_iso(tz_name: str) -> str:
    tz = pytz.timezone(tz_name)
    # Include full weekday name before the date
    return datetime.now(tz).strftime("%A %Y-%m-%d %H:%M:%S")


# ------------ Main ------------
def main():
    cfg = load_config(CONFIG_FILE)
    user = cfg["user"]
    app_password = cfg["app_password"]
    spreadsheet_id = cfg["spreadsheet_id"]
    worksheet_name = cfg["worksheet_name"]
    service_account_json = str(resolve_service_account_path(cfg))
    subject_term = cfg.get("subject_term", "")
    unseen_only = bool(cfg.get("unseen_only", True))
    max_per_run = int(cfg.get("max_per_run", 25))
    mark_read = bool(cfg.get("mark_read", False))
    mark_read_thread = bool(cfg.get("mark_read_thread", False))
    tz_name = cfg.get("timezone", "America/Los_Angeles")

    log.info("Starting poller (max_per_run=%s, unseen_only=%s, mark_read=%s, thread=%s)",
             max_per_run, unseen_only, mark_read, mark_read_thread)

    imap = open_imap(user, app_password, readonly=not (mark_read or mark_read_thread))
    try:
        uids = search_uids(imap, unseen_only, subject_term)
        if not uids:
            log.info("No matching messages found.")
            return

        sh, out_ws = open_sheet(service_account_json, spreadsheet_id, worksheet_name)
        ensure_header(out_ws)
        todo = uids[:max_per_run]
        log.info("Processing %d new message(s).", len(todo))

        rows: List[Tuple[str, str]] = []
        mark_list: List[bytes] = []

        ts = now_local_iso(tz_name)

        for uid in todo:
            msg = fetch_rfc822(imap, uid)
            text = extract_text_from_msg(msg)
            if not body_contains_sc_marker(text):
                uid_str = uid.decode() if isinstance(uid, bytes) else uid
                log.info(
                    "Skipping UID %s because body does not contain '\\r\\nSC' marker.",
                    uid_str,
                )
                continue
            text = strip_sc_marker(text)
            text = re.sub(r"\s+", " ", text).strip()
            rows.append((ts, text))

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
