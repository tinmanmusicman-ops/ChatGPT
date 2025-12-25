from __future__ import annotations

import imaplib
import json
import logging
import smtplib
import ssl
import sys
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.mime.text import MIMEText
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "bot-assets" / "config.json"

TAG_KEYWORD = "FORWARDED_CRAIGSLIST"
UNMATCHED_FOLDER = "_Unread"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("yahoo_forwarder")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


def _mask_email(value: str) -> str:
    text = (value or "").strip()
    if "@" not in text:
        return "***"
    local, domain = text.split("@", 1)
    if not local:
        return f"***@{domain}"
    prefix = local[:2]
    return f"{prefix}***@{domain}"


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                out.append(part.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out).strip()


def _normalize_flag(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "y", "on")


def _all_header_text(msg: Message) -> str:
    chunks: list[str] = []
    for key, value in msg.items():
        if not key:
            continue
        chunks.append(f"{key}: {value}")
    return "\n".join(chunks).lower()


def _compile_matchers(rule: dict) -> list[str]:
    match = rule.get("match") if isinstance(rule, dict) else None
    match_list = []
    if isinstance(match, list):
        match_list = match
    elif isinstance(match, str):
        match_list = [match]
    elif isinstance(match, dict):
        for k in ("from_contains", "header_contains", "contains", "any"):
            v = match.get(k)
            if isinstance(v, list):
                match_list.extend(v)
            elif isinstance(v, str) and v.strip():
                match_list.append(v)
    elif rule.get("craigslist_filter"):
        match_list = [rule.get("craigslist_filter")]

    out = []
    for item in match_list:
        text = str(item or "").strip().lower()
        if text:
            out.append(text)
    return out


def _get_forward_rules(cfg: dict) -> list[dict]:
    yahoo = cfg.get("yahoo") or {}
    rules = yahoo.get("forward_rules") or yahoo.get("forwarders") or yahoo.get("rules") or []
    out: list[dict] = []
    if isinstance(rules, list):
        for entry in rules:
            if isinstance(entry, dict):
                out.append(entry)

    # Backward-compatible default rule.
    if not out:
        out.append(
            {
                "name": "Craigslist",
                "match": [str(yahoo.get("craigslist_filter") or "craigslist"), "craigslist.org"],
                "forward_to": "",
                "processed_folder": str(yahoo.get("processed_folder") or "CL"),
            }
        )
    return out


def _select_forward_rule(msg: Message, rules: list[dict]) -> dict | None:
    from_text = str(msg.get("From", "") or "").lower()
    header_text = _all_header_text(msg)
    for rule in rules:
        patterns = _compile_matchers(rule)
        if not patterns:
            continue
        for pat in patterns:
            if pat in from_text or pat in header_text:
                return rule
    return None


def load_config() -> dict:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    yahoo = payload.get("yahoo") or {}

    required_yahoo = ("imap_server", "imap_port", "email", "app_password")
    missing = []
    for key in required_yahoo:
        if key not in yahoo:
            missing.append(f"yahoo.{key}")
    if missing:
        raise RuntimeError(f"Missing required config keys: {', '.join(missing)}")

    return payload


def _imap_uid(imap: imaplib.IMAP4_SSL, logger: logging.Logger, cmd: str, *args: str | bytes) -> tuple[str, list]:
    safe_args: list[str] = []
    for arg in args:
        if isinstance(arg, bytes):
            safe_args.append(arg.decode(errors="ignore"))
        else:
            safe_args.append(str(arg))
    logger.debug("IMAP UID %s %s", cmd, " ".join(safe_args))
    typ, data = imap.uid(cmd, *args)
    logger.debug("IMAP UID %s => %s (%s item(s))", cmd, typ, 0 if data is None else len(data))
    return typ, data


def connect_yahoo_imap(cfg: dict) -> imaplib.IMAP4_SSL:
    yahoo = cfg["yahoo"]
    server = str(yahoo["imap_server"])
    port = int(yahoo["imap_port"])
    client = imaplib.IMAP4_SSL(server, port)
    client.login(str(yahoo["email"]), str(yahoo["app_password"]))
    return client


def connect_yahoo_smtp(cfg: dict, logger: logging.Logger) -> smtplib.SMTP:
    yahoo = cfg["yahoo"]
    server = str(yahoo.get("smtp_server") or "smtp.mail.yahoo.com")
    email_addr = str(yahoo.get("email") or "")
    app_password = str(yahoo.get("app_password") or "")
    if not email_addr or not app_password:
        raise RuntimeError("Missing Yahoo credentials in config.json (yahoo.email / yahoo.app_password).")

    preferred_port = int(yahoo.get("smtp_port") or 587)
    port_candidates = [preferred_port]
    # Yahoo commonly supports STARTTLS on 587 and implicit TLS on 465.
    for fallback in (587, 465):
        if fallback not in port_candidates:
            port_candidates.append(fallback)

    last_exc: Exception | None = None
    for port in port_candidates:
        smtp: smtplib.SMTP | None = None
        try:
            logger.debug("SMTP connect attempt: %s:%s", server, port)
            if port == 465:
                smtp = smtplib.SMTP_SSL(
                    server, port, timeout=30, context=ssl.create_default_context()
                )
                smtp.ehlo()
            else:
                smtp = smtplib.SMTP(server, port, timeout=30)
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(email_addr, app_password)
            logger.debug("SMTP authenticated as %s via %s:%s", _mask_email(email_addr), server, port)
            return smtp
        except (smtplib.SMTPException, OSError) as exc:
            last_exc = exc
            logger.warning("Yahoo SMTP connect failed on %s:%s (%s)", server, port, exc)
            try:
                if smtp is not None:
                    smtp.quit()
            except Exception:
                pass

    raise RuntimeError(f"Unable to connect to Yahoo SMTP ({server}); last error: {last_exc}")


def is_craigslist_message(msg: Message, craigslist_filter: str) -> bool:
    filter_text = (craigslist_filter or "craigslist").strip().lower()
    from_header = str(msg.get("From", "") or "")
    if filter_text and filter_text in from_header.lower():
        return True
    for key, value in msg.items():
        if not key:
            continue
        if "craigslist.org" in str(value or "").lower():
            return True
    return False


def extract_plain_text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = str(part.get_content_type() or "").lower()
            disposition = str(part.get("Content-Disposition", "") or "").lower()
            if content_type != "text/plain":
                continue
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except LookupError:
                return payload.decode("utf-8", errors="replace")
    payload = msg.get_payload(decode=True)
    if isinstance(payload, (bytes, bytearray)):
        charset = msg.get_content_charset() or "utf-8"
        try:
            return bytes(payload).decode(charset, errors="replace")
        except LookupError:
            return bytes(payload).decode("utf-8", errors="replace")
    return str(payload or "")


def build_forward_body(msg: Message, body_text: str, *, rule_name: str) -> str:
    sender = str(msg.get("From", "") or "").strip()
    subject = _decode_mime_header(str(msg.get("Subject", "") or "").strip())
    date = str(msg.get("Date", "") or "").strip()
    label = (rule_name or "message").strip()
    return (
        f"Forwarded {label} message\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Date: {date}\n"
        "\n"
        "---- Original Body (plain text preferred) ----\n"
        f"{body_text}\n"
    )


def forward_email_to_gmail(
    smtp: smtplib.SMTP, cfg: dict, msg: Message, body_text: str, *, to_addr: str, rule_name: str
) -> None:
    yahoo = cfg["yahoo"]
    if not to_addr:
        raise RuntimeError("Missing destination forwarding address (to_addr).")
    from_addr = str(yahoo.get("email") or "").strip()
    if not from_addr:
        raise RuntimeError("Missing Yahoo sender address in config.json (yahoo.email).")
    original_subject = _decode_mime_header(str(msg.get("Subject", "") or "").strip())
    default_subject_label = (rule_name or "message").strip()
    fwd_subject = f"FWD: {original_subject}" if original_subject else f"FWD: {default_subject_label} message"

    forwarded = MIMEText(build_forward_body(msg, body_text, rule_name=rule_name), _charset="utf-8")
    forwarded["To"] = to_addr
    forwarded["From"] = from_addr
    forwarded["Subject"] = fwd_subject
    forwarded["Reply-To"] = from_addr

    rejected = smtp.sendmail(from_addr, [to_addr], forwarded.as_string())
    if rejected:
        raise RuntimeError(f"SMTP refused recipients: {rejected}")


def forward_email_to_gmail_with_retry(
    cfg: dict, msg: Message, body_text: str, *, to_addr: str, rule_name: str, logger: logging.Logger
) -> None:
    """
    Uses Yahoo SMTP to send a forward to the configured Gmail destination.
    Retries once on transient SMTP disconnects.
    """
    last_exc: Exception | None = None
    for attempt in (1, 2):
        smtp: smtplib.SMTP | None = None
        try:
            smtp = connect_yahoo_smtp(cfg, logger)
            try:
                smtp.noop()
            except smtplib.SMTPException as exc:
                logger.debug("SMTP NOOP failed (continuing): %s", exc)
            logger.info(
                "Forward attempt %s/2 (from=%s to=%s subject=%r)",
                attempt,
                _mask_email(str(cfg.get("yahoo", {}).get("email") or "")),
                _mask_email(to_addr),
                _decode_mime_header(str(msg.get("Subject", "") or "")),
            )
            forward_email_to_gmail(smtp, cfg, msg, body_text, to_addr=to_addr, rule_name=rule_name)
            return
        except smtplib.SMTPServerDisconnected as exc:
            last_exc = exc
            logger.warning("SMTP disconnected while sending (attempt %s/2): %s", attempt, exc)
        except smtplib.SMTPException as exc:
            last_exc = exc
            # For protocol-level errors, retry once; for consistent failures this will raise after attempt 2.
            logger.warning("SMTP error while sending (attempt %s/2): %s", attempt, exc)
        finally:
            try:
                if smtp is not None:
                    smtp.quit()
            except Exception:
                pass
    if last_exc is not None:
        raise last_exc


def imap_try_tag(imap: imaplib.IMAP4_SSL, uid: bytes, logger: logging.Logger, *, keyword: str = TAG_KEYWORD) -> None:
    # Try to add an IMAP keyword tag. If the server doesn't support keywords, fall back to \\Flagged.
    tag = str(keyword or "").strip()
    if not tag:
        return
    try:
        typ, _ = _imap_uid(imap, logger, "STORE", uid, "+FLAGS", f"({tag})")
        if typ == "OK":
            logger.debug("IMAP tagged uid=%s with %s", uid.decode(errors="ignore"), tag)
            return
    except imaplib.IMAP4.error:
        pass

    try:
        _imap_uid(imap, logger, "STORE", uid, "+FLAGS", "(\\Flagged)")
        logger.info("Yahoo server did not accept keyword tag; applied \\Flagged instead (uid=%s)", uid.decode())
    except imaplib.IMAP4.error:
        logger.info("Yahoo server did not accept any tag flags (uid=%s)", uid.decode())


def imap_mark_seen(imap: imaplib.IMAP4_SSL, uid: bytes, logger: logging.Logger) -> None:
    _imap_uid(imap, logger, "STORE", uid, "+FLAGS", "(\\Seen)")
    logger.debug("IMAP marked uid=%s as \\Seen", uid.decode(errors="ignore"))


def _imap_mailbox_exists(imap: imaplib.IMAP4_SSL, mailbox: str) -> bool:
    try:
        typ, data = imap.list()
    except imaplib.IMAP4.error:
        return False
    if typ != "OK" or not data:
        return False
    needle = f'"{mailbox}"'.lower()
    for line in data:
        if not line:
            continue
        text = line.decode(errors="ignore").lower() if isinstance(line, (bytes, bytearray)) else str(line).lower()
        if needle in text or text.rstrip().endswith(f" {mailbox.lower()}"):
            return True
    return False


def imap_ensure_mailbox(imap: imaplib.IMAP4_SSL, mailbox: str, logger: logging.Logger) -> None:
    name = str(mailbox or "").strip()
    if not name:
        raise RuntimeError("Mailbox name is empty.")
    if _imap_mailbox_exists(imap, name):
        return
    try:
        logger.debug("IMAP CREATE %s", name)
        imap.create(name)
    except imaplib.IMAP4.error as exc:
        logger.warning("Unable to create mailbox %r (%s)", name, exc)


def imap_move_to_mailbox(imap: imaplib.IMAP4_SSL, uid: bytes, mailbox: str, logger: logging.Logger) -> None:
    """
    Move a message out of INBOX into another folder.
    Tries UID MOVE (RFC 6851) first, then falls back to COPY + \\Deleted + EXPUNGE.
    """
    target = str(mailbox or "").strip()
    if not target:
        return
    imap_ensure_mailbox(imap, target, logger)

    try:
        typ, _ = _imap_uid(imap, logger, "MOVE", uid, target)
        if typ == "OK":
            logger.info("IMAP moved uid=%s to mailbox=%r (UID MOVE)", uid.decode(errors="ignore"), target)
            return
    except imaplib.IMAP4.error as exc:
        logger.debug("IMAP UID MOVE not supported/failed (uid=%s, mailbox=%r): %s", uid.decode(errors="ignore"), target, exc)

    typ, _ = _imap_uid(imap, logger, "COPY", uid, target)
    if typ != "OK":
        raise RuntimeError(f"IMAP copy failed for uid={uid!r} to mailbox={target!r}")
    _imap_uid(imap, logger, "STORE", uid, "+FLAGS", "(\\Deleted)")
    try:
        imap.expunge()
    except imaplib.IMAP4.error as exc:
        logger.warning("IMAP EXPUNGE failed after copy+delete (uid=%s, mailbox=%r): %s", uid.decode(errors="ignore"), target, exc)
        return
    logger.info("IMAP moved uid=%s to mailbox=%r (COPY+DELETE)", uid.decode(errors="ignore"), target)


def fetch_message(imap: imaplib.IMAP4_SSL, uid: bytes, logger: logging.Logger) -> Message:
    # Use BODY.PEEK to avoid setting the \\Seen flag just by fetching content.
    typ, data = _imap_uid(imap, logger, "FETCH", uid, "(BODY.PEEK[])")
    if typ != "OK" or not data or not data[0] or not isinstance(data[0], tuple):
        raise RuntimeError(f"Failed to fetch message uid={uid!r}")
    raw = data[0][1] or b""
    logger.debug("IMAP fetched uid=%s bytes=%s", uid.decode(errors="ignore"), len(raw))
    return message_from_bytes(raw)


def _summarize_rules_for_log(rules: list[dict]) -> str:
    parts: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        name = str(rule.get("name") or "ForwardRule").strip()
        forward_to = _mask_email(str(rule.get("forward_to") or ""))
        processed = str(rule.get("processed_folder") or "").strip()
        if processed:
            parts.append(f"{name}=>{forward_to} ({processed})")
        else:
            parts.append(f"{name}=>{forward_to}")
    return ", ".join(parts)


def run() -> int:
    logger = setup_logging()
    cfg = load_config()
    rules = _get_forward_rules(cfg)

    yahoo = cfg.get("yahoo") or {}
    logger.info(
        "Run start (config=%s, yahoo_imap=%s:%s yahoo_user=%s, rules=%s: %s)",
        CONFIG_PATH,
        yahoo.get("imap_server"),
        yahoo.get("imap_port"),
        _mask_email(str(yahoo.get("email") or "")),
        len(rules),
        _summarize_rules_for_log(rules),
    )

    imap = None
    try:
        imap = connect_yahoo_imap(cfg)
        logger.debug("IMAP connected and authenticated.")
        typ, sel = imap.select("INBOX")
        logger.debug("IMAP SELECT INBOX => %s (%s)", typ, sel)
        if typ != "OK":
            raise RuntimeError("Unable to select INBOX")

        typ, data = _imap_uid(imap, logger, "SEARCH", None, "UNSEEN")
        if typ != "OK":
            raise RuntimeError("IMAP search failed")
        if not data or not data[0]:
            logger.info("No UNSEEN messages found.")
            return 0
        uids = (data[0] or b"").split()
        if not uids:
            logger.info("No UNSEEN messages found.")
            return 0

        logger.info("IMAP search UNSEEN returned %s uid(s).", len(uids))
        forwarded_count = 0
        for uid in uids:
            try:
                msg = fetch_message(imap, uid, logger)
                decoded_subject = _decode_mime_header(str(msg.get("Subject", "") or ""))
                sender = str(msg.get("From", "") or "").strip()
                date = str(msg.get("Date", "") or "").strip()
                logger.debug(
                    "UID %s headers: from=%r subject=%r date=%r message-id=%r",
                    uid.decode(errors="ignore"),
                    sender,
                    decoded_subject,
                    date,
                    str(msg.get("Message-ID", "") or "").strip(),
                )

                rule = _select_forward_rule(msg, rules)
                if not rule:
                    logger.info(
                        "UID %s no matching rule; moving to %r (kept UNREAD).",
                        uid.decode(errors="ignore"),
                        UNMATCHED_FOLDER,
                    )
                    try:
                        imap_move_to_mailbox(imap, uid, UNMATCHED_FOLDER, logger)
                    except Exception as exc:
                        logger.warning(
                            "UID %s no matching rule; failed to move to %r (%s) - leaving in INBOX as UNREAD.",
                            uid.decode(errors="ignore"),
                            UNMATCHED_FOLDER,
                            exc,
                        )
                    continue

                body_text = extract_plain_text(msg)
                logger.debug("UID %s body length=%s", uid.decode(errors="ignore"), len(body_text))
                rule_name = str(rule.get("name") or "ForwardRule").strip()
                forward_to = str(rule.get("forward_to") or "").strip()
                if not forward_to:
                    raise RuntimeError(f"Rule {rule_name!r} missing forward_to.")

                logger.info(
                    "UID %s matched rule=%r forward_to=%s",
                    uid.decode(errors="ignore"),
                    rule_name,
                    _mask_email(forward_to),
                )
                forward_email_to_gmail_with_retry(
                    cfg,
                    msg,
                    body_text,
                    to_addr=forward_to,
                    rule_name=rule_name,
                    logger=logger,
                )

                tag_keyword = str(rule.get("tag_keyword") or TAG_KEYWORD).strip()
                imap_try_tag(imap, uid, logger, keyword=tag_keyword)
                imap_mark_seen(imap, uid, logger)
                try:
                    processed_mailbox = str(rule.get("processed_folder") or "CL").strip()
                    imap_move_to_mailbox(imap, uid, processed_mailbox, logger)
                except Exception as exc:
                    logger.warning(
                        "Forwarded uid=%s but failed to move to %r (%s)",
                        uid.decode(errors="ignore"),
                        str(rule.get("processed_folder") or "CL").strip(),
                        exc,
                    )

                logger.info(
                    "Forwarded email uid=%s rule=%r from=%r subject=%r date=%r",
                    uid.decode(),
                    rule_name,
                    sender,
                    decoded_subject,
                    date,
                )
                forwarded_count += 1
            except Exception as exc:
                logger.exception("Failed processing uid=%s (%s)", uid.decode(errors="ignore"), exc)

        return forwarded_count
    finally:
        try:
            if imap is not None:
                imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    run()
