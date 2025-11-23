from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch


PDF_NAME = "ConfigEditor_EI_Guide.pdf"


def create_canvas() -> canvas.Canvas:
    pdf_path = base_dir / PDF_NAME
    c = canvas.Canvas(str(pdf_path), pagesize=LETTER)
    c.setTitle("Config Editor – EI Demonstration")
    return c


def draw_title_page(c: canvas.Canvas, title: str, subtitle: str, tagline: str, y_start: float) -> float:
    width, height = LETTER
    c.setFont("Helvetica-Bold", 22)
    c.drawString(inch, y_start, title)
    y = y_start - 0.5 * inch
    c.setFont("Helvetica-Bold", 15)
    c.drawString(inch, y, subtitle)
    y -= 0.4 * inch
    c.setFont("Helvetica", 12)
    c.drawString(inch, y, tagline)
    return y - inch


def draw_heading(c: canvas.Canvas, text: str, x: float, y: float) -> float:
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, text)
    return y - 0.25 * inch


def wrap_text(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, line_height: float) -> float:
    c.setFont("Helvetica", 11)
    words = text.split()
    line = []
    current_y = y
    for word in words:
        test_line = " ".join(line + [word])
        if c.stringWidth(test_line, "Helvetica", 11) <= max_width:
            line.append(word)
        else:
            c.drawString(x, current_y, " ".join(line))
            current_y -= line_height
            if current_y < inch:
                c.showPage()
                current_y = LETTER[1] - inch
                c.setFont("Helvetica", 11)
            line = [word]
    if line:
        c.drawString(x, current_y, " ".join(line))
        current_y -= line_height
    return current_y


def draw_bullets(c: canvas.Canvas, lines: List[str], x: float, y: float, max_width: float, line_height: float) -> float:
    c.setFont("Helvetica", 11)
    bullet_indent = 0.2 * inch
    text_indent = x + bullet_indent
    current_y = y
    for line in lines:
        bullet = "\u2022 "
        c.drawString(x, current_y, bullet)
        current_y = wrap_text(c, line, text_indent, current_y, max_width - bullet_indent, line_height)
    return current_y


def ensure_space(c: canvas.Canvas, current_y: float, needed: float) -> float:
    if current_y - needed < inch:
        c.showPage()
        return LETTER[1] - inch
    return current_y


def main():
    c = create_canvas()
    margin = inch
    max_width = LETTER[0] - 2 * margin
    y = LETTER[1] - inch

    y = draw_title_page(
        c,
        "Config Editor – Engineered Intelligence Demonstration",
        "Accessibility, Legacy Respect, and Human + EI Collaboration",
        "A simple config GUI used as a living example of Engineered Intelligence in real time.",
        y,
    )

    c.showPage()
    y = LETTER[1] - inch

    y = ensure_space(c, y, inch)
    y = draw_heading(c, "1. Overview", margin, y)
    overview_text = (
        "The Config Editor is a Tkinter-based application created as a working demonstration of Engineered Intelligence. "
        "It handles everyday configuration tasks while showcasing EI principles: clear GUI workflows, theme customization, "
        "accessibility-aware decisions, and iterative enhancements guided through human + Codex/GPT collaboration."
    )
    y = wrap_text(c, overview_text, margin, y, max_width, 0.22 * inch)

    y = ensure_space(c, y, 1.2 * inch)
    y = draw_heading(c, "2. Key Features", margin, y)
    features = [
        "Load, edit, and save JSON configuration files in a single window.",
        "Key/value editor with type inference, history recall, and dropdown helpers.",
        "Multiple themes: High Contrast Dark, Standard Light, and the retro Green Screen CRT.",
        "Theme Color Picker with live preview, enabling custom palettes tuned in real time.",
        "Status indicators highlighting unsaved changes and clarity on save operations.",
        "EI Guide launch affordances: Help menu entry plus a prominent footer button.",
    ]
    y = draw_bullets(c, features, margin, y, max_width, 0.22 * inch)

    y = ensure_space(c, y, 1.2 * inch)
    y = draw_heading(c, "3. Accessibility & Legacy – Green Screen CRT Theme", margin, y)
    accessibility_text = (
        "The Green Screen CRT theme honors the late 70s and 80s computing era, providing high-contrast visuals that are "
        "comfortable for low-vision users while signaling seasoned engineering practices. It was designed collaboratively "
        "with Codex/GPT, coming together in roughly thirty seconds and working immediately without debugging."
    )
    y = wrap_text(c, accessibility_text, margin, y, max_width, 0.22 * inch)

    y = ensure_space(c, y, 1.4 * inch)
    y = draw_heading(c, "4. Engineered Intelligence (EI) Story", margin, y)
    ei_story = (
        "This project doubles as an EI sandbox: new features such as theme systems, guide launchers, and layout tweaks were "
        "shipped in rapid cycles. When an experiment broke the UI, the human + AI partners quickly diagnosed and restored it, "
        "preserving improvements. The human acts as the architect, setting intent and tone; EI executes precise changes, "
        "accelerating iteration and reinforcing a partnership that amplifies empathy, experience, and creativity."
    )
    y = wrap_text(c, ei_story, margin, y, max_width, 0.22 * inch)

    y = ensure_space(c, y, 1.3 * inch)
    y = draw_heading(c, "5. EI Guide / Chatbot Vision", margin, y)
    guide_text = (
        "Instead of relying on static manuals, the Config Editor experiments with an EI Guide launcher. Selecting "
        "Help → Launch EI Guide (or the footer button) opens a conversational assistant, offering interactive documentation. "
        "This reflects a shift toward living guidance: users can ask questions, recruiters can explore context, and the system "
        "explains itself dynamically."
    )
    y = wrap_text(c, guide_text, margin, y, max_width, 0.22 * inch)

    y = ensure_space(c, y, 1.2 * inch)
    y = draw_heading(c, "6. Tech Stack Summary", margin, y)
    tech_lines = [
        "Python + Tkinter for GUI, configuration handling, and accessibility features.",
        "Theme system with built-in palettes plus customizable Theme Color Picker.",
        "Accessibility considerations baked into color choices, contrast, and readable typography.",
        "ReportLab generates this PDF overview from a lightweight script.",
        "Codex / GPT collaboration accelerates design, debugging, and feature delivery.",
    ]
    y = draw_bullets(c, tech_lines, margin, y, max_width, 0.22 * inch)

    y = ensure_space(c, y, 0.8 * inch)
    y = draw_heading(c, "Closing", margin, y)
    closing = (
        "This project demonstrates how legacy experience, accessibility, and modern intelligent systems can be woven "
        "into a practical, human-centered tool."
    )
    y = wrap_text(c, closing, margin, y, max_width, 0.22 * inch)

    c.save()
    print(f"Wrote {PDF_NAME}")


if __name__ == "__main__":
    main()
