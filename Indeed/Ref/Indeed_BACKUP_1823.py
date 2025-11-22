import email
import imaplib
import json
import re
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

import requests


CONFIG_NAME = "config.json"
GMAIL_HOST = "imap.gmail.com"
GMAIL_FOLDER = "inbox"
RAW_QUERY = 'category:primary is:unread subject:Scam'
SCAM_FOLDER = "Scam"
FROM_LINE_PATTERN = re.compile(r"^[>\s\-\|]*from:\s*(.+)$", flags=re.IGNORECASE | re.MULTILINE)
PROMPT = (
    "You are a security analyst. Decide whether the email below is a scam. "
    "Respond ONLY with raw JSON (no code fences, no extra text) containing fields: "
    "is_scam (true/false), confidence (0-1), signals (list of short reasons), "
    "summary (short sentence). Base your answer on the body content; sender metadata "
    "is provided."
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def log(message):
    print("")
    print(f"[IsitScam] {message}")


def load_config():
    config_path = Path(__file__).with_name(CONFIG_NAME)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    print("")
    log("Configuration loaded successfully.")
    return config


def extract_body(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                disposition = part.get_content_disposition()
                if disposition in (None, "inline"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
        log("extract_body: no inline text/plain part found; returning empty string.")
        return ""
    payload = message.get_payload(decode=True)
    if payload:
        charset = message.get_content_charset() or "utf-8"
        body = payload.decode(charset, errors="replace")
        log("extract_body: extracted single-part text body.")
        return body
    log("extract_body: returning raw payload as string.")
    return message.get_payload()


def collect_from_blocks(text):
    matches = list(FROM_LINE_PATTERN.finditer(text))
    senders = []
    blocks = []

    if not matches:
        log("collect_from_blocks: no forwarded From: markers detected.")
        return [], [text]

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        segment = text[start:end].strip()
        addr = parseaddr(match.group(1).strip())[1]
        if addr:
            senders.append(addr)
            blocks.append(segment)

    if not senders:
        log("collect_from_blocks: markers found but no valid email addresses detected.")
        return [], [text]
    log(f"collect_from_blocks: extracted {len(senders)} sender blocks.")
    return senders, blocks


def decode_subject(raw_subject):
    if not raw_subject:
        return ""
    try:
        return str(make_header(decode_header(raw_subject)))
    except Exception:
        return raw_subject


def strip_scam_prefix(subject):
    if not subject:
        return ""
    return re.sub(r"^\s*scam[:\-\s]*", "", subject, flags=re.IGNORECASE, count=1).strip()


def clean_header_value(value):
    if not value:
        return ""
    return re.sub(r"[\r\n]+", " ", value).strip()


def forward_message(body, recipient, subject, username, password):
    msg = EmailMessage()
    safe_subject = clean_header_value(subject or "Forwarded message") or "Forwarded message"
    safe_sender = clean_header_value(username)
    safe_recipient = clean_header_value(recipient)
    msg["From"] = safe_sender
    msg["To"] = safe_recipient
    msg["Subject"] = safe_subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body or "(Empty body)")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(username, password)
        smtp.send_message(msg)
    log(f"forward_message: forwarded sanitized copy to {safe_recipient}.")


def analyze_body(body, sender, config):
    api_key = config.get("openai_api_key")
    if not api_key:
        raise RuntimeError("Missing openai_api_key in config.json")

    payload = {
        "model": config.get("openai_model", "gpt-4o-mini"),
        "temperature": config.get("openai_temperature", 0.1),
        "messages": [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": f"Sender: {sender or 'unknown'}\nEmail body:\n---\n{body}\n---",
            },
        ],
    }

    response = requests.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()
    log(f"analyze_body: received response for sender {sender or 'unknown'}.")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI response was not valid JSON: {content}") from exc


def fetch_unread_scam():
    config = load_config()
    username = config.get("gmail_user") or config.get("user")
    password = config.get("gmail_app_password") or config.get("app_password")

    if not username or not password:
        raise RuntimeError("Missing gmail_user/app_password in config.json")

    with imaplib.IMAP4_SSL(GMAIL_HOST) as client:
        client.login(username, password)
        client.select(GMAIL_FOLDER)
        status, data = client.uid("search", None, "X-GM-RAW", f'"{RAW_QUERY}"')
        if status != "OK" or not data or not data[0]:
            log("No unread Primary emails with 'Scam' in the subject.")
            return

        latest_uid = data[0].split()[-1]
        status, payload = client.uid("fetch", latest_uid, "(RFC822)")
        if status != "OK" or not payload or payload[0] is None:
            raise RuntimeError(f"Unable to fetch email UID {latest_uid!r}")

        message = email.message_from_bytes(payload[0][1])
        raw_subject = message.get("Subject", "")
        subject = decode_subject(raw_subject)
        subject_prefix = (subject.lstrip()[:4] or "").lower()
        if subject_prefix != "scam":
            log(
                f"Skipping email UID {latest_uid.decode() if isinstance(latest_uid, bytes) else latest_uid}: "
                f"subject '{subject}' does not start with 'Scam'."
            )
            client.uid("STORE", latest_uid, "-FLAGS", r"(\Seen)")
            return
        cleaned_subject = strip_scam_prefix(subject)

        body = extract_body(message)
        from_addresses, body_segments = collect_from_blocks(body)
        if from_addresses:
            sender_for_ai = from_addresses[-1]
            body_for_ai = body_segments[-1] if body_segments else body
            body_for_ai = body_for_ai or body
        else:
            sender_for_ai = ""
            body_for_ai = body

        analysis = analyze_body(body_for_ai, sender_for_ai, config)
        summary = analysis.get("summary", "No summary provided.")
        is_scam = bool(analysis.get("is_scam"))

        action_msg = "Forwarded sanitized copy back to inbox."
        if is_scam:
            copy_status, copy_data = client.uid("COPY", latest_uid, SCAM_FOLDER)
            if copy_status != "OK":
                raise RuntimeError(f"Failed to copy email {latest_uid!r} to {SCAM_FOLDER}: {copy_data}")
            store_status, store_data = client.uid("STORE", latest_uid, "+FLAGS", r"(\Deleted)")
            if store_status != "OK":
                raise RuntimeError(f"Failed to mark email {latest_uid!r} for deletion: {store_data}")
            client.expunge()
            action_msg = f"Moved to '{SCAM_FOLDER}' (copied + deleted original)."
        else:
            envelope_sender = config.get("gmail_user") or config.get("user")
            if envelope_sender and username and password:
                forward_message(body_for_ai, envelope_sender, cleaned_subject, username, password)
            delete_status, delete_data = client.uid("STORE", latest_uid, "+FLAGS", r"(\Deleted)")
            if delete_status != "OK":
                raise RuntimeError(f"Failed to mark legitimate email {latest_uid!r} for deletion: {delete_data}")
            client.expunge()
            action_msg = "Forwarded sanitized copy and removed original."

        log(
            f"Sender: {sender_for_ai or 'unknown'} | Subject: {subject} | "
            f"Summary: {summary} | Action: {action_msg}"
        )



if __name__ == "__main__":
    fetch_unread_scam()
