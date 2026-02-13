from __future__ import annotations

import argparse
import html as html_module
import json
import subprocess
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
LAST_RESULT_PATH = LOG_DIR / "last_result.txt"
LAST_RESULT_HTML = LOG_DIR / "last_result.html"
DEEP_LOG_PATH = LOG_DIR / "deep_debug.log"
GLOBAL_CONFIG_PATH = Path(r"C:\ChatGPT\ai-bots\shared\global.json")
RESUME_PATH = Path(r"C:\ChatGPT\ai-bots\AI-FIT-Site\core-US-2026-000001.md")


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


def _extract_job_metadata(job_text: str, job_file_path: Path) -> tuple[str, str]:
    job_title = job_file_path.stem
    company = "Unknown Company"
    for line in job_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("job title:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                job_title = value
        elif stripped.lower().startswith("company:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                company = value
    return job_title, company


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
        "You compare a job description against a master resume. "
        "Use only facts present in the resume text. Do not invent facts. "
        "Return plain ASCII only. No markdown. Use exactly these lines in order:\n"
        "FitScore: N\n"
        "Strengths: ...\n"
        "Gaps: ...\n"
        "Tailor: ...\n"
        "Recommendation: Apply|Skip|Investigate\n"
        "FitScore must be an integer from 0 to 100."
    )


def _user_prompt(job_text: str, resume_text: str) -> str:
    return (
        "Resume:\n"
        f"{resume_text}\n\n"
        "Job Description:\n"
        f"{job_text}\n"
    )


def _call_openai_with_sdk(api_key: str, model: str, job_text: str, resume_text: str) -> str:
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
            {"role": "user", "content": _user_prompt(job_text, resume_text)},
        ],
    )
    output = getattr(response, "output_text", "") or ""
    return output.strip()


def _call_openai_with_http(api_key: str, model: str, job_text: str, resume_text: str) -> str:
    if requests is None:
        raise FailFastError("Neither OpenAI SDK nor requests is available for API call.")

    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0.2,
        "input": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(job_text, resume_text)},
        ],
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code >= 400:
        raise FailFastError(f"OpenAI request failed ({response.status_code}): {response.text}")

    data = response.json()
    output_text = (data.get("output_text") or "").strip()
    if output_text:
        return output_text

    output_items = data.get("output") or []
    parts = []
    for item in output_items:
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
    required = ("FitScore", "Strengths", "Gaps", "Tailor", "Recommendation")
    parsed: Dict[str, str] = {}

    for line in raw_output.splitlines():
        clean_line = _ascii_clean(line).strip()
        if not clean_line or ":" not in clean_line:
            continue
        label, value = clean_line.split(":", 1)
        label = label.strip()
        value = value.strip()
        if label in required and value:
            parsed[label] = value

    for label in required:
        if label not in parsed:
            raise FailFastError(f"Model output missing required field: {label}")

    try:
        score = int(parsed["FitScore"])
    except ValueError as exc:
        raise FailFastError(f"Invalid FitScore value: {parsed['FitScore']}") from exc
    if score < 0 or score > 100:
        raise FailFastError(f"FitScore out of range 0-100: {score}")

    recommendation = parsed["Recommendation"].strip()
    if recommendation not in {"Apply", "Skip", "Investigate"}:
        raise FailFastError(f"Invalid Recommendation value: {recommendation}")

    lines = [
        f"FitScore: {score}",
        f"Strengths: {parsed['Strengths']}",
        f"Gaps: {parsed['Gaps']}",
        f"Tailor: {parsed['Tailor']}",
        f"Recommendation: {recommendation}",
    ]
    return "\n".join(_ascii_clean(line) for line in lines) + "\n"


def _append_deep_log(job_file_path: Path, job_text: str, raw_output: str, summary: str, api_source: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    snippet = ' '.join(job_text.splitlines())
    snippet = snippet.strip()
    if len(snippet) > 400:
        snippet = snippet[:400] + '... (truncated)'
    raw_clean = raw_output.strip()
    summary_clean = summary.strip()
    entry = (
        f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"JobFile: {job_file_path}\n"
        f"JobLength: {len(job_text)}\n"
        f"ApiSource: {api_source}\n"
        f"JobSnippet: {snippet}\n"
        "RawOutput:\n"
        f"{raw_clean}\n"
        "Normalized:\n"
        f"{summary_clean}\n"
        + '-' * 60
        + '\n'
    )
    with DEEP_LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(entry)

def _write_results(summary: str, job_file_path: Path, job_title: str, company: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"jobfit_{stamp}.txt"

    log_body = (
        f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"JobFile: {job_file_path}\n"
        f"JobTitle: {job_title}\n"
        f"Company: {company}\n"
        f"ResumeFile: {RESUME_PATH}\n\n"
        f"{summary}"
    )
    log_path.write_text(log_body, encoding="utf-8")

    last_body = summary + f"\nLogFile: {log_path}\n"
    LAST_RESULT_PATH.write_text(last_body, encoding="utf-8")
    html_path = _write_html(summary=summary, job_file_path=job_file_path, log_path=log_path, job_title=job_title, company=company)
    return log_path


def _write_html(summary: str, job_file_path: Path, log_path: Path, job_title: str, company: str) -> Path:
    data = {}
    for line in summary.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()

    pillar = {
        "FitScore": data.get("FitScore", ""),
        "Strengths": data.get("Strengths", ""),
        "Gaps": data.get("Gaps", ""),
        "Tailor": data.get("Tailor", ""),
        "Recommendation": data.get("Recommendation", ""),
    }

    body = "\n".join(
        f"<p class=\"{html_module.escape(key.lower())}\"><strong>{html_module.escape(key)}:</strong> {html_module.escape(value)}</p>"
        for key, value in pillar.items()
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Job Fit Summary</title>
  <style>
    :root {{ color-scheme: dark; forced-color-adjust: none; }}
    * {{ -webkit-font-smoothing: antialiased; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#000; color:#faebd7; padding:30px; forced-color-adjust:none; }}
    .container {{ max-width:960px; margin:0 auto; background:#111; border:4px solid #ff8c00; border-radius:18px; padding:32px; box-shadow:0 0 0 3px #111, 0 40px 60px rgba(0,0,0,0.75); forced-color-adjust:none; }}
    .header-row {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:12px; }}
    h1 {{ font-size:2.4rem; margin:0; color:#ff9a00; text-transform:uppercase; letter-spacing:0.2rem; }}
    .meta {{ font-size:0.95rem; color:#fffacd; }}
    p {{ line-height:1.8; margin:16px 0; font-size:1.1rem; }}
    .recommendation {{ font-size:1.35rem; color:#ffa500; font-weight:700; }}
    .header-row h1 {{ color:#ff9a00; }}
    .strengths strong, .gaps strong, .tailor strong {{ color:#5aa4ff; }}
    .fit-score {{ font-size:1.3rem; margin-bottom:6px; }}
    .source {{ font-size:0.95rem; color:#d0d6ff; margin-bottom:8px; }}
    .credentials {{ margin-top:26px; font-size:0.85rem; color:#a8d4ff; }}
    @media (prefers-contrast: more) {{
      body {{ background:#050505; }}
      .container {{ border-color:#ffb347; box-shadow:0 0 0 4px #111, 0 30px 50px rgba(255,140,0,0.45); }}
    }}
  </style>
</head>
    <body>
  <div class="container">
    <div class="header-row">
      <h1>{html_module.escape(job_title)}</h1>
      <div class="meta">{html_module.escape(company)} • Job: {html_module.escape(job_file_path.name)} • Log: {html_module.escape(log_path.name)} • {datetime.now().isoformat(timespec='seconds')}</div>
    </div>
    <div class="source">Resume: {html_module.escape(RESUME_PATH.name)}</div>
    <div class="fit-score"><strong>FitScore:</strong> {html_module.escape(data.get("FitScore", ""))}</div>
    {body}
    <div class="credentials">Generated by Evaluate Job Fit on Windows; high-contrast colors enforced.</div>
  </div>
</body>
</html>
"""
    LAST_RESULT_HTML.write_text(html_content, encoding="utf-8")
    return LAST_RESULT_HTML


def _open_browser(path: Path) -> None:
    webbrowser.open_new_tab(str(path))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate how well a job fits the master resume.")
    parser.add_argument("job_text_file", help="UTF-8 text file containing the selected job description.")
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model to use.")
    parser.add_argument("--no-open", action="store_true", help="Do not open Notepad automatically.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    job_file_path = Path(args.job_text_file).expanduser().resolve()
    job_text = _read_required_text(job_file_path, "job text input file")
    job_title, company = _extract_job_metadata(job_text, job_file_path)
    resume_text = _read_required_text(RESUME_PATH, "resume markdown file")
    api_key = _load_api_key()

    api_source = "SDK"
    raw_output = _call_openai_with_sdk(api_key=api_key, model=args.model, job_text=job_text, resume_text=resume_text)
    if not raw_output:
        api_source = "HTTP"
        raw_output = _call_openai_with_http(
            api_key=api_key,
            model=args.model,
            job_text=job_text,
            resume_text=resume_text,
        )
    if not raw_output:
        raise FailFastError("OpenAI returned an empty response.")

    summary = _normalize_output(raw_output)
    _append_deep_log(job_file_path, job_text, raw_output, summary, api_source)
    _write_results(summary=summary, job_file_path=job_file_path, job_title=job_title, company=company)
    print(summary, end="")
    if not args.no_open:
        _open_browser(LAST_RESULT_HTML)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FailFastError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
