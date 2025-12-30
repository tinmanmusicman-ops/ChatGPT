#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

try:
    from reportlab.platypus.flowables import HRFlowable
except Exception:  # pragma: no cover
    HRFlowable = None  # type: ignore[assignment]


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start

_SCRIPT_DIR = Path(__file__).resolve().parent
_RESUME_DIR = _SCRIPT_DIR.parent
_REPO_ROOT = _find_repo_root(_SCRIPT_DIR)

DEFAULT_INPUT_MD = _RESUME_DIR / "bot-assets" / "resume_target.md"
DEFAULT_SOURCE_MD = _RESUME_DIR / "bot-assets" / "resume.md"
DEFAULT_OUTPUT_PDF = _REPO_ROOT / "resume.pdf"


def _register_mono_font() -> str:
    candidates = [
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\lucon.ttf",
        r"C:\Windows\Fonts\cour.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            font_name = "ResumeMono"
            pdfmetrics.registerFont(TTFont(font_name, path))
            return font_name
    return "Courier"


def render_md_to_pdf(md_path: Path, pdf_path: Path) -> None:
    text = md_path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    body_style = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=10.5,
        leading=13,
        spaceAfter=2,
    )
    name_style = ParagraphStyle(
        "Name",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=18,
        alignment=1,  # centered
        spaceAfter=6,
    )
    contact_style = ParagraphStyle(
        "Contact",
        parent=body_style,
        fontSize=10,
        leading=12,
        alignment=1,  # centered
        spaceAfter=10,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        spaceBefore=10,
        spaceAfter=6,
    )
    h3_style = ParagraphStyle(
        "H3",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        spaceBefore=6,
        spaceAfter=2,
    )
    italic_style = ParagraphStyle(
        "Italic",
        parent=body_style,
        fontName="Helvetica-Oblique",
        spaceAfter=6,
    )

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=md_path.name,
    )

    story: list[object] = []

    def add_hr() -> None:
        story.append(Spacer(1, 6))
        if HRFlowable is not None:
            story.append(HRFlowable(width="100%", thickness=0.5, spaceBefore=2, spaceAfter=8))
        else:
            story.append(Spacer(1, 10))

    def flush_bullets(items: list[str]) -> None:
        if not items:
            return
        bullet_items = [ListItem(Paragraph(item, body_style)) for item in items]
        story.append(
            ListFlowable(
                bullet_items,
                bulletType="bullet",
                leftIndent=0.22 * inch,
                bulletFontName="Helvetica",
                bulletFontSize=10.5,
                bulletColor=body_style.textColor,
                spaceBefore=2,
                spaceAfter=6,
            )
        )
        items.clear()

    pending_bullets: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped == "---":
            flush_bullets(pending_bullets)
            add_hr()
            continue

        if stripped == "":
            flush_bullets(pending_bullets)
            story.append(Spacer(1, 8))
            continue

        if stripped.startswith("- "):
            pending_bullets.append(stripped[2:])
            continue

        flush_bullets(pending_bullets)

        if stripped.startswith("# "):
            story.append(Paragraph(stripped[2:].strip(), name_style))
            continue

        if stripped.startswith("## "):
            story.append(Paragraph(stripped[3:].strip(), h2_style))
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(stripped[4:].strip(), h3_style))
            continue

        if stripped.startswith("*") and stripped.endswith("*") and len(stripped) >= 2:
            story.append(Paragraph(stripped.strip("*").strip(), italic_style))
            continue

        if len(story) <= 2:
            story.append(Paragraph(stripped, contact_style))
        else:
            story.append(Paragraph(stripped, body_style))

    flush_bullets(pending_bullets)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)


def main() -> int:
    input_md = DEFAULT_INPUT_MD
    output_pdf = DEFAULT_OUTPUT_PDF

    argv = sys.argv[1:]
    if argv:
        if len(argv) != 2:
            raise SystemExit("Usage: render_md_to_pdf.py [<input.md> <output.pdf>]")
        input_md = Path(argv[0])
        output_pdf = Path(argv[1])

    if not input_md.exists() and input_md.resolve() == DEFAULT_INPUT_MD.resolve() and DEFAULT_SOURCE_MD.exists():
        input_md.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_SOURCE_MD, input_md)

    if not input_md.exists():
        raise SystemExit(f"Missing input markdown: {input_md}")

    render_md_to_pdf(input_md, output_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
