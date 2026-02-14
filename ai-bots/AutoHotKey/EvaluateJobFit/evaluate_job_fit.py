from __future__ import annotations

import argparse
import html as html_module
import json
import re
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

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
RESUME_PATH = Path(r"C:\ChatGPT\CORES\CORE-US-2026-000001.md")


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
        "Review the entire resume before writing output. "
        "Use the provided priority evidence index only as a navigation aid, not as a replacement for full resume review. "
        "Before writing Gaps, run an evidence check against the full resume text and the priority evidence index. "
        "Every gap must be truly absent from both. "
        "If directly related or transferable evidence exists anywhere in either source, do not claim it is missing. "
        "When evidence is partial, describe it as partial rather than missing. "
        "Return compact sentence text on each field line; do not use bullet formatting. "
        "Return plain ASCII only. No markdown. Use exactly these lines in order:\n"
        "FitScore: N\n"
        "Strengths: ...\n"
        "Gaps: ...\n"
        "Tailor: ...\n"
        "Recommendation: Apply|Skip|Investigate\n"
        "FitScore must be an integer from 0 to 100."
    )


def _extract_priority_resume_evidence(job_text: str, resume_text: str, max_lines: int = 20) -> str:
    job_tokens = {token for token in re.findall(r"[a-z0-9]+", job_text.lower()) if len(token) >= 3}
    scored_lines = []
    seen = set()

    for raw_line in resume_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in seen:
            continue
        line_lower = line.lower()
        line_tokens = set(re.findall(r"[a-z0-9]+", line_lower))
        overlap = job_tokens & line_tokens
        if not overlap:
            continue

        score = len(overlap)
        if line.startswith("-"):
            score += 2

        scored_lines.append((score, line))
        seen.add(line)

    scored_lines.sort(key=lambda item: item[0], reverse=True)
    selected = [line for _, line in scored_lines[:max_lines]]
    if not selected:
        return "NONE"
    return "\n".join(selected)


def _user_prompt(job_text: str, resume_text: str) -> str:
    priority_evidence = _extract_priority_resume_evidence(job_text=job_text, resume_text=resume_text)
    return (
        "Resume:\n"
        f"{resume_text}\n\n"
        "Priority Evidence Note:\n"
        "The priority evidence lines below are auto-selected from the full resume by lexical overlap with the job description.\n\n"
        "Priority Resume Evidence:\n"
        f"{priority_evidence}\n\n"
        "Job Description:\n"
        f"{job_text}\n"
    )


def _correction_system_prompt() -> str:
    return (
        "You are validating a job-fit summary against a resume and job description. "
        "Fix contradictions where Gaps claims missing evidence that appears in the resume. "
        "Use only facts from the resume. Do not invent facts. "
        "Return plain ASCII only. No markdown. Use exactly these lines in order:\n"
        "FitScore: N\n"
        "Strengths: ...\n"
        "Gaps: ...\n"
        "Tailor: ...\n"
        "Recommendation: Apply|Skip|Investigate\n"
        "Use compact sentence text on each line."
    )


def _correction_user_prompt(
    job_text: str,
    resume_text: str,
    current_summary: str,
    contradictions: list[str],
) -> str:
    contradiction_lines = "\n".join(f"- {item}" for item in contradictions)
    return (
        "Resume:\n"
        f"{resume_text}\n\n"
        "Job Description:\n"
        f"{job_text}\n\n"
        "Current Summary:\n"
        f"{current_summary}\n\n"
        "Detected Contradictions To Fix:\n"
        f"{contradiction_lines}\n\n"
        "Rewrite the full summary in the required five-line format."
    )


def _parse_summary_fields(summary: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in summary.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _split_gap_claims(gaps_text: str) -> list[str]:
    if " - " in gaps_text:
        return [part.strip(" -.;") for part in gaps_text.split(" - ") if part.strip(" -.;")]
    return [part.strip(" -.;") for part in re.split(r";|\.\s+", gaps_text) if part.strip(" -.;")]


def _extract_claim_tokens(claim: str) -> list[str]:
    stopwords = {
        "about",
        "after",
        "also",
        "and",
        "any",
        "are",
        "been",
        "being",
        "direct",
        "does",
        "evidence",
        "explicit",
        "from",
        "have",
        "here",
        "into",
        "lack",
        "lacks",
        "less",
        "like",
        "line",
        "lines",
        "many",
        "mention",
        "mentioned",
        "missing",
        "more",
        "most",
        "none",
        "not",
        "only",
        "other",
        "role",
        "roles",
        "same",
        "such",
        "that",
        "their",
        "there",
        "these",
        "this",
        "those",
        "through",
        "with",
        "without",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", claim.lower())
        if len(token) >= 4 and token not in stopwords
    ]


def _find_gap_contradictions(summary: str, resume_text: str) -> list[str]:
    fields = _parse_summary_fields(summary)
    gaps_text = fields.get("Gaps", "")
    if not gaps_text:
        return []

    resume_lower = resume_text.lower()
    contradictions: list[str] = []
    for claim in _split_gap_claims(gaps_text):
        claim_lower = claim.lower()
        if not re.search(r"\b(no|not|without|lack|lacks|missing)\b", claim_lower):
            continue
        tokens = _extract_claim_tokens(claim)
        if not tokens:
            continue
        matched = [token for token in tokens if re.search(rf"\b{re.escape(token)}\b", resume_lower)]
        unique_matched = sorted(set(matched))
        overlap_ratio = len(unique_matched) / len(set(tokens))
        if len(unique_matched) >= 3 and overlap_ratio >= 0.6:
            matched_text = ", ".join(sorted(set(matched))[:8])
            contradictions.append(f"{claim} [matched: {matched_text}]")
    return contradictions


def _find_gap_overlap_claims(summary: str, resume_text: str) -> list[str]:
    fields = _parse_summary_fields(summary)
    gaps_text = fields.get("Gaps", "")
    if not gaps_text:
        return []

    resume_lower = resume_text.lower()
    overlap_claims: list[str] = []
    for claim in _split_gap_claims(gaps_text):
        claim_lower = claim.lower()
        if not re.search(r"\b(no|not|without|lack|lacks|missing)\b", claim_lower):
            continue
        tokens = _extract_claim_tokens(claim)
        if not tokens:
            continue
        matched = [token for token in tokens if re.search(rf"\b{re.escape(token)}\b", resume_lower)]
        unique_matched = sorted(set(matched))
        if unique_matched:
            matched_text = ", ".join(unique_matched[:8])
            overlap_claims.append(f"{claim} [matched: {matched_text}]")
    return overlap_claims


def _sanitize_contradicted_gaps(summary: str, contradictions: list[str]) -> str:
    fields = _parse_summary_fields(summary)
    required_fields = ("FitScore", "Strengths", "Gaps", "Tailor", "Recommendation")
    for key in required_fields:
        if key not in fields:
            raise FailFastError(f"Unable to sanitize summary; missing field: {key}")

    contradiction_claims = {
        item.split(" [matched:", 1)[0].strip().lower()
        for item in contradictions
        if item.strip()
    }
    gap_claims = _split_gap_claims(fields["Gaps"])
    kept_claims = [claim for claim in gap_claims if claim.strip().lower() not in contradiction_claims]
    if kept_claims:
        fields["Gaps"] = "; ".join(kept_claims)
    else:
        fields["Gaps"] = (
            "Limited direct evidence for some role-specific details; "
            "transferable evidence exists across customer service, retail operations, and process execution."
        )

    sanitized = (
        f"FitScore: {fields['FitScore']}\n"
        f"Strengths: {fields['Strengths']}\n"
        f"Gaps: {fields['Gaps']}\n"
        f"Tailor: {fields['Tailor']}\n"
        f"Recommendation: {fields['Recommendation']}\n"
    )
    return _normalize_output(sanitized)


def _call_openai_with_sdk(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return ""

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        temperature=0.0,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    output = getattr(response, "output_text", "") or ""
    return output.strip()


def _call_openai_with_http(api_key: str, model: str, system_prompt: str, user_prompt: str) -> str:
    if requests is None:
        raise FailFastError("Neither OpenAI SDK nor requests is available for API call.")

    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0.0,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
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


def _call_openai(api_key: str, model: str, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
    api_source = "SDK"
    raw_output = _call_openai_with_sdk(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    if raw_output:
        return api_source, raw_output

    api_source = "HTTP"
    raw_output = _call_openai_with_http(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    if not raw_output:
        raise FailFastError("OpenAI returned an empty response.")
    return api_source, raw_output


def _ascii_clean(value: str) -> str:
    return value.encode("ascii", "ignore").decode("ascii")


def _normalize_output(raw_output: str) -> str:
    required = ("FitScore", "Strengths", "Gaps", "Tailor", "Recommendation")
    parsed_blocks: Dict[str, list[str]] = {label: [] for label in required}
    current_label = ""

    for line in raw_output.splitlines():
        clean_line = _ascii_clean(line).strip()
        if not clean_line:
            continue

        match = re.match(r"^(FitScore|Strengths|Gaps|Tailor|Recommendation)\s*:\s*(.*)$", clean_line)
        if match:
            current_label = match.group(1)
            first_value = match.group(2).strip()
            if first_value:
                parsed_blocks[current_label].append(first_value)
            continue

        if current_label:
            parsed_blocks[current_label].append(clean_line)

    parsed: Dict[str, str] = {}
    for label in required:
        joined = " ".join(part.strip() for part in parsed_blocks[label] if part.strip()).strip()
        if joined:
            parsed[label] = joined

    for label in required:
        if label not in parsed:
            raise FailFastError(f"Model output missing required field: {label}")

    try:
        score_match = re.search(r"\d+", parsed["FitScore"])
        if not score_match:
            raise ValueError(parsed["FitScore"])
        score = int(score_match.group(0))
    except ValueError as exc:
        raise FailFastError(f"Invalid FitScore value: {parsed['FitScore']}") from exc
    if score < 0 or score > 100:
        raise FailFastError(f"FitScore out of range 0-100: {score}")

    recommendation_match = re.search(r"\b(Apply|Skip|Investigate)\b", parsed["Recommendation"], flags=re.IGNORECASE)
    recommendation = recommendation_match.group(1).title() if recommendation_match else ""
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


def _append_deep_log(
    *,
    model: str,
    api_source: str,
    job_file_path: Path,
    job_text: str,
    resume_file_path: Path,
    resume_text: str,
    raw_output: str,
    summary: str,
    error_text: str,
    audit_notes: str,
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    job_abs = job_file_path.resolve()
    resume_abs = resume_file_path.resolve()
    raw_clean = raw_output.strip()
    summary_clean = summary.strip()
    user_prompt = _user_prompt(job_text=job_text, resume_text=resume_text)
    error_block = error_text.strip() or "NONE"
    entry = (
        f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
        f"Model: {model}\n"
        f"ApiSource: {api_source}\n"
        f"JobFile: {job_abs}\n"
        f"JobLength: {len(job_text)}\n"
        f"ResumeFile: {resume_abs}\n"
        f"ResumeLength: {len(resume_text)}\n"
        "SystemPrompt:\n"
        f"{_system_prompt()}\n"
        "UserPrompt:\n"
        f"{user_prompt}\n"
        "JobText:\n"
        f"{job_text}\n"
        "ResumeText:\n"
        f"{resume_text}\n"
        "RawOutput:\n"
        f"{raw_clean}\n"
        "Normalized:\n"
        f"{summary_clean}\n"
        "Error:\n"
        f"{error_block}\n"
        "AuditNotes:\n"
        f"{audit_notes}\n"
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
    data = _parse_summary_fields(summary)

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
    raw_output = ""
    summary = ""
    error_text = ""
    audit_notes = "NONE"
    try:
        api_source, raw_output = _call_openai(
            api_key=api_key,
            model=args.model,
            system_prompt=_system_prompt(),
            user_prompt=_user_prompt(job_text=job_text, resume_text=resume_text),
        )
        summary = _normalize_output(raw_output)
        overlap_claims = _find_gap_overlap_claims(summary=summary, resume_text=resume_text)
        if overlap_claims:
            audit_notes = "INITIAL_GAP_OVERLAP_CLAIMS:\n" + "\n".join(f"- {item}" for item in overlap_claims)
            correction_source, correction_raw = _call_openai(
                api_key=api_key,
                model=args.model,
                system_prompt=_correction_system_prompt(),
                user_prompt=_correction_user_prompt(
                    job_text=job_text,
                    resume_text=resume_text,
                    current_summary=summary,
                    contradictions=overlap_claims,
                ),
            )
            api_source = f"{api_source}+{correction_source}"
            raw_output = raw_output + "\n\n[CorrectionPass]\n" + correction_raw
            summary = _normalize_output(correction_raw)
            remaining = _find_gap_contradictions(summary=summary, resume_text=resume_text)
            if remaining:
                summary = _sanitize_contradicted_gaps(summary=summary, contradictions=remaining)
                remaining = _find_gap_contradictions(summary=summary, resume_text=resume_text)
                if remaining:
                    raise FailFastError(
                        "Gap contradiction check failed after correction pass and sanitization: "
                        + "; ".join(remaining)
                    )
                audit_notes += "\nCORRECTION_PASS: PARTIAL\nSANITIZATION: APPLIED"
            else:
                audit_notes += "\nCORRECTION_PASS: RESOLVED"
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _append_deep_log(
            model=args.model,
            api_source=api_source,
            job_file_path=job_file_path,
            job_text=job_text,
            resume_file_path=RESUME_PATH,
            resume_text=resume_text,
            raw_output=raw_output,
            summary=summary,
            error_text=error_text,
            audit_notes=audit_notes,
        )

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
