#!/usr/bin/env python3
"""Pull IRSFax emails and forward attachments to an online fax provider."""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import logging
import mimetypes
import os
import re
import smtplib
import sys
import tempfile
from contextlib import suppress
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List, Optional

import gspread
import pytz
from gspread.exceptions import WorksheetNotFound

SHARED_CONFIG_PATH = Path(__file__).resolve().parents[2] / "shared" / "Global.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fax IRS emails found in Gmail.")
    parser.add_argument(
        "--config",
        "-c",
        help="Path to the JSON config file. Defaults to Indeed/config.json or fax_config.json.",
    )
    return parser.parse_args()


def resolve_config_path(explicit: Optional[str] = None) -> Path:
    if explicit:
        explicit_path = Path(explicit)
        if explicit_path.exists():
            return explicit_path
        raise FileNotFoundError(f"Config path was provided but does not exist: {explicit}")

    base = Path(__file__).resolve().parent
    candidates = [
        base / ".." / "bot-assets" / "config.json",
        base / "bot-assets" / "config.json",
    ]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "No config file found. Please pass --config or create Fax/bot-assets/config.json."
    )

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def resolve_service_account_path(cfg: dict) -> Path:
    sa_value = cfg.get("service_account_json")
    if not sa_value:
        raise KeyError("Missing service_account_json in config")
    sa_path = Path(sa_value)
    if not sa_path.is_absolute():
        candidate = Path(__file__).resolve().parent / sa_path
        shared_candidate = Path(__file__).resolve().parents[1] / "shared" / sa_path.name
        if candidate.exists():
            sa_path = candidate
        elif shared_candidate.exists():
            sa_path = shared_candidate
        else:
            sa_path = candidate
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account file not found: {sa_path}")
    return sa_path


def open_spreadsheet(cfg: dict) -> gspread.Spreadsheet:
    spreadsheet_id = cfg.get("spreadsheet_id")
    if not spreadsheet_id:
        raise KeyError("Missing spreadsheet_id in config")
    sa_path = resolve_service_account_path(cfg)
    client = gspread.service_account(filename=str(sa_path))
    return client.open_by_key(spreadsheet_id)


def ensure_faxes_sheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        ws = spreadsheet.worksheet(title)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=6)
    headers = ["Timestamp", "Subject", "Phone", "Gateway", "Attachments", "Status", "Requests"]
    existing = ws.row_values(1)
    if existing != headers:
        ws.update("A1:G1", [headers], value_input_option="USER_ENTERED")
    return ws


def now_local_iso(tz_name: str) -> str:
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime("%A %b %d %Y %I:%M %p")


def log_fax_transaction(
    cfg: dict, subject: str, phone: str, attachments: Iterable[Path], status: str
) -> None:
    spreadsheet = open_spreadsheet(cfg)
    title = cfg.get("fax_sheet_name", "Faxes")
    ws = ensure_faxes_sheet(spreadsheet, title)
    tz_name = cfg.get("timezone", "America/Los_Angeles")
    timestamp = now_local_iso(tz_name)
    attachment_names = ";".join(str(p.name) for p in attachments)
    attachment_key = attachment_names.split(";", 1)[0] if attachment_names else ""
    existing_attachments = ws.col_values(5)[1:]
    requests = (
        sum(
            1
            for value in existing_attachments
            if value and value.split(";", 1)[0] == attachment_key
        )
        + 1
    )
    row = [
        timestamp,
        subject,
        phone,
        cfg["fax_gateway_address"],
        attachment_names,
        status,
        requests,
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


def needs_imap_rw(cfg: dict) -> bool:
    return bool(
        cfg.get("mark_read")
        or cfg.get("mark_read_thread")
        or cfg.get("move_processed", True)
    )


def ensure_mailbox_exists(imap: imaplib.IMAP4_SSL, mailbox: str) -> None:
    if not mailbox:
        return
    with suppress(Exception):
        imap.create(mailbox)


def move_email_to_folder(imap: imaplib.IMAP4_SSL, uid: bytes, folder: str) -> None:
    if not folder:
        return
    ensure_mailbox_exists(imap, folder)
    typ, _ = imap.uid("COPY", uid, folder)
    if typ != "OK":
        logger.warning("Failed to copy UID %s to folder %s", uid.decode(), folder)
        return
    imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)")
    with suppress(Exception):
        imap.expunge()


def load_shared_defaults() -> dict:
    data: dict = {}
    if SHARED_CONFIG_PATH.exists():
        try:
            with SHARED_CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            pass
    env_user = os.getenv("GMAIL_USER")
    env_pass = os.getenv("GMAIL_APP_PASSWORD")
    if env_user:
        data.setdefault("gmail_user", env_user)
    if env_pass:
        data.setdefault("gmail_app_password", env_pass)
    return data


def normalize_credentials(cfg: dict) -> None:
    if not cfg.get("email_user"):
        if cfg.get("gmail_user"):
            cfg["email_user"] = cfg["gmail_user"]
        elif cfg.get("user"):
            cfg["email_user"] = cfg["user"]
    if not cfg.get("email_password"):
        if cfg.get("gmail_app_password"):
            cfg["email_password"] = cfg["gmail_app_password"]
        elif cfg.get("app_password"):
            cfg["email_password"] = cfg["app_password"]


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    shared = load_shared_defaults()
    for key, value in shared.items():
        cfg.setdefault(key, value)

    required = ["email_user", "email_password", "fax_gateway_address"]
    normalize_credentials(cfg)
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise KeyError(f"Missing required config keys: {missing}")
    shared = load_shared_defaults()
    for key, value in shared.items():
        cfg.setdefault(key, value)
    return cfg


def open_imap(cfg: dict) -> imaplib.IMAP4_SSL:
    host = cfg.get("imap_host", "imap.gmail.com")
    port = cfg.get("imap_port", 993)
    mailbox = cfg.get("mailbox", "INBOX")
    imap = imaplib.IMAP4_SSL(host, port)
    imap.login(cfg["email_user"], cfg["email_password"])
    readonly = not needs_imap_rw(cfg)
    typ, _ = imap.select(mailbox, readonly=readonly)
    if typ != "OK":
        raise RuntimeError(f"Failed to select mailbox {mailbox}")
    return imap


def search_for_irfax(imap: imaplib.IMAP4_SSL, keyword: str, unseen_only: bool) -> List[bytes]:
    terms: List[str] = []
    if unseen_only:
        terms.append("UNSEEN")
    terms += ["SUBJECT", f'"{keyword}"']
    typ, data = imap.uid("SEARCH", None, *terms)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def fetch_message(imap: imaplib.IMAP4_SSL, uid: bytes) -> email.message.Message:
    typ, data = imap.uid("FETCH", uid, "(RFC822)")
    if typ != "OK" or not data or not data[0]:
        raise RuntimeError(f"Failed to fetch UID {uid.decode()}")
    raw = data[0][1]
    return email.message_from_bytes(raw)


def save_attachments(msg: email.message.Message, base_dir: Path) -> List[Path]:
    saved: List[Path] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        dest = base_dir / filename
        counter = 1
        while dest.exists():
            dest = base_dir / f"{dest.stem}_{counter}{dest.suffix}"
            counter += 1
        with open(dest, "wb") as fh:
            fh.write(payload)
        saved.append(dest)
    return saved


def extract_phone(subject: str, pattern: str) -> Optional[str]:
    if not subject:
        return None
    match = re.search(pattern, subject)
    if not match:
        return None
    return match.group(0)


def send_email_fax(cfg: dict, attachments: Iterable[Path], phone: str, subject: str) -> None:
    gateway = cfg["fax_gateway_address"]
    email_from = cfg.get("fax_from", cfg["email_user"])
    template = cfg.get("fax_gateway_subject_template", "Fax to {phone}: {subject}")
    email_subject = template.format(phone=phone, subject=subject or "IRSFax")
    body = cfg.get(
        "fax_gateway_body", "Please fax the attached documents. This message is automated."
    )

    message = EmailMessage()
    message["From"] = email_from
    message["To"] = gateway
    message["Subject"] = email_subject
    message.set_content(body)

    for attachment in attachments:
        content_type, encoding = mimetypes.guess_type(attachment.name)
        maintype, subtype = (
            content_type.split("/", 1) if content_type else ("application", "octet-stream")
        )
        with open(attachment, "rb") as fh:
            message.add_attachment(
                fh.read(),
                maintype=maintype,
                subtype=subtype,
                filename=attachment.name,
            )

    smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
    smtp_port = int(cfg.get("smtp_port", 587))
    use_starttls = bool(cfg.get("smtp_starttls", True))
    timeout_seconds = int(cfg.get("smtp_timeout_seconds", 60))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds) as smtp:
        if use_starttls:
            smtp.starttls()
        smtp.login(cfg["email_user"], cfg["email_password"])
        smtp.send_message(message)


def main():
    args = parse_args()
    config_path = resolve_config_path(args.config)
    logger.info("Loading configuration from %s", config_path)
    cfg = load_config(config_path)

    keyword = cfg.get("fax_subject_keyword", "IRSFax")
    unseen_only = bool(cfg.get("gmail_only_unseen", True))
    cfg["mark_read"] = bool(cfg.get("mark_read", False))
    cfg["mark_read_thread"] = bool(cfg.get("mark_read_thread", False))
    cfg["move_processed"] = bool(cfg.get("move_processed", True))
    test_mode = bool(cfg.get("TestFlag"))
    if test_mode:
        cfg["mark_read"] = False
        cfg["mark_read_thread"] = False
        cfg["move_processed"] = False

    imap = open_imap(cfg)
    try:
        uids = search_for_irfax(imap, keyword, unseen_only)
        if not uids:
            logger.info("No IRSFax messages found.")
            return
        latest_uid = uids[-1]
        msg = fetch_message(imap, latest_uid)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            attachments = save_attachments(msg, tmpdir_path)
            if not attachments:
                logger.info("IRSFax email has no attachments to fax.")
                return
            subject = msg.get("Subject", "")
            phone_pattern = cfg.get("fax_subject_pattern", r"\b\d{3}-\d{3}-\d{4}\b")
            phone = extract_phone(subject, phone_pattern)
            if not phone:
                logger.warning(
                    "Could not find fax number in subject; skipping message: %s", subject
                )
                log_fax_transaction(
                    cfg, subject, "", attachments, "skipped - missing phone"
                )
                return
            status = "sent"
            try:
                send_email_fax(cfg, attachments, phone, subject)
                status = "sent"
            except Exception as exc:
                status = f"error: {exc}"
                log_fax_transaction(cfg, subject, phone, attachments, status)
                raise
            else:
                log_fax_transaction(cfg, subject, phone, attachments, status)
                if cfg.get("move_processed", True):
                    move_email_to_folder(
                        imap, latest_uid, cfg.get("processed_folder", "Faxes")
                    )
                logger.info(
                    "Fax dispatched to %s via gateway %s", phone, cfg["fax_gateway_address"]
                )
    finally:
        with suppress(Exception):
            imap.logout()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Failed to fax IRS email: %s", exc)
        sys.exit(1)
