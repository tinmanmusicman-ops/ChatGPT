#!/usr/bin/env python3
"""
Resume Engine
==============

Reads a job description from the clipboard, loads the base resume data, calls an
AI model, and writes the tailored resume (TXT and PDF) plus the cover letter.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]
    OPENAI_IMPORT_ERROR = exc  # type: ignore[name-defined]
else:
    OPENAI_IMPORT_ERROR = None  # type: ignore[name-defined]

EM_DASH = "\u2014"
client: Optional[OpenAI] = None

ROOT_DIR = Path(__file__).resolve().parent.parent
BOT_ASSETS_DIR = ROOT_DIR / "bot-assets"
CONFIG_PATH = BOT_ASSETS_DIR / "config.json"
RESUME_TEXT_OUTPUT_PATH: Optional[Path] = None
PDF_OUTPUT_PATH: Optional[Path] = None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    config = load_json(path)
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a JSON object at the top level.")
    return config


def configure_logger(config: Dict[str, Any]) -> logging.Logger:
    logging_enabled = bool(config.get("logging", False))
    debug_mode = bool(config.get("debug", False))
    level = logging.DEBUG if debug_mode else (logging.INFO if logging_enabled else logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logger = logging.getLogger("ResumeEngine")
    logger.setLevel(level)
    return logger


def read_clipboard(logger: logging.Logger) -> str:
    command = ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    logger.debug("Reading clipboard using PowerShell: %s", " ".join(command))
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise RuntimeError("PowerShell is required to read the clipboard on this machine.")

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"Clipboard access failed: {stderr or 'unknown error'}")

    payload = completed.stdout.strip()
    if not payload:
        raise RuntimeError("Clipboard is empty. Please copy the job description before running.")
    return payload


def build_prompt(job_description: str, base_resume: Dict[str, Any]) -> str:
    base_json = json.dumps(base_resume, indent=2, ensure_ascii=False)
    prompt = (
        "Base resume JSON:\n"
        f"{base_json}\n\n"
        "Job description:\n"
        f"{job_description.strip()}\n\n"
        "Return a JSON object that contains exactly two keys: "
        "`resume` and `cover_letter`. Do not wrap the JSON in markdown or code fence. "
        "Each value should be a polished, fully formatted document adapted to the job."
    )
    return prompt


def get_openai_client(logger: logging.Logger) -> OpenAI:
    global client
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK import failed.")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required.")
    client = OpenAI(api_key=api_key)
    logger.debug("OpenAI client initialized with provided API key.")
    return client


def generate_documents(
    base_resume: Dict[str, Any],
    job_description: str,
    config: Dict[str, Any],
    logger: logging.Logger,
) -> Dict[str, str]:
    openai_client = get_openai_client(logger)

    messages = [
        {
            "role": "system",
            "content": "You are an expert resume writer who adapts a base resume "
            "JSON payload into tailored resumes and cover letters based on job descriptions.",
        },
        {
            "role": "user",
            "content": build_prompt(job_description, base_resume),
        },
    ]

    model = str(config.get("model", "gpt-4.1"))
    temperature = float(config.get("temperature", 0.2))
    max_tokens = int(config.get("max_tokens", 8000))
    logger.debug(
        "Calling model %s with temperature=%s max_tokens=%s", model, temperature, max_tokens
    )

    response = openai_client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=messages,
    )

    content = response.choices[0].message.content
    logger.debug("Model response: %s", content[:500])
    return extract_json_payload(content)


def extract_json_payload(text: str) -> Dict[str, str]:
    trimmed = text.strip()
    if not trimmed:
        raise ValueError("Received an empty response from the AI model.")

    try:
        payload = json.loads(trimmed)
    except json.JSONDecodeError:
        start = trimmed.find("{")
        end = trimmed.rfind("}")
        if start == -1 or end == -1:
            raise
        payload = json.loads(trimmed[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("AI response JSON must be an object.")

    resume_text = str(payload.get("resume", "")).strip()
    cover_letter_text = str(payload.get("cover_letter", "")).strip()
    if not resume_text or not cover_letter_text:
        raise ValueError("Both `resume` and `cover_letter` fields must be non-empty.")

    return {"resume": resume_text, "cover_letter": cover_letter_text}


def normalize_em_dashes(text: str) -> str:
    normalized = text.replace("--", EM_DASH)
    normalized = normalized.replace("–", EM_DASH)
    normalized = normalized.replace(" - ", f" {EM_DASH} ")
    return normalized


HEADING_TITLES = {
    "SUMMARY": ["SUMMARY"],
    "Key Skills": ["Key Skills"],
    "Recent Achievements": ["Recent Achievements"],
    "Professional Experience": ["Professional Experience"],
    "EDUCATION": ["EDUCATION"],
    "Relevant Project Experience": ["Relevant Project Experience"],
    "Certifications": ["Certifications"],
    "References": ["References available upon request.", "References available upon request"],
}

ORDERED_SECTIONS = [
    "SUMMARY",
    "Key Skills",
    "Recent Achievements",
    "Professional Experience",
    "EDUCATION",
    "Certifications",
    "References",
]

BASE_RESUME_PATH = BOT_ASSETS_DIR / "base_resume.json"


def _heading_candidate(line: str) -> tuple[str, bool] | tuple[None, bool]:
    stripped = line.strip()
    if not stripped:
        return None, False
    candidate = stripped.rstrip(":")
    for canonical, options in HEADING_TITLES.items():
        for option in options:
            if candidate.lower() == option.lower():
                return canonical, canonical == "References"
    return None, False


def parse_resume_into_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in text.replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            current_section = None
            continue
        heading, is_reference = _heading_candidate(line)
        if heading is None:
            candidate = line.rstrip(":")
            if line.endswith(":") and candidate:
                heading = candidate
            elif line.isupper() and len(line) > 3:
                heading = candidate
        if heading:
            current_section = heading
            if is_reference:
                sections.setdefault("References", []).append("References available upon request.")
                current_section = None
            continue
        if current_section:
            sections.setdefault(current_section, []).append(line)
    return sections


def _flush_bullets(bullets: list[str], story: list, body_style: ParagraphStyle) -> None:
    if not bullets:
        return
    bullet_items = [
        ListItem(Paragraph(re.sub(r"^[-•]+\s*", "", line), body_style))
        for line in bullets
    ]
    story.append(
        ListFlowable(
            bullet_items,
            bulletType="bullet",
            leftIndent=0.25 * inch,
            bulletFontName="Helvetica",
            bulletFontSize=11,
        )
    )


def load_base_resume_data() -> Dict[str, Any]:
    if not BASE_RESUME_PATH.exists():
        return {}
    return load_json(BASE_RESUME_PATH)


def build_summary_lines(base_resume: Dict[str, Any]) -> list[str]:
    summary = base_resume.get("summary")
    return [summary] if summary else []


def build_skills_lines(base_resume: Dict[str, Any]) -> list[str]:
    return [f"- {skill}" for skill in base_resume.get("skills", [])]


def build_achievements_lines(base_resume: Dict[str, Any]) -> list[str]:
    return [f"- {item}" for item in base_resume.get("achievements_2024_2025", [])]


def build_experience_lines(base_resume: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for job in base_resume.get("experience", []):
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "")
        start = job.get("start", "")
        end = job.get("end", "")
        header = f"{title} — {company}, {location} ({start} — {end})"
        lines.append(header)
        for highlight in job.get("highlights", []):
            lines.append(f"- {highlight}")
    return lines


def build_education_lines(base_resume: Dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for entry in base_resume.get("education", []):
        degree = entry.get("degree", entry.get("program", ""))
        school = entry.get("school", entry.get("provider", ""))
        location = entry.get("location", "")
        date = entry.get("date", "")
        summary_line = f"{degree} — {school}"
        if location:
            summary_line += f", {location}"
        if date:
            summary_line += f" ({date})"
        lines.append(summary_line)
    return lines


def build_certifications_lines(base_resume: Dict[str, Any]) -> list[str]:
    return [f"- {cert}" for cert in base_resume.get("certifications", [])]


def build_references_lines(base_resume: Dict[str, Any]) -> list[str]:
    references = base_resume.get("references")
    if references:
        return references if isinstance(references, list) else [references]
    return ["References available upon request."]
def _looks_like_structured_data_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped[0] in "{[":
        return True
    if "{" in stripped or "}" in stripped or "[" in stripped or "]" in stripped:
        return True
    return False


def extract_name(text: str, base_resume: Dict[str, Any]) -> str:
    fallback = base_resume.get("name")
    for raw_line in text.replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading, _ = _heading_candidate(line)
        if heading:
            continue
        if _looks_like_structured_data_line(line):
            continue
        return line
    return fallback or "NAME"


def save_pdf_resume(text: str, output_path: Path) -> None:
    normalized = normalize_em_dashes(text)
    base_resume = load_base_resume_data()
    sections = parse_resume_into_sections(normalized)
    name = extract_name(normalized, base_resume)

    name_style = ParagraphStyle(
        "NameStyle",
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        alignment=TA_LEFT,
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyText",
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=4,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    story: list = [Paragraph(name, name_style), Spacer(1, 6)]
    combined_sections: dict[str, list[str]] = {}

    def fallback_lines(heading: str) -> list[str]:
        if heading == "SUMMARY":
            return build_summary_lines(base_resume)
        if heading == "Key Skills":
            return build_skills_lines(base_resume)
        if heading == "Recent Achievements":
            return build_achievements_lines(base_resume)
        if heading == "Professional Experience":
            return build_experience_lines(base_resume)
        if heading == "EDUCATION":
            return build_education_lines(base_resume)
        if heading == "Certifications":
            return build_certifications_lines(base_resume)
        if heading == "References":
            return build_references_lines(base_resume)
        return []

    for heading in ORDERED_SECTIONS:
        combined_sections[heading] = sections.get(heading) or fallback_lines(heading)

    def append_section(section_heading: str, section_lines: list[str]) -> None:
        if not section_lines:
            return
        story.append(Paragraph(section_heading, heading_style))
        bullets: list[str] = []
        for line in section_lines:
            if re.match(r"^[-•]\s+", line):
                bullets.append(line)
                continue
            _flush_bullets(bullets, story, body_style)
            bullets.clear()
            story.append(Paragraph(line, body_style))
        _flush_bullets(bullets, story, body_style)

    for heading in ORDERED_SECTIONS:
        append_section(heading, combined_sections.get(heading, []))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)


def save_output(target: Path, contents: str, logger: logging.Logger) -> None:
    target.write_text(contents, encoding="utf-8")
    logger.info("Saved %s", target)
    if (
        RESUME_TEXT_OUTPUT_PATH is not None
        and PDF_OUTPUT_PATH is not None
        and target == RESUME_TEXT_OUTPUT_PATH
    ):
        save_pdf_resume(contents, PDF_OUTPUT_PATH)


def ensure_openai_module(logger: logging.Logger) -> None:
    if OpenAI is None:
        logger.error("OpenAI import failed: %s", OPENAI_IMPORT_ERROR)
        raise RuntimeError(
            "The OpenAI Python SDK is not available. Install it with `py -m pip install openai`."
        )


def main() -> int:
    try:
        config = load_config(CONFIG_PATH)
    except Exception as exc:  # pragma: no cover
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 1

    logger = configure_logger(config)
    global RESUME_TEXT_OUTPUT_PATH, PDF_OUTPUT_PATH
    RESUME_TEXT_OUTPUT_PATH = ROOT_DIR / config["output_resume_path"]
    PDF_OUTPUT_PATH = ROOT_DIR / config["output_resume_pdf_path"]
    try:
        ensure_openai_module(logger)
        job_description = read_clipboard(logger)
        base_resume_path = BOT_ASSETS_DIR / config["base_resume_path"]
        base_resume = load_json(base_resume_path)
        payload = generate_documents(base_resume, job_description, config, logger)
        resume_output = RESUME_TEXT_OUTPUT_PATH
        cover_letter_output = ROOT_DIR / config["output_cover_letter_path"]
        save_output(resume_output, payload["resume"], logger)
        save_output(cover_letter_output, payload["cover_letter"], logger)
        logger.info("Resume Engine completed successfully.")
        if PDF_OUTPUT_PATH and PDF_OUTPUT_PATH.exists():
            print(f"[PDF LINK] /view/{PDF_OUTPUT_PATH.name}")
        return 0
    except Exception as exc:  # pragma: no cover
        logger.exception("Resume Engine failed: %s", exc)
        print(f"Resume Engine failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
