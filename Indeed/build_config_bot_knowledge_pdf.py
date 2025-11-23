from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch


PDF_NAME = "ConfigEditor_Bot_Knowledge_Base.pdf"


def create_canvas():
    pdf_path = base_dir / PDF_NAME
    c = canvas.Canvas(str(pdf_path), pagesize=LETTER)
    c.setTitle("Config Editor – EI Guide Knowledge Base")
    return c


def draw_heading(c, text, x, y):
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, text)
    return y - 0.25 * inch


def wrap_text(c, text, x, y, max_width, line_height=0.22 * inch, font_size=11):
    c.setFont("Helvetica", font_size)
    words = text.split()
    line = []
    current_y = y
    for word in words:
        test_line = " ".join(line + [word])
        if c.stringWidth(test_line, "Helvetica", font_size) <= max_width:
            line.append(word)
        else:
            c.drawString(x, current_y, " ".join(line))
            current_y -= line_height
            if current_y < inch:
                c.showPage()
                current_y = LETTER[1] - inch
                c.setFont("Helvetica", font_size)
            line = [word]
    if line:
        c.drawString(x, current_y, " ".join(line))
        current_y -= line_height
    return current_y


def draw_bullets(c, lines, x, y, max_width, line_height=0.22 * inch):
    bullet_indent = 0.2 * inch
    c.setFont("Helvetica", 11)
    current_y = y
    for text in lines:
        c.drawString(x, current_y, "\u2022")
        current_y = wrap_text(c, text, x + bullet_indent, current_y, max_width - bullet_indent, line_height)
    return current_y


def ensure_space(c, current_y, needed=inch):
    if current_y - needed < inch:
        c.showPage()
        return LETTER[1] - inch
    return current_y


def main():
    c = create_canvas()
    margin = inch
    max_width = LETTER[0] - 2 * margin
    y = LETTER[1] - inch

    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin, y, "Config Editor – EI Guide Knowledge Base")
    y -= 0.4 * inch
    c.setFont("Helvetica", 12)
    c.drawString(margin, y, "Interactive Help for Users of the Config Editor")
    y -= inch

    # Section 1 – What Is This Tool?
    y = ensure_space(c, y)
    y = draw_heading(c, "1. What Is This Tool?", margin, y)
    overview_text = (
        "The Config Editor helps you open, review, and update configuration files in a friendly window. "
        "It is also a practical demonstration of Engineered Intelligence (EI): humans provide intent and direction, "
        "while an intelligent assistant helps execute changes quickly and safely."
    )
    y = wrap_text(c, overview_text, margin, y, max_width)

    # Section 2 – Basic Navigation Guide
    y = ensure_space(c, y)
    y = draw_heading(c, "2. Basic Navigation Guide", margin, y)
    steps = [
        "Load a config: use the Config path field, click Browse to select a file, then press Load.",
        "Edit a key: select an entry in the list, adjust the Key and Value fields, choose the type if needed.",
        "Add or delete: enter a new key/value and click Add/Update, or select an entry and use Delete Selected.",
        "Save changes: click Save to write updates back to the JSON config file.",
        "\"Unsaved Changes\" reminder: this message under the form warns when edits are not yet saved.",
        "Status bar: shows confirmation, warnings, or errors. Watch it when loading or saving files.",
    ]
    y = draw_bullets(c, steps, margin, y, max_width)

    # Section 3 – Understanding the Interface
    y = ensure_space(c, y)
    y = draw_heading(c, "3. Understanding the Interface", margin, y)
    interface_points = [
        "Config path: shows which file will be loaded or saved.",
        "Browse / Load / Save: manage file selection and persistence.",
        "Entries list: displays all configuration keys and their values.",
        "Key and Value fields: edit content for the selected entry or a new key.",
        "Font Size selector: adjust text sizing for readability.",
        "Theme controls: switch styles from the View menu or Theme Colors button.",
        "Status footer: messages and indicators, plus the Configuration Chatbot launch button.",
    ]
    y = draw_bullets(c, interface_points, margin, y, max_width)

    # Section 4 – Themes & Appearance
    y = ensure_space(c, y)
    y = draw_heading(c, "4. Themes & Appearance", margin, y)
    theme_text = (
        "Themes change the look and feel of the Config Editor. Use the View menu to switch between High Contrast Dark, "
        "Standard Light, and the Green Screen CRT theme. The Green Screen CRT theme is intentionally retro: it honors "
        "legacy terminals, offers strong contrast, and helps users who prefer gentle monochrome displays."
    )
    y = wrap_text(c, theme_text, margin, y, max_width)

    # Section 5 – Theme Color Picker
    y = ensure_space(c, y)
    y = draw_heading(c, "5. Theme Color Picker", margin, y)
    picker_text = (
        "Select Theme Colors to open the picker. Each color field includes a button showing its current hue. "
        "When you adjust a color, the live preview updates immediately so you can confirm readability and accent choices."
    )
    y = wrap_text(c, picker_text, margin, y, max_width)

    # Section 6 – EI Guide (Chatbot) Usage
    y = ensure_space(c, y)
    y = draw_heading(c, "6. EI Guide (Chatbot) Usage", margin, y)
    guide_text = (
        "Launch the EI Guide from Help → Launch EI Guide or the Configuration Chatbot button near the bottom. "
        "Ask it how to use features, why the interface looks a certain way, how to troubleshoot, or even what EI means. "
        "This chatbot replaces static manuals with an interactive conversation."
    )
    y = wrap_text(c, guide_text, margin, y, max_width)

    # Section 7 – Common Problems & Solutions
    y = ensure_space(c, y)
    y = draw_heading(c, "7. Common Problems & Solutions", margin, y)
    problems = [
        "\"My changes didn’t save.\" → Click Save and watch the status bar for confirmation. Unsaved Changes will clear when the file is written.",
        "\"I don’t see my config file.\" → Verify the path in the Config field. Browse again if needed.",
        "\"The screen looks strange.\" → Try switching themes; Green Screen CRT is designed for high comfort.",
        "\"I changed colors and can’t read text.\" → Reopen Theme Colors and reset to defaults, or switch to another preset theme.",
        "\"What is EI?\" → Engineered Intelligence means this tool is built through human direction plus intelligent assistance.",
    ]
    y = draw_bullets(c, problems, margin, y, max_width)

    # Section 8 – What Is Engineered Intelligence (EI)?
    y = ensure_space(c, y)
    y = draw_heading(c, "8. What Is Engineered Intelligence (EI)?", margin, y)
    ei_text = (
        "EI is a collaboration model: humans set goals, tone, and context while AI accelerates design, coding, and fixes. "
        "This tool is a living example—changes are intentional, rapid, and grounded in empathy and accessibility."
    )
    y = wrap_text(c, ei_text, margin, y, max_width)

    # Section 9 – Talking to the EI Guide
    y = ensure_space(c, y)
    y = draw_heading(c, "9. Talking to the EI Guide", margin, y)
    talking_text = (
        "If you're unsure, just ask. The EI Guide understands this application, knows its philosophy, and responds in real time. "
        "There is no need to read lengthy manuals—the guide will explain each step conversationally."
    )
    y = wrap_text(c, talking_text, margin, y, max_width)

    # Closing
    y = ensure_space(c, y)
    y = draw_heading(c, "Closing", margin, y)
    closing_text = (
        "This knowledge base exists so the tool can teach itself—through conversation, clarity, and intelligent collaboration."
    )
    y = wrap_text(c, closing_text, margin, y, max_width)

    c.save()
    print(f"Wrote {PDF_NAME}")


if __name__ == "__main__":
    main()
