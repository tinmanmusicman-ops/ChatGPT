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
DEFAULT_OUTPUT_PDF = _REPO_ROOT / "resume.pdf"
DEFAULT_RENDERER = _SCRIPT_DIR / "render_md_to_pdf.py"


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


def _read_clipboard() -> str:
    try:
        import pyperclip  # type: ignore
    except Exception:
        pyperclip = None

    if pyperclip is not None:
        try:
            content = pyperclip.paste()
            if isinstance(content, str) and content.strip():
                return content.strip()
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
            if result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

    raise RuntimeError("Unable to read job description from clipboard; pass --job-description-file.")


def _is_hr(line: str) -> bool:
    return line.strip() == "---"


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


def _compute_plan(lines: Sequence[str]) -> TailorPlan:
    immutable: set[int] = set()
    allowed: set[int] = set()
    current_section: str | None = None

    for index, line in enumerate(lines):
        section = _major_section(line)
        if section is not None:
            current_section = section

        if line == "" or _is_hr(line) or _is_heading(line) or _is_date_line(line):
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
        "You tailor resumes to a target job description. You MUST preserve structure.\n"
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
        "- You may ONLY edit text in-place (summary, keywords, minor bullet wording).\n"
        "- Preserve blank lines and horizontal rules exactly.\n"
        "- Preserve heading lines exactly.\n"
        "- Preserve date lines exactly.\n"
        "- Preserve bullet prefixes exactly: if a line begins with \"- \", keep \"- \" unchanged.\n"
        f"- Only these line numbers may change: {allowed_ranges}.\n\n"
        "Editable lines (line_number -> current_line_text):\n"
        f"{json.dumps(editable_lines, ensure_ascii=False, indent=2)}\n\n"
        "Output format (JSON only):\n"
        "{\"edits\": {\"<line_number>\": \"<replacement line>\", ...}}\n\n"
        "Rules for edits:\n"
        "- Only include keys for lines you want to change.\n"
        "- Keys must be line numbers from the editable set.\n"
        "- Values must be a single line of text (no newline characters).\n"
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


def _tailor_markdown(md_text: str, job_description: str, *, model: str, temperature: float) -> str:
    if OpenAI is None:
        raise RuntimeError("openai package is required for tailoring but is not installed.")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required to tailor resume_target.md.")

    client = OpenAI(api_key=api_key)
    lines = _normalize_newlines(md_text).split("\n")
    plan = _compute_plan(lines)
    messages = _build_messages(job_description, md_text, plan)

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=6000,
        messages=messages,
    )
    content = resp.choices[0].message.content or ""
    payload = _extract_first_json_object(content)
    edits = payload.get("edits")
    if edits is None:
        raise ValueError("Model response missing `edits`.")
    if not isinstance(edits, dict):
        raise ValueError("`edits` must be an object mapping line numbers to replacement strings.")

    allowed_line_numbers = {str(i + 1) for i in plan.allowed_indices}
    updated = list(lines)

    for line_no_raw, replacement in edits.items():
        line_no = str(line_no_raw).strip()
        if line_no not in allowed_line_numbers:
            raise ValueError(f"Edit provided for non-editable line: {line_no!r}.")
        if not isinstance(replacement, str):
            raise ValueError(f"Replacement must be a string for line {line_no}.")
        if "\n" in replacement or "\r" in replacement:
            raise ValueError(f"Replacement must be a single line for line {line_no}.")

        index = int(line_no) - 1
        src = lines[index]
        out = replacement

        if _is_bullet(src):
            if not out.startswith("- "):
                raise ValueError(f"Bullet marker changed at line {line_no}.")
            if out == "- ":
                raise ValueError(f"Invalid bullet format at line {line_no}.")

        updated[index] = out

    for index, src in enumerate(lines):
        out = updated[index]
        if index in plan.immutable_indices and out != src:
            raise ValueError(f"Immutable line changed at {index + 1}.")
        if index not in plan.allowed_indices and out != src:
            raise ValueError(f"Unexpected change outside allowed lines at {index + 1}.")

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
    parser.add_argument("--job-description-file", type=Path, default=None)
    parser.add_argument("--model", type=str, default="gpt-4.1")
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(args.source.read_text(encoding="utf-8"), encoding="utf-8")

    if args.job_description_file is not None:
        job_description = _read_job_description(args.job_description_file)
    else:
        job_description = _read_clipboard()

    tailored = _tailor_markdown(args.target.read_text(encoding="utf-8"), job_description, model=args.model, temperature=args.temperature)
    args.target.write_text(tailored, encoding="utf-8")

    _render(args.target, args.pdf, args.renderer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
