#!/usr/bin/env python3
"""Scan Gmail for ACNN subjects and record requests for manual handling."""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
import sys
from contextlib import suppress
from datetime import datetime, timezone
from email.header import decode_header, make_header
from pathlib import Path
from typing import Dict, List

AC_PATTERN = re.compile(r"^AC(\d{1,2})$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Capture ACNN email requests.")
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=script_dir / "config.json",
        help="Path to the config file (default: config.json next to this script).",
    )
    return parser.parse_args()


def load_config(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def decode_subject(raw_subject: str) -> str:
    try:
        decoded = str(make_header(decode_header(raw_subject)))
        return decoded.strip()
    except Exception:
        return raw_subject.strip()


def log_request(log_path: Path, entry: Dict) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = json.dumps({"timestamp": timestamp, **entry})
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    user = cfg.get("gmail_user") or cfg.get("user")
    password = cfg.get("gmail_app_password") or cfg.get("app_password")
    if not user or not password:
        print("Missing gmail_user/app_password in config", file=sys.stderr)
        sys.exit(1)

    only_unseen = bool(cfg.get("gmail_only_unseen", True))
    folder = cfg.get("gmail_folder", "INBOX")
    test_mode = bool(cfg.get("TestFlag", False))
    log_path = Path(__file__).resolve().parent / "ac_email_requests.log"

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(user, password)
        mail.select(folder)
        search_terms: List[str] = []
        if only_unseen:
            search_terms.append("UNSEEN")
        search_terms.append('SUBJECT "AC"')
        status, data = mail.search(None, *search_terms)
        if status != "OK":
            print(f"Search failed: {status}", file=sys.stderr)
            return

        ids = data[0].split()
        for uid in ids:
            status, msg_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID)])")
            if status != "OK" or not msg_data:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            raw_subject = msg.get("Subject", "")
            subject = decode_subject(raw_subject)
            match = AC_PATTERN.match(subject)
            if not match:
                continue
            code = int(match.group(1))
            if not (1 <= code <= 21):
                continue
            entry = {
                "subject": subject,
                "code": code,
                "message_id": msg.get("Message-ID", ""),
                "folder": folder,
            }
            print(f"AC request captured: subject='{subject}' code={code}")
            log_request(log_path, entry)
            if test_mode:
                mail.store(uid, "-FLAGS", "(\\Seen)")
    finally:
        with suppress(Exception):
            mail.close()
        with suppress(Exception):
            mail.logout()


if __name__ == "__main__":
    main()
