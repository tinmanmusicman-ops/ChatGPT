#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer


@dataclass(frozen=True)
class Theme:
    page_bg: colors.Color
    text: colors.Color
    muted: colors.Color
    heading: colors.Color
    rule: colors.Color
    code_bg: colors.Color


DARK = Theme(
    page_bg=colors.HexColor("#0B0F14"),
    text=colors.HexColor("#F5F7FA"),
    muted=colors.HexColor("#B9C0CC"),
    heading=colors.HexColor("#9AD7FF"),
    rule=colors.HexColor("#223040"),
    code_bg=colors.HexColor("#111926"),
)


def _draw_background(theme: Theme):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(theme.page_bg)
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
        canvas.setFillColor(theme.muted)
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.55 * inch, f"Page {doc.page}")
        canvas.restoreState()

    return _draw


def _styles(theme: Theme) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            name="Title",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            textColor=theme.text,
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            name="Subtitle",
            fontName="Helvetica",
            fontSize=12,
            leading=16,
            textColor=theme.muted,
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            name="H1",
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=theme.heading,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            name="H2",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=18,
            textColor=theme.text,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            name="Body",
            fontName="Helvetica",
            fontSize=10.8,
            leading=15,
            textColor=theme.text,
            spaceAfter=8,
        ),
        "body_compact": ParagraphStyle(
            name="BodyCompact",
            fontName="Helvetica",
            fontSize=10.3,
            leading=14.5,
            textColor=theme.text,
            spaceAfter=6,
        ),
        "mono": ParagraphStyle(
            name="Mono",
            fontName="Courier",
            fontSize=9.6,
            leading=12.5,
            textColor=theme.text,
            backColor=theme.code_bg,
            borderPadding=6,
            spaceBefore=6,
            spaceAfter=10,
        ),
        "bullet": ParagraphStyle(
            name="Bullet",
            fontName="Helvetica",
            fontSize=10.6,
            leading=14.8,
            textColor=theme.text,
        ),
        "small": ParagraphStyle(
            name="Small",
            fontName="Helvetica",
            fontSize=9.4,
            leading=12.5,
            textColor=theme.muted,
            spaceAfter=6,
        ),
    }


def _bullets(items: Iterable[str], style: ParagraphStyle, left_indent: float = 18) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(i, style), leftIndent=10) for i in items],
        bulletType="bullet",
        leftIndent=left_indent,
        bulletFontName="Helvetica",
        bulletFontSize=9,
        bulletColor=style.textColor,
    )


def _code(text: str) -> str:
    safe = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .rstrip()
    )
    return f"<font face=\"Courier\">{safe}</font>"


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    signature: str
    doc: str
    returns_value: bool
    called_by: list[str]


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    def fmt_arg(arg: ast.arg, default: Optional[ast.expr]) -> str:
        base = arg.arg
        if arg.annotation is not None:
            base += f": {ast.unparse(arg.annotation)}"
        if default is not None:
            base += f" = {ast.unparse(default)}"
        return base

    args = node.args
    pos_args = args.posonlyargs + args.args
    defaults = [None] * (len(pos_args) - len(args.defaults)) + list(args.defaults)
    rendered = [fmt_arg(a, d) for a, d in zip(pos_args, defaults)]
    if args.vararg:
        rendered.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        rendered.append("*")
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        rendered.append(fmt_arg(a, d))
    if args.kwarg:
        rendered.append(f"**{args.kwarg.arg}")
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{node.name}({', '.join(rendered)}){ret}"


def _returns_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            return True
    return False


def _extract_functions_with_callers(path: Path) -> list[FunctionInfo]:
    src = path.read_text(encoding="utf-8")
    mod = ast.parse(src)

    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in mod.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node

    def called_names(fn_node: ast.AST) -> set[str]:
        names: set[str] = set()
        for n in ast.walk(fn_node):
            if isinstance(n, ast.Call):
                target = n.func
                if isinstance(target, ast.Name):
                    names.add(target.id)
        return names

    called_by: dict[str, set[str]] = {name: set() for name in funcs}
    for caller, fn_node in funcs.items():
        for callee in called_names(fn_node):
            if callee in called_by:
                called_by[callee].add(caller)

    infos: list[FunctionInfo] = []
    for name, node in sorted(funcs.items(), key=lambda kv: kv[0].lower()):
        doc = ast.get_docstring(node) or ""
        doc_one = re.sub(r"\s+", " ", doc).strip()
        infos.append(
            FunctionInfo(
                name=name,
                signature=_format_signature(node),
                doc=doc_one,
                returns_value=_returns_value(node),
                called_by=sorted(called_by.get(name, set())),
            )
        )
    return infos


def _first_nonempty_lines(path: Path, limit: int = 40) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    for line in lines:
        if line.strip():
            kept.append(line.rstrip())
        if len(kept) >= limit:
            break
    return "\n".join(kept)


def build_manual_story(theme: Theme, dashboard_py: Path, client_js: Path) -> list[Any]:
    s = _styles(theme)
    story: list[Any] = []

    story.append(Paragraph("Thermostat Dashboard – Operator Manual", s["title"]))
    story.append(
        Paragraph(
            "This manual is written for a first‑time operator. It explains how the dashboard behaves "
            "based strictly on the shipped UI structure and source code.",
            s["subtitle"],
        )
    )
    story.append(
        Paragraph(
            _code(
                "Files this manual is based on:\n"
                f"- {dashboard_py.as_posix()}\n"
                f"- {client_js.as_posix()}\n"
                "- Generated page: ai-bots/Thermostats/Web/dashboard_public.html"
            ),
            s["mono"],
        )
    )

    # 1. What this dashboard is
    story.append(Paragraph("1. What This Dashboard Is", s["h1"]))
    story.append(
        Paragraph(
            "This dashboard is a browser-based view into a thermostat telemetry dataset. "
            "It is generated by a Python script and then operated entirely in the browser via JavaScript.",
            s["body"],
        )
    )
    story.append(
        _bullets(
            [
                "<b>System it monitors</b>: a thermostat/HVAC dataset (project folder name: <font face=\"Courier\">Thermostats</font>). "
                "The code reads rows from a Google Sheet; the thermostat brand/model is not hard-coded in the source.",
                "<b>What problem it solves</b>: it turns raw rows (timestamps, temperatures, modes, runtime) into a live “front panel” plus charts, "
                "and it lets you load prior days as archived snapshots.",
                "<b>Who it is for</b>: an operator who needs to quickly understand what the system is doing (now and over time) without digging through raw data.",
            ],
            s["bullet"],
        )
    )
    story.append(
        Paragraph(
            "<b>Important limitation (from code)</b>: the generated dashboard is a <b>static HTML page</b>. "
            "Clicking buttons does not execute Python on a server; it runs client-side JavaScript only.",
            s["body"],
        )
    )

    # 2. Mental model
    story.append(Paragraph("2. Mental Model of the System", s["h1"]))
    story.append(
        Paragraph(
            "Think of the dashboard as a <b>data player</b> with a cassette deck. A “cassette” is one day of saved data. "
            "The deck/transport controls are how you move between days, while the chart cursor is how you move within a day.",
            s["body"],
        )
    )
    story.append(
        _bullets(
            [
                "<b>Current data</b>: embedded into the HTML as JSON inside <font face=\"Courier\">&lt;script id=\"dashboard-data-inline\"&gt;</font>.",
                "<b>Archive data</b>: loaded on demand from <font face=\"Courier\">ai-bots/Thermostats/Web/chart hist/&lt;YYYY-MM-DD&gt;.json</font> via <font face=\"Courier\">fetch()</font>.",
                "<b>Time index</b>: each chart point is an index into arrays like <font face=\"Courier\">chartLabels[]</font>, <font face=\"Courier\">actual[]</font>, <font face=\"Courier\">setpoint[]</font>, etc.",
                "<b>Selection pointer</b>: your hover/pin chooses which index the front-panel cards display.",
            ],
            s["bullet"],
        )
    )
    story.append(
        Paragraph(
            "<b>What the cassette spin means</b>: the JavaScript adds a <font face=\"Courier\">playing</font> class to the cassette deck "
            "and sets CSS variables for direction and speed. After the spin timer expires, it loads the selected archive JSON and redraws the dashboard.",
            s["body"],
        )
    )

    # 3. Layout overview
    story.append(PageBreak())
    story.append(Paragraph("3. Layout Overview", s["h1"]))
    story.append(
        Paragraph(
            "The dashboard is made of three main areas in small mode, plus a separate full-screen TV mode.",
            s["body"],
        )
    )
    story.append(
        _bullets(
            [
                "<b>A. Front-panel cards</b> (<font face=\"Courier\">#Cards</font>): current values like Building Temp, Set Point, Outside Temp, AC Status, Fan Mode, "
                "plus request metadata (Type, Studio, Request Expires) when present in the dataset.",
                "<b>B. Usage chart</b> (<font face=\"Courier\">#usage-slot</font>): a bar chart of condenser runtime totals for a selected range (7 days / month / year).",
                "<b>C. Controls + transport</b>: chart series toggles, Auto-play toggle, step buttons (<< / >>), and the cassette transport panel.",
                "<b>D. TV mode</b>: a full-screen frame that shows the main history chart with a bottom bar (history selector + tape reader) and a nav overlay.",
            ],
            s["bullet"],
        )
    )

    # 4. Data cassette
    story.append(Paragraph("4. Data Cassette", s["h1"]))
    story.append(Paragraph("<b>What happens when a cassette (archive day) is loaded</b>:", s["h2"]))
    story.append(
        _bullets(
            [
                "The UI chooses a target archive <font face=\"Courier\">slug</font> (YYYY-MM-DD) and schedules a tape spin.",
                "After the spin timer, it calls <font face=\"Courier\">loadDashboardData(slug)</font> which fetches <font face=\"Courier\">chart hist/slug.json</font>.",
                "When the JSON arrives, it calls <font face=\"Courier\">applyDashboardData(data, slug)</font> which replaces in-memory <font face=\"Courier\">dashboardData</font> and redraws charts/cards.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("<b>Spinning cassette (exact meaning)</b>:", s["h2"]))
    story.append(
        Paragraph(
            "The cassette reels spin when the deck has CSS class <font face=\"Courier\">playing</font>. "
            "Direction and speed are controlled by CSS variables <font face=\"Courier\">--deck-spin-direction</font> and <font face=\"Courier\">--deck-spin-duration</font>.",
            s["body"],
        )
    )
    story.append(Paragraph("<b>How the transport relates to time navigation</b>:", s["h2"]))
    story.append(
        _bullets(
            [
                "The transport <b>moves between days</b> (archives).",
                "The step buttons (<< / >>) can move <b>between points within a day</b>, and when you step past the first/last point it can wrap to adjacent days.",
                "Tape animation rules (from code): next day = fast spin; forward jumps = fast-forward then play; backward jumps = rewind then play.",
            ],
            s["bullet"],
        )
    )

    # 5. Buttons and controls
    story.append(PageBreak())
    story.append(Paragraph("5. Buttons and Controls", s["h1"]))
    story.append(
        Paragraph(
            "This section lists each interactive control visible in the HTML and describes exactly what it does. "
            "<b>Note on Python</b>: clicks do not execute Python; they execute <font face=\"Courier\">dashboard_client.js</font> in the browser.",
            s["body"],
        )
    )
    story.append(Paragraph("5.1 Front-panel link", s["h2"]))
    story.append(
        _bullets(
            [
                "<font face=\"Courier\">#help-chat-link</font> (“Chat Help”): opens an external chatbot URL in a new tab. Hidden in TV mode by CSS.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("5.2 Usage Chart controls", s["h2"]))
    story.append(
        _bullets(
            [
                "<font face=\"Courier\">.usage-control[data-range=\"7d\"]</font>: sets usage range to last 7 days (based on available archive slugs).",
                "<font face=\"Courier\">.usage-control[data-range=\"month\"]</font>: sets usage range to the current month (UTC month of the active archive slug).",
                "<font face=\"Courier\">.usage-control[data-range=\"year\"]</font>: aggregates runtime by month for the current year (UTC year of the active archive slug).",
                "<b>Click a bar</b> in the Usage chart: loads that day’s archive via <font face=\"Courier\">loadDashboardData(slug)</font>.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("5.3 Main chart series controls", s["h2"]))
    story.append(
        _bullets(
            [
                "<font face=\"Courier\">.chart-control[data-mode=\"setpoint\"]</font>: show/hide the Set Point series.",
                "<font face=\"Courier\">.chart-control[data-mode=\"actual\"]</font>: show/hide the Building Temp series.",
                "<font face=\"Courier\">.chart-control[data-mode=\"outside\"]</font>: show/hide the Outside Temp series.",
                "<font face=\"Courier\">.chart-control[data-mode=\"cooling\"]</font>: show/hide the AC Status series (Idle/Cooling).",
                "<font face=\"Courier\">.chart-control[data-mode=\"fan\"]</font>: show/hide the Fan Mode series (Auto/Circulate/On).",
                "<font face=\"Courier\">.chart-control[data-mode=\"both\"]</font> (“Combined”): toggles all series on/off as a group.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("5.4 Auto-play", s["h2"]))
    story.append(
        _bullets(
            [
                "<font face=\"Courier\">#autoplay-toggle</font>: toggles auto-play. When enabled, after 60 seconds idle the dashboard cycles highlights and series combinations.",
                "Auto-play pauses can hide the main chart and show the hands/logo for a timed segment; user interaction (mouse/touch/click) stops auto-play and resets the idle timer.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("5.5 Step controls (within-day navigation)", s["h2"]))
    story.append(
        _bullets(
            [
                "<font face=\"Courier\">#chart-step-prev</font> (<<): step to the previous point. If you step past the first point, it can load the previous day and pin to the last point.",
                "<font face=\"Courier\">#chart-step-next</font> (>>): step to the next point. If you step past the last point, it can load the next day and pin to the first point.",
                "<font face=\"Courier\">#chart-step-value</font>: readout showing the selected time label (formatted) for the current hover/pin.",
                "<b>Hold-to-repeat</b>: step buttons support press-and-hold repeating after a delay (implemented via pointer/keyboard listeners).",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("5.6 Transport controls (between-day navigation)", s["h2"]))
    story.append(
        _bullets(
            [
                "<font face=\"Courier\">#transport-step-month</font> / <font face=\"Courier\">#transport-step-day</font>: sets whether the day navigation buttons jump by month or by day.",
                "<font face=\"Courier\">#transport-nav</font>: the script injects Previous/Next archive buttons here (<font face=\"Courier\">#archive-prev</font> and <font face=\"Courier\">#archive-next</font>).",
                "<b>Arrow keys</b>: Left/Right arrow keys perform the same navigation (day/month/hour depending on TV step mode).",
                "<b>Transport panel click</b> (<font face=\"Courier\">#transport-panel</font>): toggles the history list open/closed. "
                "If a history day is “armed” and you click directly on the deck (<font face=\"Courier\">#transport-deck</font>), it loads that selection after the tape animation.",
            ],
            s["bullet"],
        )
    )

    # 6. Click and double-click
    story.append(PageBreak())
    story.append(Paragraph("6. Click and Double-Click Behavior", s["h1"]))
    story.append(Paragraph("6.1 Single-click (chart point selection)", s["h2"]))
    story.append(
        _bullets(
            [
                "Move mouse over the main chart: if nothing is pinned, the dashboard previews (“Hover: …”) and updates the front-panel cards.",
                "Click a point on the main chart: pins that point (front-panel cards lock to it). Click the same point again to unpin.",
                "Click empty chart area: clears pin and suppresses hover updates until you move the mouse out and back in.",
                "“Clear Pin” button: appears only when a point is pinned; clicking it clears the pin.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("6.2 Double-click (enter/exit TV mode)", s["h2"]))
    story.append(
        _bullets(
            [
                "Double-click the main chart OR the usage chart: enters TV mode (full-screen frame).",
                "In TV mode: double-click again to exit back to the dashboard.",
                "In TV mode: pressing <b>Escape</b> also exits.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("6.3 State preserved when switching views", s["h2"]))
    story.append(
        _bullets(
            [
                "Pinned point selection and active series modes are saved to <font face=\"Courier\">localStorage</font> key <font face=\"Courier\">thermostatDashboard.ui.v1</font>.",
                "When a new archive loads, the dashboard attempts to restore the pinned selection by matching the saved hour label to the new day’s labels.",
                "TV mode remembers whether charts were swapped and whether the big chart was hidden, then restores those states on exit.",
            ],
            s["bullet"],
        )
    )

    # 7. Display modes
    story.append(Paragraph("7. Display Modes", s["h1"]))
    story.append(Paragraph("7.1 Small dashboard mode", s["h2"]))
    story.append(
        Paragraph(
            "Small mode shows the front-panel cards, the Usage chart, and the control/transport area. "
            "The large TV frame is hidden by the <font face=\"Courier\">hide-big-chart</font> body class.",
            s["body"],
        )
    )
    story.append(Paragraph("7.2 Big TV / full-screen mode", s["h2"]))
    story.append(
        _bullets(
            [
                "TV mode is enabled by adding <font face=\"Courier\">tv-mode</font> to <font face=\"Courier\">document.body</font>.",
                "Most small-mode elements are hidden in TV mode (cards, controls block, etc.) by CSS.",
                "A bottom bar shows the active history day and a tape reader deck; chart controls appear as an overlay.",
                "If you move the mouse near the bottom edge, the TV controls hint appears (auto-hidden).",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("7.3 How to enter/exit", s["h2"]))
    story.append(
        _bullets(
            ["Enter: double-click either chart.", "Exit: double-click in TV mode, or press Escape."],
            s["bullet"],
        )
    )

    # 8. Form behavior (state)
    story.append(PageBreak())
    story.append(Paragraph("8. Form Behavior (What Updates and What Stays)", s["h1"]))
    story.append(
        Paragraph(
            "There is no traditional form submission. The dashboard is a single-page UI with state held in memory and in localStorage.",
            s["body"],
        )
    )
    story.append(
        _bullets(
            [
                "<b>Updates dynamically</b>: front-panel card values, condenser runtime totals, series visibility, tooltips, and selection readouts.",
                "<b>Does not reset automatically</b>: your chosen series modes and pin selection (persisted in <font face=\"Courier\">localStorage</font>).",
                "<b>Resets when an archive loads</b>: chart datasets and labels are replaced by the archive JSON; the UI then tries to re-apply your saved pin/modes.",
            ],
            s["bullet"],
        )
    )

    # 9. Chatbot interaction
    story.append(Paragraph("9. Chatbot Interaction", s["h1"]))
    story.append(
        Paragraph(
            "From the dashboard source code, the chatbot is accessed via the “Chat Help” link and is not embedded into the dashboard state.",
            s["body"],
        )
    )
    story.append(Paragraph("<b>What the chatbot is used for</b>:", s["h2"]))
    story.append(
        _bullets(
            [
                "Explaining what the user is seeing (cards, charts, controls).",
                "Helping interpret values and trends (e.g., why the condenser runtime is high).",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("<b>Allowed actions (based on dashboard code)</b>:", s["h2"]))
    story.append(
        _bullets(
            [
                "It can open and display guidance (like PDFs) and answer questions.",
                "It cannot directly change thermostat setpoints or modes through this dashboard, because the dashboard has no API endpoints and runs as static HTML.",
                "It can instruct the user to click dashboard controls (series toggles, history navigation, TV mode) to change what is displayed.",
            ],
            s["bullet"],
        )
    )
    story.append(
        Paragraph(
            "<b>State-aware suggestions (what it can base suggestions on)</b>: "
            "the dashboard stores UI state locally (pinned hour and active series). "
            "Unless the chatbot has separate access to that browser state, it will not automatically know it; "
            "a user may need to describe what they selected.",
            s["body_compact"],
        )
    )

    # 10. Function reference
    story.append(PageBreak())
    story.append(Paragraph("10. Function Reference (Critical Section)", s["h1"]))
    story.append(
        Paragraph(
            "This section lists Python functions defined in the generator script and what triggers them. "
            "For UI behaviors, see the JavaScript functions in <font face=\"Courier\">dashboard_client.js</font>.",
            s["body"],
        )
    )
    infos = _extract_functions_with_callers(dashboard_py)
    story.append(
        Paragraph(
            f"{len(infos)} Python functions were found in the generator script.",
            s["small"],
        )
    )
    for info in infos:
        story.append(Paragraph(f"<b>{info.signature}</b>", s["body_compact"]))
        doc = info.doc or "No docstring in source."
        story.append(Paragraph(doc, s["small"]))
        triggers = []
        if info.name == "main":
            triggers.append("Trigger: command line entry point (called under __main__).")
        if info.called_by:
            triggers.append(f"Called by: {', '.join(info.called_by)}")
        else:
            triggers.append("Called by: (no other Python function references found)")
        triggers.append("Outputs: returns a value" if info.returns_value else "Outputs: no explicit return value (None)")
        story.append(_bullets(triggers, s["bullet"], left_indent=24))
        story.append(Spacer(1, 4))

    # 11. Typical usage flow
    story.append(PageBreak())
    story.append(Paragraph("11. Typical Usage Flow", s["h1"]))
    story.append(Paragraph("11.1 First launch (operator)", s["h2"]))
    story.append(
        _bullets(
            [
                "Open the dashboard URL (static page). The page loads embedded JSON and initializes the UI.",
                "If you do nothing, Auto-play may start after an idle delay and cycle visible series/points.",
                "If you want manual control, click anywhere on the page or move the mouse to stop Auto-play.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("11.2 Read the current state", s["h2"]))
    story.append(
        _bullets(
            [
                "Look at the front-panel cards to see the current (or selected) Building Temp, Set Point, Outside Temp, AC Status, Fan Mode, and condenser runtime.",
                "Use the series buttons to simplify the display (e.g., turn off everything except Set Point).",
                "Hover the chart (when visible) to preview a moment in time; click to pin if you want to lock the cards to that moment.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("11.3 Navigate history (day by day)", s["h2"]))
    story.append(
        _bullets(
            [
                "Use the transport navigation (injected Previous/Next buttons) or Left/Right arrow keys to move across archives.",
                "Watch for the tape spin animation; after it finishes, the dashboard loads the selected day’s JSON and redraws.",
                "Use << / >> step buttons to move within the day; stepping past the edges can automatically wrap to adjacent days.",
            ],
            s["bullet"],
        )
    )
    story.append(Paragraph("11.4 Enter TV mode (big view)", s["h2"]))
    story.append(
        _bullets(
            [
                "Double-click either chart to enter TV mode.",
                "Use the TV step mode (Month/Day/Time) and the big << / >> buttons to navigate.",
                "Exit TV mode by pressing Escape or double-clicking again.",
            ],
            s["bullet"],
        )
    )

    return story


def build_pdf(output_path: Path) -> None:
    dashboard_py = Path(__file__).resolve().parent / "Dashboard.py"
    client_js = Path(__file__).resolve().parent / "dashboard_client.js"
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title="Thermostat Dashboard – Operator Manual",
        author="Thermostats Dashboard",
    )
    doc.build(
        build_manual_story(DARK, dashboard_py, client_js),
        onFirstPage=_draw_background(DARK),
        onLaterPages=_draw_background(DARK),
    )


def main() -> int:
    here = Path(__file__).resolve()
    output = here.parent.parent / "Web" / "dashboard_operator_manual.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
