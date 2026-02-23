from __future__ import annotations

import html
import re
from datetime import timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from models import ParsedJobEmail


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
MULTISPACE_PATTERN = re.compile(r"\s+")


def _normalize_whitespace(value: str) -> str:
    return MULTISPACE_PATTERN.sub(" ", value).strip()


def _normalize_url(raw_url: str) -> str:
    return html.unescape(raw_url).strip().rstrip(".,;:)>]")


def _is_upwork_url(candidate: str) -> bool:
    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()
    return parsed.scheme in {"http", "https"} and (host == "upwork.com" or host.endswith(".upwork.com"))


def _is_job_like_path(candidate: str) -> bool:
    path = (urlparse(candidate).path or "").lower()
    if "~" in path:
        return True
    markers = ("/jobs/", "/job/", "/freelance-jobs/", "/ab/jobs/", "/nx/jobs/")
    return any(marker in path for marker in markers)


def _extract_parts(message: EmailMessage) -> tuple[str, str]:
    plain_chunks: list[str] = []
    html_chunks: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type().lower()
            try:
                content = part.get_content()
            except Exception:
                continue
            if not isinstance(content, str):
                continue
            if content_type == "text/plain":
                plain_chunks.append(content)
            elif content_type == "text/html":
                html_chunks.append(content)
    else:
        try:
            content = message.get_content()
        except Exception:
            content = ""
        if isinstance(content, str):
            if message.get_content_type().lower() == "text/html":
                html_chunks.append(content)
            else:
                plain_chunks.append(content)

    plain_text = "\n".join(plain_chunks).strip()
    html_text = "\n".join(html_chunks).strip()
    return plain_text, html_text


def _extract_upwork_url(raw_text: str) -> str:
    text = html.unescape(raw_text or "")
    if not text:
        return ""

    lower_text = text.lower()
    marker_idx = lower_text.find("... more:")
    if marker_idx >= 0:
        segment = text[marker_idx:]
        for raw_url in URL_PATTERN.findall(segment):
            candidate = _normalize_url(raw_url)
            if _is_upwork_url(candidate):
                return candidate

    first_valid = ""
    first_job_like = ""
    for raw_url in URL_PATTERN.findall(text):
        candidate = _normalize_url(raw_url)
        if not _is_upwork_url(candidate):
            continue
        if not first_valid:
            first_valid = candidate
        if not first_job_like and _is_job_like_path(candidate):
            first_job_like = candidate

    if first_job_like:
        return first_job_like
    if first_valid:
        return first_valid
    return ""


def extract_job_email(
    imap_uid: str,
    message: EmailMessage,
    allowed_sender_domain: str,
    detail_noise_phrase: str,
) -> tuple[ParsedJobEmail | None, str | None]:
    message_id = (message.get("Message-ID", "") or "").strip()
    if not message_id:
        return None, "missing_message_id"

    _, sender_email = parseaddr(message.get("From", ""))
    sender_email = sender_email.strip().lower()
    if "@" not in sender_email:
        return None, "missing_sender"
    sender_domain = sender_email.split("@", 1)[1]
    allowed = allowed_sender_domain.strip().lower()
    if not (sender_domain == allowed or sender_domain.endswith("." + allowed)):
        return None, "sender_domain_mismatch"

    date_header = (message.get("Date", "") or "").strip()
    try:
        parsed_date = parsedate_to_datetime(date_header)
    except Exception:
        return None, "invalid_date_header"
    if parsed_date is None:
        return None, "invalid_date_header"
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
    timestamp_utc = parsed_date.astimezone(timezone.utc).isoformat(timespec="seconds")

    plain_text, html_text = _extract_parts(message)
    if not plain_text and not html_text:
        return None, "missing_email_body"

    body_text = plain_text
    if not body_text and html_text:
        body_text = BeautifulSoup(html_text, "html.parser").get_text(separator=" ")
    body_text = _normalize_whitespace(body_text)
    if not body_text:
        return None, "empty_email_body"

    marker_idx = body_text.lower().find("view job details:")
    if marker_idx >= 0:
        body_text = _normalize_whitespace(body_text[:marker_idx])

    combined_source = "\n".join([html_text, plain_text, message.get("Subject", "")])
    job_url = _extract_upwork_url(combined_source)
    if not job_url:
        return None, "job_url_not_found"

    cleaned = URL_PATTERN.sub(" ", body_text)
    if detail_noise_phrase.strip():
        escaped_noise = re.escape(detail_noise_phrase.strip())
        cleaned = re.sub(escaped_noise, " ", cleaned, flags=re.IGNORECASE)
    cleaned = _normalize_whitespace(cleaned)
    if len(cleaned) < 20:
        return None, "description_too_short"
    if len(cleaned) > 1200:
        cleaned = cleaned[:1200].rstrip()

    short_description = cleaned[:220].rstrip()
    subject = _normalize_whitespace(message.get("Subject", "") or "")

    return (
        ParsedJobEmail(
            imap_uid=imap_uid,
            message_id=message_id,
            timestamp_utc=timestamp_utc,
            job_url=job_url,
            job_description=cleaned,
            short_description=short_description,
            subject=subject,
        ),
        None,
    )
