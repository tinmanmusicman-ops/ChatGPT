from __future__ import annotations

import argparse
import html as html_module
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict

try:
    import requests
except ImportError:  # pragma: no cover - handled at runtime
    requests = None


PROJECT_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_DIR / "logs"
LAST_SUMMARY_TEXT_PATH = LOG_DIR / "last_email_summary.txt"
LAST_SUMMARY_HTML_PATH = LOG_DIR / "last_email_summary.html"
LAST_ERROR_PATH = LOG_DIR / "last_email_summary_error.txt"
GLOBAL_CONFIG_PATH = Path(r"C:\ChatGPT\ai-bots\shared\global.json")


class FailFastError(RuntimeError):
    pass


def _read_required_text(path: Path, label: str) -> str:
    if not path.exists():
        raise FailFastError(f"Missing required {label}: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FailFastError(f"Unable to read {label}: {path} ({exc})") from exc
    clean = text.strip()
    if not clean:
        raise FailFastError(f"{label} is empty: {path}")
    return clean


def _load_api_key() -> str:
    raw = _read_required_text(GLOBAL_CONFIG_PATH, "global config file")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FailFastError(f"Invalid JSON in global config: {GLOBAL_CONFIG_PATH} ({exc})") from exc
    if not isinstance(data, dict):
        raise FailFastError(f"global config must be a JSON object: {GLOBAL_CONFIG_PATH}")
    for key_name in ("openai_api_key", "OPENAI_API_KEY"):
        value = data.get(key_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise FailFastError(f"OpenAI API key not found in {GLOBAL_CONFIG_PATH}")


def _system_prompt() -> str:
    return (
        "Summarize the provided email or message clearly and concisely.\n"
        "Return only:\n"
        "Summary: (3-5 sentence max overview)\n"
        "KeyPoints: (short bullet-style sentence line separated by semicolons)\n"
        "ActionItems: (if present, otherwise write \"None\")\n"
        "Tone: (Informational, Urgent, Decision Needed, or Neutral)\n"
        "Keep total response under 120 words.\n"
        "Do not invent information.\n"
        "Plain ASCII only.\n"
        "No markdown formatting."
    )


def _user_prompt(message_text: str) -> str:
    return f"Message:\n{message_text}\n"


def _call_openai_with_sdk(api_key: str, model: str, message_text: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return ""
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        temperature=0.2,
        input=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(message_text)},
        ],
    )
    output = getattr(response, "output_text", "") or ""
    return output.strip()


def _call_openai_with_http(api_key: str, model: str, message_text: str) -> str:
    if requests is None:
        raise FailFastError("Neither OpenAI SDK nor requests is available for API call.")

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.2,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(message_text)},
            ],
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise FailFastError(f"OpenAI request failed ({response.status_code}): {response.text}")

    data = response.json()
    output_text = (data.get("output_text") or "").strip()
    if output_text:
        return output_text

    parts = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content") or []:
            if not isinstance(content_item, dict):
                continue
            text_value = content_item.get("text")
            if isinstance(text_value, str):
                parts.append(text_value)
    return "\n".join(parts).strip()


def _ascii_clean(value: str) -> str:
    return value.encode("ascii", "ignore").decode("ascii")


def _normalize_output(raw_output: str) -> str:
    required = ("Summary", "KeyPoints", "ActionItems", "Tone")
    parsed_blocks: Dict[str, list[str]] = {label: [] for label in required}
    current_label = ""

    for line in raw_output.splitlines():
        clean_line = _ascii_clean(line).strip()
        if not clean_line:
            continue
        matched = False
        for label in required:
            prefix = f"{label}:"
            if clean_line.startswith(prefix):
                first_value = clean_line[len(prefix) :].strip()
                if first_value:
                    parsed_blocks[label].append(first_value)
                current_label = label
                matched = True
                break
        if matched:
            continue
        if current_label:
            parsed_blocks[current_label].append(clean_line)

    parsed: Dict[str, str] = {}
    for label in required:
        value = " ".join(part.strip() for part in parsed_blocks[label] if part.strip()).strip()
        if value:
            parsed[label] = value

    for label in required:
        if label not in parsed:
            raise FailFastError(f"Model output missing required field: {label}")

    tone_map = {
        "informational": "Informational",
        "urgent": "Urgent",
        "decision needed": "Decision Needed",
        "neutral": "Neutral",
    }
    tone_key = parsed["Tone"].strip().lower()
    if tone_key not in tone_map:
        raise FailFastError(f"Invalid Tone value: {parsed['Tone']}")
    tone = tone_map[tone_key]

    key_points = parsed["KeyPoints"].replace("\n", " ")
    key_points = key_points.replace(" - ", "; ")
    if ";" not in key_points and ". " in key_points:
        key_points = "; ".join(part.strip() for part in key_points.split(". ") if part.strip())
    key_points = key_points.strip(" ;.")
    key_points = key_points + ("." if key_points and not key_points.endswith(".") else "")

    action_items = parsed["ActionItems"].strip()
    if not action_items:
        action_items = "None"

    lines = [
        f"Summary: {parsed['Summary'].strip()}",
        f"KeyPoints: {key_points if key_points else 'None.'}",
        f"ActionItems: {action_items}",
        f"Tone: {tone}",
    ]
    final_text = "\n".join(_ascii_clean(line) for line in lines).strip() + "\n"

    total_words = len(final_text.replace("\n", " ").split())
    if total_words > 120:
        raise FailFastError(f"Summary exceeds 120-word limit: {total_words}")
    return final_text


def _parse_summary_fields(summary: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in summary.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _write_summary_html(summary: str, input_path: Path, text_log_path: Path) -> Path:
    fields = _parse_summary_fields(summary)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Email Summary</title>
  <style>
    :root {{ color-scheme: dark; forced-color-adjust: none; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#000; color:#faebd7; padding:30px; }}
    .container {{ max-width:900px; margin:0 auto; background:#111; border:4px solid #ff8c00; border-radius:18px; padding:28px; box-shadow:0 30px 50px rgba(0,0,0,0.75); }}
    h1 {{ font-size:2rem; margin:0 0 10px; color:#ff9a00; text-transform:uppercase; letter-spacing:0.12rem; }}
    .meta {{ color:#fffacd; font-size:0.95rem; margin-bottom:16px; }}
    p {{ line-height:1.7; margin:12px 0; font-size:1.04rem; }}
    strong {{ color:#5aa4ff; }}
    .tone strong {{ color:#ffa500; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Email Summary</h1>
    <div class="meta">Input: {html_module.escape(input_path.name)} | Log: {html_module.escape(text_log_path.name)} | {datetime.now().isoformat(timespec='seconds')}</div>
    <p><strong>Summary:</strong> {html_module.escape(fields.get("Summary", ""))}</p>
    <p><strong>KeyPoints:</strong> {html_module.escape(fields.get("KeyPoints", ""))}</p>
    <p><strong>ActionItems:</strong> {html_module.escape(fields.get("ActionItems", ""))}</p>
    <p class="tone"><strong>Tone:</strong> {html_module.escape(fields.get("Tone", ""))}</p>
  </div>
</body>
</html>
"""
    LAST_SUMMARY_HTML_PATH.write_text(html_content, encoding="utf-8")
    return LAST_SUMMARY_HTML_PATH


def _write_outputs(normalized_output: str, input_path: Path) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_text_path = LOG_DIR / f"email_summary_{stamp}.txt"

    timestamped_body = (
        f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"InputFile: {input_path}\n\n"
        f"{normalized_output}"
    )
    timestamped_text_path.write_text(timestamped_body, encoding="utf-8")
    LAST_SUMMARY_TEXT_PATH.write_text(normalized_output, encoding="utf-8")
    return _write_summary_html(summary=normalized_output, input_path=input_path, text_log_path=timestamped_text_path)


def _write_error(error_text: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LAST_ERROR_PATH.write_text(error_text.strip() + "\n", encoding="utf-8")


def _clear_error() -> None:
    if LAST_ERROR_PATH.exists():
        LAST_ERROR_PATH.unlink()


def _open_browser(path: Path) -> None:
    webbrowser.open_new_tab(str(path))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize selected email/message text with OpenAI.")
    parser.add_argument("input_text_file", help="UTF-8 text file containing the selected message body.")
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model to use.")
    parser.add_argument("--no-open", action="store_true", help="Do not open HTML summary automatically.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    input_path = Path(args.input_text_file).expanduser().resolve()
    message_text = _read_required_text(input_path, "message text input file")
    api_key = _load_api_key()

    raw_output = _call_openai_with_sdk(api_key=api_key, model=args.model, message_text=message_text)
    if not raw_output:
        raw_output = _call_openai_with_http(api_key=api_key, model=args.model, message_text=message_text)
    if not raw_output:
        raise FailFastError("OpenAI returned an empty response.")

    normalized = _normalize_output(raw_output)
    html_path = _write_outputs(normalized, input_path=input_path)
    _clear_error()
    print(normalized, end="")
    if not args.no_open:
        _open_browser(html_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FailFastError as exc:
        _write_error(f"ERROR: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
