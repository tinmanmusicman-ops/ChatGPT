#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer


@dataclass(frozen=True)
class Theme:
    page_bg: colors.Color
    text: colors.Color
    heading: colors.Color
    divider: colors.Color


DARK_THEME = Theme(
    page_bg=colors.HexColor("#0B0F14"),
    text=colors.HexColor("#F5F7FA"),
    heading=colors.HexColor("#9AD7FF"),
    divider=colors.HexColor("#223040"),
)


def draw_background(theme: Theme):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(theme.page_bg)
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
        canvas.restoreState()

    return _draw


def build_story(theme: Theme) -> list:
    title = ParagraphStyle(
        name="Title",
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=30,
        textColor=theme.text,
        spaceAfter=14,
    )
    body = ParagraphStyle(
        name="Body",
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        textColor=theme.text,
        spaceAfter=10,
    )
    section = ParagraphStyle(
        name="Section",
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=20,
        textColor=theme.heading,
        spaceBefore=10,
        spaceAfter=6,
    )
    bullet = ParagraphStyle(
        name="Bullet",
        fontName="Helvetica",
        fontSize=13,
        leading=18,
        textColor=theme.text,
    )

    story: list = []

    story.append(Paragraph("Welcome to the Dashboard", title))
    story.append(
        Paragraph(
            "If you just arrived here and nothing makes sense yet, you’re in the right place. "
            "This page is meant to be explored, and you don’t need any background to start. "
            "When you’re ready, the chatbot can explain what you’re seeing—one question at a time.",
            body,
        )
    )

    story.append(Paragraph("What This Dashboard Is", section))
    story.append(
        Paragraph(
            "This dashboard is a quick, live snapshot of what’s happening right now. "
            "It brings together a few signals (like recent activity and trends) and shows them as simple labels and charts. "
            "You can use it to get a sense of “what’s going on” at a glance, even if you don’t recognize everything. "
            "If something looks unfamiliar, that’s normal—the chatbot can translate it into plain language.",
            body,
        )
    )

    story.append(Paragraph("What the Chatbot Is For", section))
    story.append(
        Paragraph(
            "The chatbot is your guide. You can ask questions in everyday language—no special commands. "
            "It can explain what a label means, what a chart is showing, or why something might be happening. "
            "It won’t start talking until you ask something, so just type whenever you’re ready.",
            body,
        )
    )

    story.append(Paragraph("Common Questions You Can Ask", section))
    questions = [
        "What am I looking at?",
        "What does this chart mean?",
        "Why is this running right now?",
        "Is this normal?",
        "What changed compared to earlier?",
        "What should I pay attention to first?",
        "Can you explain this number in simple terms?",
        "What happened most recently?",
        "Is anything unusual or worth checking?",
    ]
    story.append(
        ListFlowable(
            [ListItem(Paragraph(q, bullet), leftIndent=12) for q in questions],
            bulletType="bullet",
            leftIndent=18,
            bulletColor=theme.text,
            bulletFontName="Helvetica",
            bulletFontSize=12,
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph("What Happens Next", section))
    story.append(
        Paragraph(
            "Once you ask a question, the chatbot will reply with a clear explanation and may ask a quick follow-up to make sure it understands. "
            "If you’re not sure how to phrase your question, that’s okay—just describe what you notice. "
            "When you’re ready, start typing a question in the chat.",
            body,
        )
    )

    return story


def build_pdf(output_path: Path, theme: Theme = DARK_THEME) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
        title="Welcome to the Dashboard",
        author="Dashboard Chatbot",
    )
    doc.build(
        build_story(theme),
        onFirstPage=draw_background(theme),
        onLaterPages=draw_background(theme),
    )


def main() -> int:
    here = Path(__file__).resolve()
    output = here.parent.parent / "Web" / "dashboard_chatbot_guide.pdf"
    build_pdf(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

