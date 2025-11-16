import email
import imaplib
import json
from pathlib import Path


CONFIG_NAME = "config.json"
GMAIL_HOST = "imap.gmail.com"
GMAIL_FOLDER = "inbox"
RAW_QUERY = 'category:primary is:unread subject:Scam'


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


if __name__ == "__main__":
    fetch_unread_scam()
