from __future__ import annotations

import email
import imaplib
import json
import os
from email.header import decode_header
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

COMPANY_INFO_PROMPT = """
You are an AI Business Analyst.

Input:
- Email body text of a job-alert email.
- For each job-related URL contained in the email, extract the job details and determine the referenced company.
- For each company referenced in the email, produce an in-depth SWOT assessment (Strengths, Weaknesses, Opportunities, Threats) using only information from the email body and clear context around the job URL (no outside research).


Instructions:
1. Identify every distinct job URL in the email. Treat each as a unique job entry.
2. For each job entry:
   - Determine company_name from the surrounding text or the page/URL hints in the email.
   - Develop a company_info field containing a SWOT mini-brief. Each component must be labeled (e.g., "Strengths: ...; Weaknesses: ...") and highlight concrete details from the email: company overview, capabilities, differentiators, pain points, market positioning, hiring cues, or risks affecting customers/employees. When a component lacks evidence, explicitly note "Strengths: null" (etc.) rather than inventing information.
   - Capture the job URL itself in url.

3. Return a JSON object of the form:
{
  "jobs": [
    {
      "company_name": string|null,
      "url": string,
      "company_info": string|null
    }
  ]
}

Rules:
- Only use information present in the email content for company_info; do not fabricate or infer from outside knowledge.
- company_info must concisely cover Strengths, Weaknesses, Opportunities, and Threats (up to ~100 words) with each label spelled out. If every SWOT dimension is empty, set company_info to null.
- Always include each field (company_name, url, company_info) for every job object, even if company_info is null.
- Output only valid JSON (no markdown, code fences, or commentary).
""".strip()


def load_config() -> Dict[str, object]:
    """Load email + API configuration."""
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing config file: {CONFIG_PATH}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {CONFIG_PATH}: {exc}") from exc


def _decode_mime_header(value: Optional[str]) -> str:
    """Decode MIME headers (Subject, From)."""
    if not value:
        return ""
    parts: List[str] = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(charset or "utf-8", "replace"))
            except Exception:
                parts.append(text.decode("utf-8", "replace"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def get_openai_client(cfg: Dict[str, object]) -> OpenAI:
    """Construct an OpenAI client from config/environment."""
    api_key = cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing OpenAI API key. Set openai_api_key in config.json or OPENAI_API_KEY env var.")
    return OpenAI(api_key=api_key)


def _extract_body(msg: email.message.Message) -> str:
    """Return HTML body if present, otherwise plain text."""
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
            content_type = part.get_content_type()
            if content_type == "text/html" and not html_body:
                html_body = decoded
            elif content_type == "text/plain" and not text_body:
                text_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text_body = payload.decode(msg.get_content_charset() or "utf-8", "replace")

    return (html_body or text_body or "").strip()


def _search_args(cfg: Dict[str, object], include_sender: bool = True) -> List[str]:
    """Build IMAP SEARCH filters for primary unseen mail."""
    args: List[str] = []
    raw_terms: List[str] = ["category:primary"]

    subject_term = (cfg.get("subject_term") or "").strip()
    if subject_term:
        raw_terms.append(f'subject:"{subject_term}"')

    if raw_terms:
        args.extend(["X-GM-RAW", f"\"{' '.join(raw_terms)}\""])

    sender = None
    if include_sender:
        sender = cfg.get("gmail_from_filter") or next(
            (s for s in cfg.get("gmail_from_filters", []) if s), None
        )
        if sender:
            args.extend(["FROM", f"\"{sender}\""])

    args.append("UNSEEN")
    return args


def extract_company_info(body: str, cfg: Dict[str, object]) -> Dict[str, object]:
    """Send the email body to OpenAI to extract company info per job."""
    if not body:
        return {"jobs": []}

    client = get_openai_client(cfg)
    model = cfg.get("openai_model") or "gpt-4o-mini"
    temperature = cfg.get("openai_temperature")
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 0.1

    response = client.responses.create(
        model=model,
        instructions=COMPANY_INFO_PROMPT,
        input=body,
        temperature=temperature,
    )


    raw = getattr(response, "output_text", None)
    if not raw:
        try:
            first = response.output[0]
            parts: List[str] = []
            for content in getattr(first, "content", []):
                text_part = getattr(content, "text", None)
                if text_part:
                    value = getattr(text_part, "value", None)
                    if isinstance(value, str):
                        parts.append(value)
            raw = "\n".join(parts)
        except Exception:
            return {"jobs": [], "error": "Unable to parse AI response"}

    raw = str(raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"jobs": [], "raw": raw, "error": "JSON decode failed"}


def fetch_unseen_primary(cfg: Dict[str, object]) -> Optional[Dict[str, str]]:
    """Grab the first unseen message in the Primary inbox."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    first_uid_bytes: Optional[bytes] = None
    revert_unseen = False
    try:
        mail.login(cfg["gmail_user"], cfg["gmail_app_password"])
        status, _ = mail.select("INBOX")
        if status != "OK":
            raise RuntimeError("Unable to select INBOX")

        search_args = _search_args(cfg, include_sender=True)
        status, data = mail.uid("SEARCH", None, *search_args)
        if status != "OK" or not data or not data[0]:
            print("[INFO] No unseen message matched sender filters; retrying without them.")
            search_args = _search_args(cfg, include_sender=False)
            status, data = mail.uid("SEARCH", None, *search_args)
            if status != "OK" or not data or not data[0]:
                return None

        first_uid_bytes = data[0].split()[0]
        status, msg_data = mail.uid("FETCH", first_uid_bytes, "(RFC822)")
        if status != "OK" or not msg_data:
            return None

        msg = email.message_from_bytes(msg_data[0][1])
        body_text = _extract_body(msg)

        if cfg.get("mark_read", True):
            mail.uid("STORE", first_uid_bytes, "+FLAGS", "(\\Seen)")
            revert_unseen = True

        return {
            "uid": first_uid_bytes.decode(),
            "subject": _decode_mime_header(msg.get("Subject")),
            "from": _decode_mime_header(msg.get("From")),
            "body": body_text,
        }
    finally:
        if revert_unseen and first_uid_bytes is not None:
            try:
                mail.uid("STORE", first_uid_bytes, "-FLAGS", "(\\Seen)")
            except Exception:
                pass
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    cfg = load_config()
    email_payload = fetch_unseen_primary(cfg)
    body = ""

    if email_payload is None:
        print("No unseen email found in Primary.")
    else:
        body = email_payload["body"]
        print(f"Subject: {email_payload['subject']}")
        print(f"From: {email_payload['from']}")
        print("\n--- Email Body (first 400 chars) ---")
        print(body[:400])
        print("\n--- End ---")
        company_info = extract_company_info(body, cfg)
        print("\n--- AI Company Info ---")
        print(json.dumps(company_info, indent=2))
