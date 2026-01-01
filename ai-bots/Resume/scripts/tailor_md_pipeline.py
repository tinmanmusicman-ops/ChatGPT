#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start


_SCRIPT_DIR = Path(__file__).resolve().parent
_RESUME_DIR = _SCRIPT_DIR.parent
_REPO_ROOT = _find_repo_root(_SCRIPT_DIR)

DEFAULT_SOURCE_MD = _RESUME_DIR / "bot-assets" / "resume.md"
DEFAULT_TARGET_MD = _RESUME_DIR / "bot-assets" / "resume_target.md"

DEFAULT_RESUME_OUTPUT_DIR = Path(r"C:\!!!!!!!!!!!!!!!!!!!!!!!!!Stuff")
DEFAULT_OUTPUT_DIR = Path(os.environ.get("HSST_RESUME_OUTPUT_DIR", str(DEFAULT_RESUME_OUTPUT_DIR)))
DEFAULT_OUTPUT_PDF = DEFAULT_OUTPUT_DIR / "resume.pdf"
DEFAULT_RENDERER = _SCRIPT_DIR / "render_md_to_pdf.py"
DEFAULT_COVER_LETTER_MD = _RESUME_DIR / "bot-assets" / "cover_letter_target.md"
DEFAULT_COVER_LETTER_BASE_MD = _RESUME_DIR / "bot-assets" / "cover_letter_base.md"
DEFAULT_COVER_LETTER_PDF = DEFAULT_OUTPUT_DIR / "cover_letter.pdf"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "have",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class TailorPlan:
    allowed_indices: set[int]
    immutable_indices: set[int]


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_job_description(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is required to read PDF job descriptions.")
        doc = fitz.open(path)
        return "\n".join(doc.load_page(i).get_text("text") for i in range(doc.page_count)).strip()
    return _read_text(path).strip()


def _read_clipboard(*, allow_empty: bool = True) -> str:
    try:
        import pyperclip  # type: ignore
    except Exception:
        pyperclip = None

    if pyperclip is not None:
        try:
            content = pyperclip.paste()
            if isinstance(content, str):
                if content.strip():
                    return content.strip()
                if allow_empty:
                    return ""
        except Exception:
            pass

    if sys.platform.startswith("win"):
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                check=True,
            )
            if isinstance(result.stdout, str):
                if result.stdout.strip():
                    return result.stdout.strip()
                if allow_empty:
                    return ""
        except Exception:
            pass

    if allow_empty:
        return ""

    raise RuntimeError(
        "Unable to read job description from clipboard; copy the job description text to the clipboard and retry."
    )


def _is_hr(line: str) -> bool:
    return line.strip() == "---"

def _is_pagebreak(line: str) -> bool:
    stripped = line.strip()
    if stripped == r"\pagebreak":
        return True
    if stripped.lower() in ("<!-- pagebreak -->", "<!--pagebreak-->"):
        return True
    if stripped == "\f":
        return True
    return False

def _is_render_directive(line: str) -> bool:
    return bool(re.match(r"^\s*<!--\s*render\s*:\s*.*?-->\s*$", line, flags=re.IGNORECASE))


def _is_heading(line: str) -> bool:
    return bool(re.match(r"^\s*#{1,6}\s+\S", line))


def _is_date_line(line: str) -> bool:
    return bool(re.match(r"^\s*\*\d{4}\s*[–-]\s*\d{4}\*\s*$", line.strip()))


def _is_bullet(line: str) -> bool:
    return line.startswith("- ")


def _major_section(line: str) -> str | None:
    match = re.match(r"^\s*##\s+(.*?)\s*$", line)
    if not match:
        return None
    return match.group(1).strip()

def _compute_line_sections(lines: Sequence[str]) -> list[str | None]:
    sections: list[str | None] = [None] * len(lines)
    current: str | None = None
    for idx, line in enumerate(lines):
        section = _major_section(line)
        if section is not None:
            current = section
        sections[idx] = current
    return sections


def _compute_plan(lines: Sequence[str]) -> TailorPlan:
    immutable: set[int] = set()
    allowed: set[int] = set()
    current_section: str | None = None

    for index, line in enumerate(lines):
        section = _major_section(line)
        if section is not None:
            current_section = section

        if (
            line == ""
            or _is_hr(line)
            or _is_pagebreak(line)
            or _is_render_directive(line)
            or _is_heading(line)
            or _is_date_line(line)
        ):
            immutable.add(index)
            continue

        if current_section == "Operations & Customer Systems Specialist":
            allowed.add(index)
            continue

        if current_section in ("Core Skills", "Systems & Tools"):
            allowed.add(index)
            continue

        if current_section in ("Operational Improvements & Systems Work", "Professional Experience"):
            if _is_bullet(line):
                allowed.add(index)
                continue

        immutable.add(index)

    return TailorPlan(allowed_indices=allowed, immutable_indices=immutable)


def _format_ranges(indices: Iterable[int]) -> str:
    numbers = sorted(set(indices))
    if not numbers:
        return ""
    ranges: list[str] = []
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = n
    ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
    return ", ".join(ranges)


def _build_messages(job_description: str, original_md: str, plan: TailorPlan) -> list[dict[str, str]]:
    allowed_ranges = _format_ranges(plan.allowed_indices)
    original_lines = _normalize_newlines(original_md).split("\n")
    editable_lines = {str(index + 1): original_lines[index] for index in sorted(plan.allowed_indices)}

    system = (
        "You are performing STRICT, SOURCE-GROUNDED resume tailoring.\n"
        "The ONLY source of truth for facts/skills/experience is the provided resume Markdown.\n"
        "The job description may be used to reference the target company/role/mission/needs and to choose emphasis and wording.\n"
        "You MUST NOT introduce new claims of experience or responsibilities. If a detail is not supported by the resume text, do not add it.\n"
        "Inference is allowed only when framed as alignment, interest, or capability (not as something already done).\n"
        "Return ONLY JSON.\n"
    )
    user = (
        "Job description:\n"
        f"{job_description}\n\n"
        "Resume Markdown (source of truth):\n"
        f"{original_md}\n\n"
        "Constraints (must follow):\n"
        "- Do NOT add/remove/reorder sections.\n"
        "- Do NOT add/remove/reorder bullet items.\n"
        "- Do NOT change company names, titles, dates, or roles.\n"
        "- Do NOT add new tools, metrics, numbers, employers, locations, or responsibilities.\n"
        "- You MAY mention the target company name and role title ONLY as alignment/interest (never as prior experience).\n"
        "- If you mention the target company/role, do it ONLY in the summary section (not in experience bullets).\n"
        "- Use alignment phrasing like \"aligned with my background in...\", \"drawing on my experience with...\", \"this role complements my work in...\".\n"
        "- You may ONLY edit text in-place (summary, keywords, minor bullet wording).\n"
        "- Preserve blank lines and horizontal rules exactly.\n"
        "- Preserve heading lines exactly.\n"
        "- Preserve date lines exactly.\n"
        "- Preserve bullet prefixes exactly: if a line begins with \"- \", keep \"- \" unchanged.\n"
        f"- Only these line numbers may change: {allowed_ranges}.\n\n"
        "Editable lines (line_number -> current_line_text):\n"
        f"{json.dumps(editable_lines, ensure_ascii=False, indent=2)}\n\n"
        "Output format (JSON only):\n"
        "{\"edits\": {\"<line_number>\": \"<replacement line>\", ...}}\n"
        "- `edits` MUST be present (use `{}` if no changes).\n\n"
        "Rules for edits:\n"
        "- Only include keys for lines you want to change.\n"
        "- Keys must be line numbers from the editable set.\n"
        "- Values must be a single line of text (no newline characters).\n"
        "- Keep meaning the same; only rephrase or tighten.\n"
        "- Do not include markdown fences.\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_first_json_object(text: str) -> dict[str, Any]:
    trimmed = (text or "").strip()
    if not trimmed:
        raise ValueError("Empty model response.")
    try:
        parsed = json.loads(trimmed)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = trimmed.find("{")
    end = trimmed.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not contain a JSON object.")
    parsed = json.loads(trimmed[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed


def _tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", text).strip().lower()
    if not cleaned:
        return []
    return [t for t in cleaned.split() if t and t not in _STOPWORDS]


def _jaccard_similarity(a: str, b: str) -> float:
    a_set = set(_tokenize(a))
    b_set = set(_tokenize(b))
    if not a_set and not b_set:
        return 1.0
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


@dataclass(frozen=True)
class AllowedTerms:
    capitalized_words: set[str]
    acronyms: set[str]


def _extract_allowed_terms(text: str) -> AllowedTerms:
    normalized = _normalize_newlines(text)
    cap_words = set(re.findall(r"\b[A-Z][a-z][A-Za-z0-9&/.-]*\b", normalized))
    acronyms = set(re.findall(r"\b[A-Z]{2,}\b", normalized))
    return AllowedTerms(capitalized_words=cap_words, acronyms=acronyms)

def _merge_allowed_terms(a: AllowedTerms, b: AllowedTerms) -> AllowedTerms:
    return AllowedTerms(
        capitalized_words=set(a.capitalized_words) | set(b.capitalized_words),
        acronyms=set(a.acronyms) | set(b.acronyms),
    )


def _numbers_in(text: str) -> list[str]:
    return re.findall(r"(?<!\w)[#]?\d+(?:[.,]\d+)?%?(?!\w)", text)


def _audit_line(src: str, out: str, *, allowed: AllowedTerms, similarity_threshold: float, line_no: str) -> list[str]:
    issues: list[str] = []

    if _numbers_in(src) != _numbers_in(out):
        issues.append("numeric tokens changed")

    src_caps = set(re.findall(r"\b[A-Z][a-z][A-Za-z0-9&/.-]*\b", src))
    out_caps = set(re.findall(r"\b[A-Z][a-z][A-Za-z0-9&/.-]*\b", out))
    new_caps = {w for w in out_caps - src_caps if w not in allowed.capitalized_words}
    new_caps -= {"Dear", "Hiring", "Manager", "Sincerely"}
    # Ignore sentence-starter capitalization differences.
    first_word = re.match(r"^\s*([A-Z][a-z][A-Za-z0-9&/.-]*)\b", out)
    if first_word:
        new_caps.discard(first_word.group(1))
    if new_caps:
        issues.append(f"new capitalized terms: {', '.join(sorted(new_caps))}")

    src_acr = set(re.findall(r"\b[A-Z]{2,}\b", src))
    out_acr = set(re.findall(r"\b[A-Z]{2,}\b", out))
    new_acr = {w for w in out_acr - src_acr if w not in allowed.acronyms}
    if new_acr:
        issues.append(f"new acronyms: {', '.join(sorted(new_acr))}")

    sim = _jaccard_similarity(src, out)
    if sim < similarity_threshold:
        issues.append(f"low similarity ({sim:.2f} < {similarity_threshold:.2f})")

    if issues:
        return [f"line {line_no}: " + "; ".join(issues)]
    return []


def _coerce_edits(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Returns an edits dict if present, an empty dict if payload is empty, or None if unusable.
    """
    if not payload:
        return {}
    for key in ("edits", "line_edits", "changes", "replacements"):
        candidate = payload.get(key)
        if candidate is None:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def _reorder_bullets_source_only(md_text: str, job_description: str) -> str:
    lines = _normalize_newlines(md_text).split("\n")
    jd_tokens = _tokenize(job_description)
    weights: dict[str, int] = {}
    for tok in jd_tokens:
        weights[tok] = weights.get(tok, 0) + 1

    def score_bullet(line: str) -> int:
        tokens = _tokenize(line[2:] if line.startswith("- ") else line)
        return sum(weights.get(t, 0) for t in set(tokens))

    current_section: str | None = None
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        section = _major_section(line)
        if section is not None:
            current_section = section

        if current_section not in ("Operational Improvements & Systems Work", "Professional Experience"):
            out_lines.append(line)
            i += 1
            continue

        if not _is_bullet(line):
            out_lines.append(line)
            i += 1
            continue

        block_start = i
        while i < len(lines) and _is_bullet(lines[i]):
            i += 1
        block = lines[block_start:i]
        scored = [(score_bullet(b), idx, b) for idx, b in enumerate(block)]
        scored.sort(key=lambda t: (-t[0], t[1]))
        out_lines.extend([b for _, _, b in scored])

    return "\n".join(out_lines)


@dataclass(frozen=True)
class TargetInfo:
    role_title: str
    company_name: str
    context: str


def _extract_target_info(job_description: str) -> TargetInfo:
    jd = _normalize_newlines(job_description)
    lines = [ln.strip() for ln in jd.split("\n") if ln.strip()]

    role_title = ""
    for line in lines[:25]:
        if len(line) > 80:
            continue
        if re.search(r"\b(job type|pay rate|posted|apply|requirements)\b", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^[A-Za-z][A-Za-z &/+-]{2,}$", line):
            role_title = line
            break
    if not role_title:
        match = re.search(r"\bseeking\s+(?:a|an)\s+(.+?)\s+to\b", jd, flags=re.IGNORECASE)
        role_title = match.group(1).strip() if match else "this role"

    company_name = ""
    if re.search(r"\bRobert Half\b", jd):
        company_name = "Robert Half"
    if not company_name:
        for pattern in (
            r"\b(?:position|role|opportunity)\s+with\s+([A-Z][A-Za-z0-9&.,' -]{2,80})",
            r"\bapply\s+for\s+the\s+.*?\s+with\s+([A-Z][A-Za-z0-9&.,' -]{2,80})",
        ):
            match = re.search(pattern, jd, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip().strip(",. ")
            candidate = re.split(r"[\n\r]", candidate)[0].strip()
            if candidate and "Hiring Manager" not in candidate:
                company_name = candidate
                break
    if not company_name:
        company_name = "your organization"

    context = ""
    if re.search(r"\bmission-driven\b", jd, flags=re.IGNORECASE) and re.search(r"\bnonprofit\b", jd, flags=re.IGNORECASE):
        context = "supporting a mission-driven nonprofit organization"
        if re.search(r"\bSan Diego\b", jd, flags=re.IGNORECASE):
            context += " in San Diego"

    return TargetInfo(role_title=role_title, company_name=company_name, context=context)


def _audit_cover_letter(cover_letter_md: str, *, resume_md: str, job_description: str, target: TargetInfo) -> None:
    allowed = _merge_allowed_terms(_extract_allowed_terms(resume_md), _extract_allowed_terms(job_description))

    lower = cover_letter_md.lower()
    company_norm = target.company_name.strip().lower()
    role_norm = target.role_title.strip().lower()

    if company_norm and company_norm not in {"your organization", "your team"}:
        if company_norm not in lower:
            raise ValueError("Cover letter did not include the target company name.")

    def role_context_present() -> bool:
        if not role_norm or role_norm == "this role":
            return True
        if role_norm in lower:
            return True

        title_tokens = [t for t in _tokenize(target.role_title) if t not in {"role", "position", "opportunity", "job"}]
        if not title_tokens:
            return True

        cover_tokens = set(_tokenize(cover_letter_md))
        hits = len(set(title_tokens) & cover_tokens)

        if hits >= 2:
            return True
        if hits >= 1 and any(x in lower for x in (" role", " position", " opportunity", " job")):
            return True
        return False

    if not role_context_present():
        raise ValueError("Cover letter did not include target role context.")

    # Reject common template placeholders (but do not fail for normal wording variation).
    placeholder_patterns = [
        r"\byour name\b",
        r"\bname here\b",
        r"\bcompany name\b",
        r"\baddress here\b",
        r"\b\[your name\]\b",
        r"\b\[company name\]\b",
        r"\b\[address\]\b",
        r"\b\[phone\]\b",
        r"\b\[email\]\b",
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, lower):
            raise ValueError("Cover letter contains template placeholder text.")

    allowed_numbers = set(_numbers_in(resume_md)) | set(_numbers_in(job_description))
    output_numbers = set(_numbers_in(cover_letter_md))
    extras = output_numbers - allowed_numbers
    if extras:
        raise ValueError(f"Cover letter contains unsupported numeric tokens: {', '.join(sorted(extras))}")

    output_acr = set(re.findall(r"\b[A-Z]{2,}\b", cover_letter_md))
    new_acr = sorted(output_acr - set(allowed.acronyms))
    if new_acr:
        raise ValueError(f"Cover letter contains unsupported acronyms: {', '.join(new_acr[:12])}")

    resume_lower = resume_md.lower()
    cover_lower = cover_letter_md.lower()
    alignment_markers = (
        "aligned with",
        "drawing on",
        "complements",
        "eager to",
        "interested in",
        "excited to",
        "ready to",
        "able to",
        "capable of",
        "well-suited",
        "fits well",
        "can ",
        "would ",
    )
    claim_markers = (
        "i have ",
        "i've ",
        "i managed",
        "i supported",
        "i coordinated",
        "i organized",
        "i scheduled",
        "i prepared",
        "i maintained",
        "i handled",
        "i led",
        "i owned",
        "i oversaw",
        "my experience includes",
        "i am experienced",
    )
    risky_terms = (
        "calendar",
        "calendars",
        "scheduling",
        "travel",
        "grant",
        "grants",
        "proposal",
        "proposals",
        "board",
        "donor",
        "donors",
        "fundraising",
        "outreach",
        "onboarding",
        "meeting minutes",
        "confidential",
        "compliance",
        "crm",
        "database",
        "databases",
    )

    def split_sentences(text: str) -> list[str]:
        cleaned = _normalize_newlines(text)
        parts = re.split(r"(?<=[.!?])\s+|\n{2,}", cleaned)
        return [p.strip() for p in parts if p.strip()]

    sentences = split_sentences(cover_lower)
    for term in risky_terms:
        if term not in cover_lower:
            continue
        if term in resume_lower:
            continue
        for sentence in sentences:
            if term not in sentence:
                continue
            if any(marker in sentence for marker in alignment_markers):
                continue
            if any(marker in sentence for marker in claim_markers):
                raise ValueError(f"Cover letter claims experience with '{term}' not supported by resume.")

    # Only fail on new-employer mentions when they look like employers.
    # Examples: "role with X", "position with X", "worked at X"
    employer_patterns = [
        r"\b(?:role|position|opportunity|job)\s+with\s+([A-Z][A-Za-z0-9&.,' -]{2,80})",
        r"\bworked\s+at\s+([A-Z][A-Za-z0-9&.,' -]{2,80})",
        r"\bemployed\s+at\s+([A-Z][A-Za-z0-9&.,' -]{2,80})",
    ]
    for pattern in employer_patterns:
        for match in re.finditer(pattern, cover_letter_md):
            phrase = (match.group(1) or "").strip().strip(",. ")
            if not phrase:
                continue
            phrase_lower = phrase.lower()
            if company_norm and company_norm in phrase_lower:
                continue
            if phrase_lower in {"your organization", "your team"}:
                continue
            if phrase_lower in resume_lower or phrase_lower in job_description.lower():
                continue
            raise ValueError(f"Cover letter references employer '{phrase}' not supported by resume/job description.")


def _draft_cover_letter_openai(
    *,
    resume_md: str,
    cover_letter_base_md: str | None,
    job_description: str,
    target: TargetInfo,
    model: str,
    temperature: float,
) -> str:
    if OpenAI is None:
        raise RuntimeError("openai package is required for cover letter drafting but is not installed.")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for cover letter drafting.")

    base_block = ""
    if cover_letter_base_md:
        base_block = f"\n\nCover letter base (optional template):\n{cover_letter_base_md}\n"

    system = (
        "Write a targeted cover letter using ONLY supported facts from the resume.\n"
        "You may reference the target company/role/mission/needs from the job description.\n"
        "Do NOT invent experience; if not explicitly in the resume, frame as alignment, interest, or capability.\n"
        "Output Markdown only (no code fences).\n"
    )
    user = (
        f"Target company: {target.company_name}\n"
        f"Target role: {target.role_title}\n"
        f"Context: {target.context}\n\n"
        f"Job description:\n{job_description}\n\n"
        f"Resume (source of truth):\n{resume_md}\n"
        f"{base_block}\n"
        "Requirements:\n"
        "- Start with: \"# Dear Hiring Manager,\"\n"
        "- Explicitly name the target company and role in the first paragraph.\n"
        "- Use alignment phrasing like \"aligned with my background in...\" / \"drawing on my experience with...\" / \"this role complements my work in...\".\n"
        "- 3-5 short paragraphs, then \"Sincerely,\" and the name.\n"
        "- Do NOT add metrics not present in the resume.\n"
    )

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=1200,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (resp.choices[0].message.content or "").strip()


def _generate_cover_letter_md(resume_md: str, job_description: str) -> str:
    lines = _normalize_newlines(resume_md).split("\n")
    name = "Timothy B. Inman"
    for line in lines:
        if line.startswith("# "):
            candidate = line[2:].strip()
            if candidate:
                name = candidate
            break

    summary = ""
    current_section: str | None = None
    for idx, line in enumerate(lines):
        section = _major_section(line)
        if section is not None:
            current_section = section
            continue
        if current_section == "Operations & Customer Systems Specialist":
            if line.strip() and not _is_hr(line) and not _is_heading(line):
                summary = line.strip()
                break

    bullets: list[str] = []
    current_section = None
    for line in lines:
        section = _major_section(line)
        if section is not None:
            current_section = section
            continue
        if current_section in ("Operational Improvements & Systems Work", "Professional Experience") and _is_bullet(line):
            bullets.append(line[2:].strip())

    jd_tokens = set(_tokenize(job_description))
    ranked: list[tuple[int, str]] = []
    for bullet in bullets:
        score = len(set(_tokenize(bullet)) & jd_tokens)
        ranked.append((score, bullet))
    ranked.sort(key=lambda t: (-t[0], bullets.index(t[1])))
    selected = [b for _, b in ranked[:4] if b]

    def ensure_sentence(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return stripped
        if stripped.endswith((".", "!", "?")):
            return stripped
        return stripped + "."

    paragraphs: list[str] = []
    target = _extract_target_info(job_description)
    role_title = target.role_title.strip()
    company_name = target.company_name.strip() or "your organization"
    if not job_description.strip() or role_title.lower() in {"this role", "the role"}:
        opening = f"I am writing to express my interest in opportunities with {company_name}"
    elif re.search(r"\b(role|position|opportunity|job)\b", role_title, flags=re.IGNORECASE):
        opening = f"I am applying for the {role_title} with {company_name}"
    else:
        opening = f"I am applying for the {role_title} role with {company_name}"
    if target.context:
        opening += f", {target.context}"
    paragraphs.append(ensure_sentence(opening))

    if summary:
        paragraphs.append(ensure_sentence(f"Aligned with my background in {summary}"))
    if selected:
        paragraphs.append("Drawing on my experience with " + " ".join(ensure_sentence(b) for b in selected))
    paragraphs.append("Thank you for your time and consideration. I welcome the opportunity to discuss how I can contribute.")

    return "\n".join(
        [
            "# Dear Hiring Manager,",
            "",
            *[p for para in paragraphs for p in (para, "")],
            "Sincerely,",
            name,
            "",
        ]
    )


def _tailor_markdown(md_text: str, job_description: str, *, model: str, temperature: float) -> str:
    if OpenAI is None or not os.environ.get("OPENAI_API_KEY", "").strip():
        print("[INFO] OPENAI_API_KEY not set (or openai missing); using source-only tailoring (no rewording).", flush=True)
        return _reorder_bullets_source_only(md_text, job_description)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip())
    lines = _normalize_newlines(md_text).split("\n")
    line_sections = _compute_line_sections(lines)
    plan = _compute_plan(lines)
    base_messages = _build_messages(job_description, md_text, plan)
    allowed = _merge_allowed_terms(_extract_allowed_terms(md_text), _extract_allowed_terms(job_description))
    target = _extract_target_info(job_description)

    payload: dict[str, Any] | None = None
    edits: dict[str, Any] | None = None

    for attempt in range(2):
        messages = list(base_messages)
        if attempt:
            messages.append(
                {
                    "role": "user",
                    "content": "Your previous response was invalid. Return JSON only with an `edits` object (use `{}` if no edits).",
                }
            )
        try:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=temperature if attempt == 0 else 0.0,
                    max_tokens=6000,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            except TypeError:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=temperature if attempt == 0 else 0.0,
                    max_tokens=6000,
                    messages=messages,
                )
            content = resp.choices[0].message.content or ""
            payload = _extract_first_json_object(content)
            edits = _coerce_edits(payload)
            if edits is None:
                continue
            break
        except Exception as exc:
            payload = None
            edits = None
            print(f"[WARN] Tailoring model call failed; falling back to source-only tailoring. ({exc})", flush=True)
            return _reorder_bullets_source_only(md_text, job_description)

    if edits is None:
        print("[WARN] Model response missing usable `edits`; falling back to source-only tailoring.", flush=True)
        return _reorder_bullets_source_only(md_text, job_description)

    allowed_line_numbers = {str(i + 1) for i in plan.allowed_indices}
    updated = list(lines)
    audit_issues: list[str] = []

    for line_no_raw, replacement in edits.items():
        line_no = str(line_no_raw).strip()
        if line_no not in allowed_line_numbers:
            audit_issues.append(f"line {line_no}: edit provided for non-editable line; ignored")
            continue
        if not isinstance(replacement, str):
            audit_issues.append(f"line {line_no}: replacement is not a string; ignored")
            continue
        if "\n" in replacement or "\r" in replacement:
            audit_issues.append(f"line {line_no}: replacement contains newline; ignored")
            continue

        index = int(line_no) - 1
        src = lines[index]
        out = replacement
        section = line_sections[index]

        if _is_bullet(src):
            if not out.startswith("- "):
                audit_issues.append(f"line {line_no}: bullet marker changed; ignored")
                continue
            if out == "- ":
                audit_issues.append(f"line {line_no}: invalid bullet format; ignored")
                continue
            if section in ("Operational Improvements & Systems Work", "Professional Experience"):
                src_lower = src.lower()
                out_lower = out.lower()
                company = target.company_name.strip()
                role = target.role_title.strip()
                if company and company.lower() in out_lower and company.lower() not in src_lower:
                    audit_issues.append(f"line {line_no}: introduced target company name inside a bullet")
                    continue
                if role and role.lower() in out_lower and role.lower() not in src_lower:
                    audit_issues.append(f"line {line_no}: introduced target role title inside a bullet")
                    continue

        similarity_threshold = 0.45 if _is_bullet(src) else 0.35
        issues = _audit_line(src, out, allowed=allowed, similarity_threshold=similarity_threshold, line_no=line_no)
        if issues:
            audit_issues.extend(issues)
            continue
        updated[index] = out

    for index, src in enumerate(lines):
        out = updated[index]
        if index in plan.immutable_indices and out != src:
            raise ValueError(f"Immutable line changed at {index + 1}.")
        if index not in plan.allowed_indices and out != src:
            raise ValueError(f"Unexpected change outside allowed lines at {index + 1}.")

    if audit_issues:
        print("[WARN] Truth-audit rejected some edits:", flush=True)
        for issue in audit_issues[:20]:
            print(f"[WARN] - {issue}", flush=True)
        if len(audit_issues) > 20:
            print(f"[WARN] - ... and {len(audit_issues) - 20} more", flush=True)
    return "\n".join(updated)


def _render(md_path: Path, pdf_path: Path, renderer_path: Path) -> None:
    if not renderer_path.exists():
        raise FileNotFoundError(f"Missing renderer script: {renderer_path}")
    if (
        md_path.resolve() == DEFAULT_TARGET_MD.resolve()
        and pdf_path.resolve() == DEFAULT_OUTPUT_PDF.resolve()
        and renderer_path.resolve() == DEFAULT_RENDERER.resolve()
    ):
        subprocess.run([sys.executable, str(renderer_path)], check=True)
        return
    subprocess.run([sys.executable, str(renderer_path), str(md_path), str(pdf_path)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy → tailor Markdown (text-only) → render PDF.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_MD)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET_MD)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_OUTPUT_PDF)
    parser.add_argument("--renderer", type=Path, default=DEFAULT_RENDERER)
    parser.add_argument("--cover-letter-md", type=Path, default=DEFAULT_COVER_LETTER_MD)
    parser.add_argument("--cover-letter-base-md", type=Path, default=DEFAULT_COVER_LETTER_BASE_MD)
    parser.add_argument("--cover-letter-pdf", type=Path, default=DEFAULT_COVER_LETTER_PDF)
    parser.add_argument("--job-description-file", type=Path, default=None)
    parser.add_argument("--model", type=str, default="gpt-4.1")
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    print("[INFO] Targeted resume pipeline started.", flush=True)

    args.pdf.parent.mkdir(parents=True, exist_ok=True)
    args.cover_letter_pdf.parent.mkdir(parents=True, exist_ok=True)

    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(args.source.read_text(encoding="utf-8"), encoding="utf-8")

    if args.job_description_file is not None:
        print("[WARN] --job-description-file is ignored; clipboard-only mode is enabled.", flush=True)
    try:
        job_description = _read_clipboard(allow_empty=True)
    except Exception as exc:
        print(f"[WARN] Unable to read clipboard; proceeding without a job description. ({exc})", flush=True)
        job_description = ""

    generic_mode = not job_description.strip()
    if generic_mode:
        print("[INFO] Clipboard is empty; generating a generic resume (no AI tailoring).", flush=True)
    else:
        print("[INFO] Job description loaded from clipboard.", flush=True)

    if generic_mode:
        tailored_md = args.target.read_text(encoding="utf-8")
    else:
        print("[INFO] Tailoring resume.md -> resume_target.md (text-only).", flush=True)
        try:
            tailored_md = _tailor_markdown(
                args.target.read_text(encoding="utf-8"),
                job_description,
                model=args.model,
                temperature=args.temperature,
            )
        except Exception as exc:
            print(f"[WARN] Tailoring failed; using source-only tailoring. ({exc})", flush=True)
            tailored_md = _reorder_bullets_source_only(args.target.read_text(encoding="utf-8"), job_description)
    args.target.write_text(tailored_md, encoding="utf-8")

    print("[INFO] Generating cover_letter_target.md (source-grounded).", flush=True)
    cover_letter_base_md: str | None = None
    if args.cover_letter_base_md is not None and args.cover_letter_base_md.exists():
        cover_letter_base_md = args.cover_letter_base_md.read_text(encoding="utf-8")

    target = _extract_target_info(job_description)
    if (not generic_mode) and OpenAI is not None and os.environ.get("OPENAI_API_KEY", "").strip():
        try:
            cover_letter_md = _draft_cover_letter_openai(
                resume_md=tailored_md,
                cover_letter_base_md=cover_letter_base_md,
                job_description=job_description,
                target=target,
                model=args.model,
                temperature=args.temperature,
            )
        except Exception as exc:
            print(f"[WARN] Cover letter drafting failed; using source-only cover letter. ({exc})", flush=True)
            cover_letter_md = _generate_cover_letter_md(tailored_md, job_description)
    else:
        cover_letter_md = _generate_cover_letter_md(tailored_md, job_description)

    if not generic_mode:
        try:
            _audit_cover_letter(cover_letter_md, resume_md=tailored_md, job_description=job_description, target=target)
        except Exception as exc:
            print(f"[WARN] Cover letter truth-audit failed; using source-only cover letter. ({exc})", flush=True)
            cover_letter_md = _generate_cover_letter_md(tailored_md, job_description)
            try:
                _audit_cover_letter(cover_letter_md, resume_md=tailored_md, job_description=job_description, target=target)
            except Exception as exc2:
                print(
                    f"[WARN] Cover letter audit still failing; proceeding with source-only cover letter. ({exc2})",
                    flush=True,
                )
    args.cover_letter_md.parent.mkdir(parents=True, exist_ok=True)
    args.cover_letter_md.write_text(
        cover_letter_md + ("" if cover_letter_md.endswith("\n") else "\n"),
        encoding="utf-8",
    )

    print("[INFO] Rendering resume_target.md -> resume.pdf.", flush=True)
    _render(args.target, args.pdf, args.renderer)

    print("[INFO] Rendering cover letter -> cover_letter.pdf.", flush=True)
    _render(args.cover_letter_md, args.cover_letter_pdf, args.renderer)

    files = [{"name": args.pdf.name, "label": "Resume PDF"}]
    if args.cover_letter_pdf.exists():
        files.append({"name": args.cover_letter_pdf.name, "label": "Cover Letter PDF"})
    print(json.dumps({"files": files}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
