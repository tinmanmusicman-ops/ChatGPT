import email
import imaplib
import json
import re
from email.utils import parseaddr
from pathlib import Path

import requests


CONFIG_NAME = "config.json"
GMAIL_HOST = "imap.gmail.com"
GMAIL_FOLDER = "inbox"
RAW_QUERY = 'category:primary is:unread subject:Scam'
FROM_LINE_PATTERN = re.compile(r"^[>\s\-\|]*from:\s*(.+)$", flags=re.IGNORECASE | re.MULTILINE)
PROMPT = (
    "You are a security analyst. Decide whether the email below is a scam. "
    "Respond ONLY with raw JSON (no code fences, no extra text) containing fields: "
    "is_scam (true/false), confidence (0-1), signals (list of short reasons), "
    "summary (short sentence). Base your answer on the body content; sender metadata "
    "is provided."
)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def load_config():
    config_path = Path(__file__).with_name(CONFIG_NAME)
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
        return ""
    payload = message.get_payload(decode=True)
    if payload:
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return message.get_payload()


def extract_from_lines(text):
    matches = []
    for match in FROM_LINE_PATTERN.finditer(text):
        addr = parseaddr(match.group(1).strip())[1]
        if addr:
            matches.append(addr)
    return matches


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
            print("No unread Primary emails with 'Scam' in the subject.")
            return

        latest_uid = data[0].split()[-1]
        status, payload = client.uid("fetch", latest_uid, "(RFC822)")
        if status != "OK" or not payload or payload[0] is None:
            raise RuntimeError(f"Unable to fetch email UID {latest_uid!r}")

        message = email.message_from_bytes(payload[0][1])
        body = extract_body(message)
        from_addresses = extract_from_lines(body)
        sender_for_ai = from_addresses[1] if len(from_addresses) > 1 else (from_addresses[0] if from_addresses else "")
        analysis = analyze_body(body, sender_for_ai, config)
        breakpoint()  # Inspect `body`, `from_addresses`, `analysis`.


if __name__ == "__main__":
    fetch_unread_scam()
