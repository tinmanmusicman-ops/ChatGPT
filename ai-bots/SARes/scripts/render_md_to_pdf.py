#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import re
from pathlib import Path

DEFAULT_RESUME_OUTPUT_DIR = Path(r"C:\!!!!!!!!!!!!!!!!!!!!!!!!!Stuff")
DEFAULT_OUTPUT_DIR = Path(os.environ.get("HSST_RESUME_OUTPUT_DIR", str(DEFAULT_RESUME_OUTPUT_DIR)))
DEFAULT_INPUT_MD = Path(__file__).resolve().parent / "bot-assets" / "resume_target.md"
DEFAULT_SOURCE_MD = Path(__file__).resolve().parent / "bot-assets" / "resume.md"
DEFAULT_OUTPUT_PDF = DEFAULT_OUTPUT_DIR / "resume.pdf"
DEFAULT_CSS_PATH = Path(__file__).resolve().parent.parent / "resume-dark.css"
DEFAULT_NORTH_CSS_PATH = Path(__file__).resolve().parent.parent / "resume-north.css"


def _find_pandoc_executable() -> Path | None:
    candidate = shutil.which("pandoc")
    if candidate:
        return Path(candidate)
    if os.name == "nt":
        fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Pandoc" / "pandoc.exe"
        if fallback.exists():
            return fallback
    return None


def _find_wkhtmltopdf_executable() -> Path | None:
    candidate = shutil.which("wkhtmltopdf")
    if candidate:
        return Path(candidate)
    if os.name == "nt":
        fallback = Path("C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe")
        if fallback.exists():
            return fallback
    return None


_BLOCK_START = re.compile(r"^#{1,6}\s+\S")


def _normalize_markdown_for_pandoc(md_text: str) -> str:
    """
    Pandoc's markdown reader treats many block elements as requiring a blank line
    boundary. When a heading lacks a separating blank line we insert one while
    keeping the rest of the text untouched.
    """
    normalized = md_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        is_hr = stripped.strip() == "---"
        is_heading = bool(_BLOCK_START.match(stripped))

        if is_heading and out and out[-1].strip():
            out.append("")
        out.append(stripped)
        if is_hr:
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _render_with_pandoc(input_md: Path, output_pdf: Path, css: Path | None) -> None:
    pandoc = _find_pandoc_executable()
    wkhtml = _find_wkhtmltopdf_executable()
    if not pandoc or not wkhtml:
        missing = []
        if not pandoc:
            missing.append("pandoc")
        if not wkhtml:
            missing.append("wkhtmltopdf")
        raise SystemExit(f"Missing required tool(s): {', '.join(missing)}")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    normalized_md = _normalize_markdown_for_pandoc(input_md.read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".md",
        delete=False,
    ) as handle:
        handle.write(normalized_md)
        tmp_path = Path(handle.name)

    try:
        wkhtml_opts: list[str] = [
            "--pdf-engine-opt",
            "--enable-local-file-access",
            "--pdf-engine-opt",
            "--background",
            "--pdf-engine-opt",
            "--print-media-type",
            "--pdf-engine-opt",
            "--margin-top",
            "--pdf-engine-opt",
            "0",
            "--pdf-engine-opt",
            "--margin-right",
            "--pdf-engine-opt",
            "0",
            "--pdf-engine-opt",
            "--margin-bottom",
            "--pdf-engine-opt",
            "0",
            "--pdf-engine-opt",
            "--margin-left",
            "--pdf-engine-opt",
            "0",
        ]
        command = [
            str(pandoc),
            "-f",
            "markdown+hard_line_breaks",
            str(tmp_path),
            "-o",
            str(output_pdf),
            "--pdf-engine",
            str(wkhtml),
        ]
        if css:
            if not css.exists():
                raise SystemExit(f"Missing CSS stylesheet: {css}")
            command.extend(
                [
                    "--css",
                    str(css),
                ]
            )
        command.extend(wkhtml_opts)
        print(f"[INFO] Running pandoc -> {output_pdf.name}")
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stdout = exc.stdout.strip() if exc.stdout else "<empty>"
            stderr = exc.stderr.strip() if exc.stderr else "<empty>"
            raise SystemExit(
                f"Pandoc failed (exit {exc.returncode}). stdout: {stdout} stderr: {stderr}"
            )
        print("[DEBUG] Pandoc stdout:", result.stdout.strip() or "<empty>")
        print("[DEBUG] Pandoc stderr:", result.stderr.strip() or "<empty>")
        print(f"[INFO] Saved {output_pdf}")
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render Markdown resume to PDF.")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=DEFAULT_INPUT_MD,
        help="Source Markdown (default: bot-assets/resume_target.md)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_PDF,
        help="Target PDF path (default: resume.pdf)",
    )
    parser.add_argument(
        "--css",
        "-c",
        type=Path,
        default=DEFAULT_CSS_PATH,
        help="CSS stylesheet for rendering (default: resume-dark.css)",
    )
    parser.add_argument(
        "--ats",
        action="store_true",
        help="Convenience flag: render with the ATS-friendly north CSS.",
    )
    args = parser.parse_args()

    input_md = args.input
    output_pdf = args.output

    if not input_md.exists() and input_md.resolve() == DEFAULT_INPUT_MD.resolve():
        if DEFAULT_SOURCE_MD.exists():
            input_md.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(DEFAULT_SOURCE_MD, input_md)

    if not input_md.exists():
        raise SystemExit(f"Missing input markdown: {input_md}")

    css = DEFAULT_NORTH_CSS_PATH if args.ats else args.css
    _render_with_pandoc(input_md, output_pdf, css=css)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
