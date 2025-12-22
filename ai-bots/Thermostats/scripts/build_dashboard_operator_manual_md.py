#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    signature: str
    doc: str
    returns_value: bool
    called_by: list[str]


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    def fmt_arg(arg: ast.arg, default: ast.expr | None) -> str:
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


def _md_escape(text: str) -> str:
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


def build_markdown(dashboard_py: Path, client_js: Path) -> str:
    client_name = client_js.as_posix()
    dash_name = dashboard_py.as_posix()
    lines: list[str] = []

    lines.append("# Thermostat Dashboard — Operator Manual")
    lines.append("")
    lines.append("This manual is written for a first-time operator. It explains how the dashboard behaves **based on the shipped UI structure and source code**.")
    lines.append("")
    lines.append("**Source of truth files:**")
    lines.append(f"- `{dash_name}` (Python generator)")
    lines.append(f"- `{client_name}` (Browser UI logic)")
    lines.append("- `ai-bots/Thermostats/Web/dashboard_public.html` (generated output)")
    lines.append("")
    lines.append("> Note: This dashboard runs as static HTML + JavaScript in the browser. Clicking controls does **not** execute Python on a server.")
    lines.append("")

    lines.append("## 1. What This Dashboard Is")
    lines.append("")
    lines.append("- **What system it controls/monitors:** a thermostat/HVAC telemetry dataset (project folder name: `Thermostats`). The Python script reads rows from a Google Sheet and generates a dashboard page.")
    lines.append("- **What problem it solves:** converts raw rows (timestamps, temperatures, modes, runtime) into a readable “front panel” plus charts, and lets the operator load prior days as archived snapshots.")
    lines.append("- **Who it is designed for:** someone operating/monitoring the system who needs to understand current status and trends without reading the raw sheet.")
    lines.append("")
    lines.append("## 2. Mental Model of the System")
    lines.append("")
    lines.append("Think of the dashboard as a **data player** with a cassette deck:")
    lines.append("")
    lines.append("- A **cassette** represents **one day of saved data** (an “archive day”).")
    lines.append("- The **transport** moves **between days** (loads a different archive JSON file).")
    lines.append("- The **chart cursor** moves **within a day** (picks a point index).")
    lines.append("- The **front-panel cards** show values for the currently selected point (hover/pin).")
    lines.append("")
    lines.append("### What the cassette represents in real terms")
    lines.append("")
    lines.append("- **Current data** is embedded into the HTML in a `<script id=\"dashboard-data-inline\" type=\"application/json\">…</script>` block.")
    lines.append("- **Archive data** is loaded from `ai-bots/Thermostats/Web/chart hist/<YYYY-MM-DD>.json` using `fetch()` in the browser.")
    lines.append("- **Time indexing** is array-based: a point index selects aligned values across arrays like `chartLabels[]`, `actual[]`, `setpoint[]`, `outside[]`, `cooling[]`, `fan[]`, etc.")
    lines.append("")
    lines.append("### What the spinning cassette means")
    lines.append("")
    lines.append("- The reels spin when the deck element has CSS class `playing`.")
    lines.append("- Direction and speed are controlled by CSS variables `--deck-spin-direction` and `--deck-spin-duration` that the JavaScript sets before scheduling the archive load.")
    lines.append("")
    lines.append("## 3. Layout Overview")
    lines.append("")
    lines.append("### Major areas (small mode)")
    lines.append("")
    lines.append("- **A. Front-panel cards** (`#Cards`): current values (temps, modes, etc.).")
    lines.append("- **B. Usage chart** (`#usage-slot`): bar chart of condenser runtime totals across a selected range (7 days / month / year).")
    lines.append("- **C. Controls + history + transport**: series toggles, auto-play, step buttons, and a cassette transport panel used to navigate archived days.")
    lines.append("")
    lines.append("### TV mode (big/full-screen mode)")
    lines.append("")
    lines.append("- **TV frame** shows the main history chart full-screen.")
    lines.append("- **Bottom bar** shows a history selector and a tape reader deck.")
    lines.append("- **Overlay controls** provide chart mode buttons and navigation.")
    lines.append("")

    lines.append("## 4. Data Cassette")
    lines.append("")
    lines.append("### What happens when a cassette (archive day) is loaded")
    lines.append("")
    lines.append("From `dashboard_client.js`:")
    lines.append("")
    lines.append("1. The UI chooses an archive **slug** (format `YYYY-MM-DD`).")
    lines.append("2. The UI starts the tape animation (`triggerDeckSpin(...)`).")
    lines.append("3. After the spin timer, it calls `loadDashboardData(slug)` which fetches `chart hist/<slug>.json`.")
    lines.append("4. On success, it calls `applyDashboardData(data, slug)` which replaces in-memory state and redraws charts/cards.")
    lines.append("")
    lines.append("### Transport controls vs. time navigation")
    lines.append("")
    lines.append("- **Between-day navigation:** uses archive slugs (`navigateArchiveByDays(...)`, `navigateArchiveByMonths(...)`, plus the history list).")
    lines.append("- **Within-day navigation:** uses the selected point index (`stepPinnedPoint(...)` and chart hover/pin).")
    lines.append("- **Edge behavior:** stepping past the first/last point can load an adjacent day and pin to the opposite edge (continuous “scrolling” feel).")
    lines.append("")
    lines.append("## 5. Buttons and Controls")
    lines.append("")
    lines.append("> Important: buttons trigger JavaScript functions in `dashboard_client.js`. They do **not** call Python functions directly.")
    lines.append("")
    lines.append("### 5.1 Chat Help link")
    lines.append("")
    lines.append("- **Control:** `#help-chat-link` (“Chat Help”)")
    lines.append("- **Click behavior:** opens the configured chatbot URL in a new tab.")
    lines.append("- **Python function triggered:** none (static HTML link).")
    lines.append("- **State changes:** none in the dashboard.")
    lines.append("")
    lines.append("### 5.2 Main history chart controls (series visibility)")
    lines.append("")
    lines.append("Controls: `.chart-control[data-mode=…]`")
    lines.append("")
    lines.append("- `setpoint`, `actual`, `outside`, `cooling`, `fan`: toggles each dataset via `toggleMode(mode)`; redraws the chart and saves mode state to localStorage.")
    lines.append("- `both` (“Combined”): toggles all datasets on/off as a group in `toggleMode(\"both\")`.")
    lines.append("")
    lines.append("### 5.3 Auto-play")
    lines.append("")
    lines.append("- **Control:** `#autoplay-toggle`")
    lines.append("- **Click behavior:** toggles auto-play on/off (managed by `bindAutoplayInteractions()`, `startAutoplay()`, `stopAutoplay()`).")
    lines.append("- **What changes:** after idle time, auto-play cycles series combinations and highlights points; user interaction stops and reschedules auto-play.")
    lines.append("")
    lines.append("### 5.4 Show/Hide History chart")
    lines.append("")
    lines.append("- **Control:** `#toggle-history`")
    lines.append("- **Click behavior:** toggles the main chart canvas display using `showChart()` / `hideChart()`.")
    lines.append("- **What changes:** chart canvas visibility and button label (`Show History Chart` ↔ `Hide History Chart`).")
    lines.append("")
    lines.append("### 5.5 Step controls (within-day point navigation)")
    lines.append("")
    lines.append("- **Controls:** `#chart-step-prev` and `#chart-step-next`")
    lines.append("- **Click behavior:** calls `stepPinnedPoint(-1)` or `stepPinnedPoint(1)`.")
    lines.append("- **Hold behavior:** buttons support hold-to-repeat (`bindHoldRepeat(...)`) after a delay.")
    lines.append("- **State changes:** updates pinned selection and the card readouts; may load adjacent days when stepping beyond edges.")
    lines.append("")
    lines.append("### 5.6 Usage chart controls (runtime aggregation)")
    lines.append("")
    lines.append("- **Controls:** `.usage-control[data-range=\"7d\"|\"month\"|\"year\"]`")
    lines.append("- **Click behavior:** sets `usageRangeKey` and calls `renderUsageSlotChart()`.")
    lines.append("- **Click on a bar:** loads that day’s archive via `loadDashboardData(slug)`.")
    lines.append("")
    lines.append("### 5.7 Transport panel and history list (between-day navigation)")
    lines.append("")
    lines.append("- **History list UI:** `#chart-history` / `#chart-history-toggle` / `#chart-history-list` plus dynamic month picker built by `renderArchiveList()`.")
    lines.append("- **Open/close history list:** controlled by `setHistoryExpanded(...)`, `showHistoryFiles()`, `hideHistoryFiles()`.")
    lines.append("- **Selecting a day:** clicking a history entry schedules an archive load via `scheduleArchiveLoadWithTapeRules(slug)`.")
    lines.append("- **Transport panel click:** `bindTransportHistoryToggle()` toggles the history list; it also supports “load by clicking the deck” when a pending selection is armed.")
    lines.append("")
    lines.append("### 5.8 Keyboard shortcuts")
    lines.append("")
    lines.append("- **Left/Right arrows:** handled by `bindArchiveKeyboardShortcuts()` to navigate (in TV mode, they respect TV step mode).")
    lines.append("- **Escape (TV mode):** exits TV mode.")
    lines.append("")

    lines.append("## 6. Click and Double-Click Behavior")
    lines.append("")
    lines.append("### 6.1 Single-click selection behavior (main chart)")
    lines.append("")
    lines.append("- Hover a point (mousemove): previews the point (updates cards) when nothing is pinned.")
    lines.append("- Click a point: pins it (click again on same point unpins).")
    lines.append("- Click empty area: clears pin and suppresses hover updates until the mouse leaves and re-enters.")
    lines.append("- `Clear Pin` button appears only while pinned (created/managed in `ensureSelectionUi()` and updated by `updateSelectionIndicator()`).")
    lines.append("")
    lines.append("### 6.2 Double-click behavior")
    lines.append("")
    lines.append("- Double-click the main chart OR the usage chart: enter TV mode (`enterTvMode()`).")
    lines.append("- Double-click while in TV mode: exit TV mode (`exitTvMode()`).")
    lines.append("")
    lines.append("### 6.3 State preserved across view changes")
    lines.append("")
    lines.append("- UI state is stored in localStorage key `thermostatDashboard.ui.v1` via `saveUiState()` and restored by `loadUiState()`.")
    lines.append("- Saved items include: pinned point (or pinned hour label) and enabled series modes.")
    lines.append("")

    lines.append("## 7. Display Modes")
    lines.append("")
    lines.append("### 7.1 Small dashboard mode")
    lines.append("")
    lines.append("- Default mode. Most components are visible (cards, usage chart, controls/transport).")
    lines.append("- The big TV frame is hidden by the body class `hide-big-chart` and shown by removing it.")
    lines.append("")
    lines.append("### 7.2 Big TV / full-screen mode")
    lines.append("")
    lines.append("- Enabled by adding `tv-mode` to `document.body`.")
    lines.append("- Many small-mode elements are hidden by CSS in TV mode.")
    lines.append("- Navigation and controls are provided through the overlay and bottom bar.")
    lines.append("")
    lines.append("### 7.3 Enter/exit")
    lines.append("")
    lines.append("- Enter: double-click either chart.")
    lines.append("- Exit: press `Escape` or double-click again.")
    lines.append("")

    lines.append("## 8. Form Behavior")
    lines.append("")
    lines.append("There is no form submission. This is a single-page UI with state stored in memory and localStorage.")
    lines.append("")
    lines.append("- **Updates dynamically:** cards, totals, chart visibility, tooltips, selection indicators, history status.")
    lines.append("- **Does not reset unless changed:** selected series modes and pinned selection (persisted).")
    lines.append("- **Resets on archive load:** chart datasets/labels are replaced, then the UI attempts to re-apply saved pin/modes.")
    lines.append("")

    lines.append("## 9. Chatbot Interaction")
    lines.append("")
    lines.append("From the dashboard code, the chatbot is accessed via a link and is not embedded in the dashboard.")
    lines.append("")
    lines.append("- **Used for:** explaining what is on screen and guiding the operator through the UI.")
    lines.append("- **Allowed actions (based on dashboard code):** the dashboard itself exposes no server endpoints; the chatbot cannot directly change thermostat settings through this page.")
    lines.append("- **What it can realistically do:** instruct the operator to click specific dashboard controls and interpret the resulting state.")
    lines.append("")

    lines.append("## 10. Function Reference (Critical Section)")
    lines.append("")
    lines.append("### 10.1 Python generator functions")
    lines.append("")
    py_funcs = _extract_functions_with_callers(dashboard_py)
    lines.append(f"{len(py_funcs)} functions found in `{dash_name}`.")
    lines.append("")
    lines.append("| Function | Docstring | Called by | Returns value |")
    lines.append("|---|---|---|---|")
    for fn in py_funcs:
        doc = fn.doc or "—"
        called_by = ", ".join(fn.called_by) if fn.called_by else "—"
        returns = "Yes" if fn.returns_value else "No/None"
        lines.append(
            f"| `{_md_escape(fn.signature)}` | {_md_escape(doc)} | {_md_escape(called_by)} | {returns} |"
        )
    lines.append("")
    lines.append("### 10.2 JavaScript UI functions (key operators)")
    lines.append("")
    lines.append("This manual references these primary UI functions in `dashboard_client.js` (not exhaustive):")
    lines.append("")
    lines.append("- `applyDashboardData(data, slugHint)` — apply new payload and redraw UI")
    lines.append("- `loadDashboardData(slug)` — fetch an archive JSON file")
    lines.append("- `scheduleArchiveLoadWithTapeRules(slug, pinIndexAfterLoad)` — animate tape then load")
    lines.append("- `toggleMode(mode)` / `setModeSet(modes)` — control which datasets are visible")
    lines.append("- `bindChartPointPicker()` / `setSelectedPoint(...)` — hover/pin point selection")
    lines.append("- `renderUsageSlotChart()` — build the runtime aggregation bar chart")
    lines.append("- `enterTvMode()` / `exitTvMode()` — full-screen display mode")
    lines.append("")

    lines.append("## 11. Typical Usage Flow")
    lines.append("")
    lines.append("1. Open the dashboard page; it initializes from embedded JSON.")
    lines.append("2. If Auto-play starts and you want manual control, move the mouse or click to stop it.")
    lines.append("3. Use the front-panel cards to read current status; show/hide series for clarity.")
    lines.append("4. Show the main chart and hover to preview points; click to pin a moment in time.")
    lines.append("5. Use history navigation (history list, transport nav, arrow keys) to load a prior day; watch for the tape spin then redraw.")
    lines.append("6. Use << / >> to step within the day (and optionally across days via edge wrapping).")
    lines.append("7. Double-click to enter TV mode for a big-screen view; navigate with overlays; press Escape to exit.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    here = Path(__file__).resolve()
    dashboard_py = here.parent / "Dashboard.py"
    client_js = here.parent / "dashboard_client.js"
    out_path = here.parent.parent / "Web" / "dashboard_operator_manual.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_markdown(dashboard_py, client_js), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

