#!/usr/bin/env python3
from __future__ import annotations

import re
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer

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
DEFAULT_RESUME_OUTPUT_DIR = Path(r"C:\!!!!!!!!!!!!!!!!!!!!!!!!!Stuff")
DEFAULT_OUTPUT_DIR = Path(os.environ.get("HSST_RESUME_OUTPUT_DIR", str(DEFAULT_RESUME_OUTPUT_DIR)))
DEFAULT_OUTPUT_PDF = DEFAULT_OUTPUT_DIR / "resume.pdf"

@dataclass
class RenderConfig:
    body_font_size: float = 10.5
    body_leading: float = 13
    body_space_after: float = 2
    blank_spacer: float = 8
    list_space_before: float = 2
    list_space_after: float = 6

    name_font_size: float = 16
    name_leading: float = 18
    name_space_after: float = 3

    contact_font_size: float = 10
    contact_leading: float = 11.5
    contact_space_after: float = 1.5

    h2_font_size: float = 12
    h2_leading: float = 14
    h2_space_before: float = 10
    h2_space_after: float = 6

    h3_font_size: float = 11
    h3_leading: float = 13
    h3_space_before: float = 6
    h3_space_after: float = 2


def _apply_preset(config: RenderConfig, preset: str) -> RenderConfig:
    preset_norm = preset.strip().lower()
    if preset_norm == "tight":
        return RenderConfig(
            body_font_size=config.body_font_size,
            body_leading=11.5,
            body_space_after=0.5,
            blank_spacer=5,
            list_space_before=1,
            list_space_after=3.5,
            name_font_size=config.name_font_size,
            name_leading=17,
            name_space_after=2,
            contact_font_size=config.contact_font_size,
            contact_leading=11,
            contact_space_after=1,
            h2_font_size=config.h2_font_size,
            h2_leading=13,
            h2_space_before=7,
            h2_space_after=4,
            h3_font_size=config.h3_font_size,
            h3_leading=12,
            h3_space_before=5,
            h3_space_after=1,
        )
    return config


def _parse_render_directive(line: str) -> tuple[RenderConfig | None, bool]:
    """
    Supported (line must be standalone):
      - <!-- render: tight -->
      - <!-- render: leading=12 spaceAfter=1 blank=6 listAfter=4 -->
      - <!-- render: fontSize=10.25 leading=12 -->
      - <!-- render: nameAfter=2 contactLeading=11 contactAfter=1 -->
    Returns: (config_or_none, is_directive_line)
    """
    match = re.match(r"^\s*<!--\s*render\s*:\s*(.*?)\s*-->\s*$", line, flags=re.IGNORECASE)
    if not match:
        return None, False

    payload = (match.group(1) or "").strip()
    if not payload:
        return RenderConfig(), True

    config = RenderConfig()

    if re.fullmatch(r"tight", payload, flags=re.IGNORECASE):
        return _apply_preset(config, "tight"), True

    tokens = re.split(r"[,\s]+", payload)
    for token in tokens:
        if not token:
            continue
        if token.lower() == "tight":
            config = _apply_preset(config, "tight")
            continue
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key_norm = key.strip().lower()
        value_norm = value.strip()
        try:
            num = float(value_norm)
        except ValueError:
            continue

        if key_norm in ("fontsize", "font_size", "font"):
            config.body_font_size = num
        elif key_norm in ("leading", "lineheight", "line_height"):
            config.body_leading = num
        elif key_norm in ("spaceafter", "space_after"):
            config.body_space_after = num
        elif key_norm in ("blank", "blankspacer", "blank_spacer"):
            config.blank_spacer = num
        elif key_norm in ("listbefore", "list_before", "listspacebefore", "list_space_before"):
            config.list_space_before = num
        elif key_norm in ("listafter", "list_after", "listspaceafter", "list_space_after"):
            config.list_space_after = num
        elif key_norm in ("namefontsize", "name_font_size", "namefont"):
            config.name_font_size = num
        elif key_norm in ("nameleading", "name_leading"):
            config.name_leading = num
        elif key_norm in ("nameafter", "name_after", "namespaceafter", "name_space_after"):
            config.name_space_after = num
        elif key_norm in ("contactfontsize", "contact_font_size", "contactfont"):
            config.contact_font_size = num
        elif key_norm in ("contactleading", "contact_leading"):
            config.contact_leading = num
        elif key_norm in ("contactafter", "contact_after", "contactspaceafter", "contact_space_after"):
            config.contact_space_after = num

    return config, True


def _make_styles(config: RenderConfig) -> dict[str, ParagraphStyle]:
    body_style = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=config.body_font_size,
        leading=config.body_leading,
        spaceAfter=config.body_space_after,
    )
    name_style = ParagraphStyle(
        "Name",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=config.name_font_size,
        leading=config.name_leading,
        alignment=1,  # centered
        spaceAfter=config.name_space_after,
    )
    contact_style = ParagraphStyle(
        "Contact",
        parent=body_style,
        fontSize=config.contact_font_size,
        leading=config.contact_leading,
        alignment=1,  # centered
        spaceAfter=config.contact_space_after,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=config.h2_font_size,
        leading=config.h2_leading,
        spaceBefore=config.h2_space_before,
        spaceAfter=config.h2_space_after,
    )
    h3_style = ParagraphStyle(
        "H3",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=config.h3_font_size,
        leading=config.h3_leading,
        spaceBefore=config.h3_space_before,
        spaceAfter=config.h3_space_after,
    )
    italic_style = ParagraphStyle(
        "Italic",
        parent=body_style,
        fontName="Helvetica-Oblique",
        spaceAfter=6,
    )
    salutation_style = ParagraphStyle(
        "Salutation",
        parent=body_style,
        fontName="Helvetica-Bold",
        spaceAfter=6,
    )

    return {
        "body": body_style,
        "name": name_style,
        "contact": contact_style,
        "h2": h2_style,
        "h3": h3_style,
        "italic": italic_style,
        "salutation": salutation_style,
    }


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

    config = RenderConfig()
    styles = _make_styles(config)
    body_style = styles["body"]
    name_style = styles["name"]
    contact_style = styles["contact"]
    h2_style = styles["h2"]
    h3_style = styles["h3"]
    italic_style = styles["italic"]
    salutation_style = styles["salutation"]

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
    mode: str = "generic"
    in_contact_block = False

    def is_pagebreak(line: str) -> bool:
        stripped = line.strip()
        if stripped == r"\pagebreak":
            return True
        if stripped.lower() in ("<!-- pagebreak -->", "<!--pagebreak-->"):
            return True
        if stripped == "\f":
            return True
        return False

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
                bulletFontSize=body_style.fontSize,
                bulletColor=body_style.textColor,
                spaceBefore=config.list_space_before,
                spaceAfter=config.list_space_after,
            )
        )
        items.clear()

    pending_bullets: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        next_config, is_directive = _parse_render_directive(line)
        if is_directive:
            flush_bullets(pending_bullets)
            if next_config is not None:
                config = next_config
                styles = _make_styles(config)
                body_style = styles["body"]
                name_style = styles["name"]
                contact_style = styles["contact"]
                h2_style = styles["h2"]
                h3_style = styles["h3"]
                italic_style = styles["italic"]
                salutation_style = styles["salutation"]
            continue

        if is_pagebreak(line):
            flush_bullets(pending_bullets)
            story.append(PageBreak())
            continue

        if stripped == "---":
            flush_bullets(pending_bullets)
            add_hr()
            in_contact_block = False
            continue

        if stripped == "":
            flush_bullets(pending_bullets)
            story.append(Spacer(1, config.blank_spacer))
            if mode == "resume":
                in_contact_block = False
            continue

        if stripped.startswith("- "):
            pending_bullets.append(stripped[2:])
            continue

        flush_bullets(pending_bullets)

        if stripped.startswith("# "):
            header_text = stripped[2:].strip()
            if header_text.lower().startswith("dear"):
                story.append(Paragraph(header_text, salutation_style))
            elif not story:
                mode = "resume"
                in_contact_block = True
                story.append(Paragraph(header_text, name_style))
            else:
                story.append(Paragraph(header_text, h2_style))
            continue

        if stripped.startswith("## "):
            story.append(Paragraph(stripped[3:].strip(), h2_style))
            in_contact_block = False
            continue

        if stripped.startswith("### "):
            story.append(Paragraph(stripped[4:].strip(), h3_style))
            in_contact_block = False
            continue

        if stripped.startswith("*") and stripped.endswith("*") and len(stripped) >= 2:
            story.append(Paragraph(stripped.strip("*").strip(), italic_style))
            continue

        if mode == "resume" and in_contact_block:
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
