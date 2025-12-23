# Thermostat Dashboard — Operator Manual (Primary Source of Truth)

This file is the **primary documentation source of truth** for the thermostat dashboard. It is written to be consumed by both humans and an embedded help/chat system.

- **Primary manual (this file):** `ai-bots/Thermostats/Web/dashboard_operator_manual.md`
- **Derived artifacts:** `ai-bots/Thermostats/Web/dashboard_operator_manual.pdf`, `ai-bots/Thermostats/Web/dashboard_operator_manual.txt`

---

## 0. How To Use This Manual (Keyword Lookup)
[tags: help, search, lookup, keyword, tags, glossary]

### What this is
This manual is structured for concept-based lookup. Each major section includes a `[tags: ...]` line with common words a user might type.

### How to use it (explicit actions)
- Type a keyword (example: `tv`, `display`, `rewind`, `cassette`, `autoplay`, `pin`, `history`, `usage`).
- Prefer the “human” term you see on screen (example: `help`, `history`, `transport`, `cassette`).

### What happens when used
- A help system can use tags/headings to find the most relevant section(s) and return the content from those sections.

### What does NOT change (state preservation)
- This manual is the only source of truth for help answers. If something is not described here, it must not be explained as if it exists.

### Caveats or limitations
- If no tags/headings match a term, the help system should respond with: `No documentation matches that term.`

---

## Source of truth (code + UI)
[tags: source, code, ui, html, javascript, python, static]

### What this is
This manual is grounded in these files:

- `ai-bots/Thermostats/scripts/Dashboard.py` — Python generator (builds `dashboard_public.html`)
- `ai-bots/Thermostats/scripts/dashboard_client.js` — browser UI logic (all interactive behavior)
- `ai-bots/Thermostats/Web/dashboard_public.html` — generated output (HTML/CSS structure)

### How to use it (explicit actions)
- Use these files to verify any claimed behavior before adding it to this manual.

### What happens when used
- The dashboard UI runs as **static HTML + JavaScript in the browser**. Clicking dashboard controls does **not** execute Python on a server.

### What does NOT change (state preservation)
- The UI behavior described in this manual is based on the code paths above.

### Caveats or limitations
- If behavior changes in code, update this manual first (the PDF is derived).

---

## 1. What This Dashboard Is
[tags: overview, dashboard, thermostat, hvac, telemetry, monitoring, purpose]

### What this is
This dashboard monitors a thermostat/HVAC telemetry dataset stored as spreadsheet rows. The generator reads a Google Sheet and renders the dashboard page.

### How to use it (explicit actions)
- Open the dashboard page in a browser.
- Use the charts and navigation controls to understand what changed over time.

### What happens when used
It converts row-based readings into:

- a “front panel” of current/selected values (cards)
- interactive charts (history chart + usage chart)
- a day-by-day archive navigation mechanism (the “data cassette/transport”)

### What does NOT change (state preservation)
- Clicking UI controls changes the browser UI; it does not run Python server-side.

### Caveats or limitations
- This dashboard displays what is present in the embedded JSON and archive files it loads.

---

## 2. Mental Model: Data, Time, and Indexing
[tags: data, time, timeline, index, labels, cursor, point, selection]

### What this is
Treat the dashboard like a **data player**:

- A **cassette** = a **single day** of saved readings (an archive day).
- The **transport** = how you move **between days** (load a different archive day).
- The **chart cursor** = how you move **within a day** (choose a point index).
- The **cards** = show values for the selected point (hover/pin).

The data model is index-based:

- Arrays are aligned by index (same index = same moment).
- Key arrays include `chartLabels[]`, `actual[]`, `setpoint[]`, `outside[]`, `cooling[]`, `fan[]`, `condenserMinutes[]`.

### How to use it (explicit actions)
- Use the history chart to move point-by-point within a day (hover/pin/step).
- Use the transport/history list to move day-by-day (load a different cassette/day).

### What happens when used
- The UI uses the selected point index to decide what values to show on the cards.

### What does NOT change (state preservation)
- The loaded day does not change until you explicitly load another archive day.

### Caveats or limitations
- This manual does not assume real-world timestamps beyond what `chartLabels[]` provides.

---

## 3. Layout Overview (Small Mode vs TV Mode)
[tags: layout, screen, panels, cards, chart, usage, history, transport, tv]

### What this is
In small (default) mode the page is arranged into major areas:

1. **Front-panel cards** (`#Cards`) — shows current/selected values.
2. **Usage chart panel** (`#usage-slot`) — bar chart summarizing condenser runtime (range selectable).
3. **History/controls/transport block** — dataset toggles, auto-play, step controls, history selector, and the cassette transport.

### How to use it (explicit actions)
- Use dataset toggle buttons to simplify the history chart view.
- Use the history list or transport controls to load a different day.
- Use TV mode (see section 7) for full-screen display.

### What happens when used
- Controls in the history/transport area affect what day is loaded and what point is selected.

### What does NOT change (state preservation)
- Layout changes (small vs TV) do not fetch new data by themselves.

### Caveats or limitations
- Some elements are hidden in TV mode by CSS.

---

## 4. Charts (History Chart and Usage Chart)
[tags: chart, charts, history chart, usage chart, timeline, runtime, bar chart]

### What this is
This dashboard has **two charts**:

1. **History chart** (thermostat timeline chart)
   - Purpose: show how readings change across time points within the loaded day.

2. **Usage chart** (runtime summary bar chart)
   - Purpose: summarize condenser runtime across a selected range (7 days / month / year).

### How to use it (explicit actions)
- History chart:
  - Click dataset buttons (`.chart-control[data-mode]`) to show/hide series.
  - Hover points to preview card values; click a point to pin it.
  - Use step buttons (`#chart-step-prev`, `#chart-step-next`) to move point-by-point.
- Usage chart:
  - Click range buttons (`.usage-control[data-range]`) to change the aggregation range.
  - Click a bar to load the archive day behind that bar.

### What happens when used
- Dataset toggles update which series are drawn on the history chart.
- Point selection (hover/pin) changes what values the cards show for the loaded day.
- Clicking a usage bar loads the associated day (archive slug) by calling `loadDashboardData(slug)`.

### What does NOT change (state preservation)
- Dataset toggles do not change the loaded day by themselves.
- Usage range changes do not change the loaded day until you click a bar.

### Caveats or limitations
- If a needed archive JSON file is missing, a 404 can cause that date to be removed from the in-memory archive list (see section 6).

---

## 5. Selecting a Time Point (Hover, Pin, Clear Pin, Step)
[tags: chart, history chart, hover, pin, selection, cursor, point, step, previous, next, clear]

### What this is
The dashboard supports selecting a specific “time point” within the loaded day using the history chart.

### How to use it (explicit actions)
- Hover:
  - Move the mouse over the history chart (`#history-chart`).
- Pin / unpin:
  - Click a point on the history chart to pin it.
  - Click the same pinned point again to unpin it.
  - Click away (no point) to clear pin and suppress hover until mouseleave.
- Clear Pin button:
  - Click `#clear-pin` (only visible when a point is pinned).
- Step buttons:
  - Click `#chart-step-prev` (<<) or `#chart-step-next` (>>) to step.
  - Press-and-hold supports hold-to-repeat.

### What happens when used
- Hover updates the selection and card values **only when nothing is pinned**.
- Pinning locks the selection to that point until unpinned/cleared.
- Stepping changes the pinned point index. If stepping beyond the first/last point:
  - it loads the adjacent day (if available)
  - then pins to the opposite edge (index 0 or last)

### What does NOT change (state preservation)
- Selection changes do not modify the underlying data; they only choose which index to display.

### Caveats or limitations
- The selection UI elements `#clear-pin` and `#selection-indicator` are created dynamically by JavaScript (`ensureSelectionUi()`).

---

## 6. Data Cassette, Transport, and Archive Loading
[tags: cassette, tape, transport, archive, load, day, month, previous day, next day]

### What this is
Archive navigation is modeled like a tape deck:

- A **cassette** represents a single day (archive slug `YYYY-MM-DD`).
- The **transport** loads a different day by fetching `chart hist/<YYYY-MM-DD>.json`.
- The deck animation (spin/rewind/fast-forward) is a UI cue during archive changes.

### How to use it (explicit actions)
- Use the history list (section 8) to select a day to load.
- Use transport navigation buttons (`#archive-prev`, `#archive-next`) to step by day or month (depending on step mode).
- Use keyboard arrows to navigate (section 9).

### What happens when used
Archive load sequence:

1. UI chooses a target slug.
2. UI starts tape animation (`triggerDeckSpin(...)`).
3. UI fetches archive JSON (`loadDashboardData(slug)` -> `fetch("chart hist/<slug>.json")`).
4. UI applies payload and redraws (`applyDashboardData(data, slug)`).

### What does NOT change (state preservation)
- Tape animation is visual; the actual day change happens when the archive JSON is loaded and applied.

### Caveats or limitations
- If an archive JSON fetch returns 404, the UI removes that date from `dashboardData.archiveDates` and re-renders the list.

---

## 6A. Tape Animation (“Spin”, “Rewind”, “Fast-Forward”)
[tags: tape, cassette, rewind, fast-forward, spin, play, animation]

### What this is
When the dashboard loads a different archive day, it animates the cassette deck as a visual cue. The reels spin when the deck element has CSS class `playing`.

### How to use it (explicit actions)
- Load another day (via history list, transport controls, usage bar click, or keyboard navigation).
- Watch the cassette animation while the archive file loads.

### What happens when used
The UI tries to make navigation feel like a tape deck:

- Next day (`deltaDays == 1`): short “fast spin”.
- Forward jump (`deltaDays > 1`): “fast-forward” phase then a short “play” phase.
- Backward jump (`deltaDays <= 0`): “rewind” phase then a short “play” phase.

### What does NOT change (state preservation)
- The animation itself does not change data. The day changes only when the archive JSON is successfully loaded and applied.

### Caveats or limitations
- “Rewind/fast-forward” describe the animation and sequencing; the actual load still depends on fetching `chart hist/<YYYY-MM-DD>.json`.

---

## 7. Display / TV Mode (Full-Screen)
[tags: tv, display, television, screen, fullscreen, full screen, big, presentation, tv mode]

### What this is
TV mode is a full-screen presentation mode driven by CSS class `tv-mode` on `<body>`.

### How to use it (explicit actions)
- Enter TV mode:
  - Double-click the main history chart (`#history-chart`) OR the usage chart (`#usage-slot-chart`).
- Exit TV mode:
  - Double-click while in TV mode, or press `Escape`.

### What happens when used
- When entering TV mode:
  - The TV frame is revealed (`hide-big-chart` is removed).
  - If charts are swapped, the UI switches back so TV mode defaults to the thermostat/history chart (`applyChartSwap(false)`).
  - The body receives `tv-mode` and TV overlays/bottom bar are shown.
- When exiting TV mode:
  - The body removes `tv-mode` and the TV history mount is removed (`unmountTvHistory()`).
  - The prior chart swap state is restored (if it changed in TV mode).
  - The prior “hide big chart” state is restored.

### What does NOT change (state preservation)
- Entering/exiting TV mode does not load a new archive day by itself.
- Exiting TV mode restores the previous chart-swap state and previous big-chart visibility state.
- Entering/exiting TV mode does not change the current point selection (pinned/hovered index); it only changes layout.

### Caveats or limitations
- In TV mode, CSS hides many small-mode elements and shows TV overlays/bottom bar.
- TV mode defaults to the thermostat/history chart; the usage chart can be shown in the TV frame via chart swap.

---

## 8. History List (Archive Picker)
[tags: history list, archive picker, dates, calendar, month, day, list]

### What this is
The history list is the UI for selecting a specific archive day to load.

Core elements:

- container: `#chart-history`
- toggle header: `#chart-history-toggle`
- status label: `#chart-history-status`
- list: `#chart-history-list`

### How to use it (explicit actions)
- Open the history list using the history UI on the page.
- Choose a month from the month picker (last 12 months).
- Click a day entry to load it.

### What happens when used
- Archive list is built by `renderArchiveList()`.
- Selecting a day:
  - closes the history panel
  - schedules tape animation and loads the day (`scheduleArchiveLoadWithTapeRules(slug)`)

### What does NOT change (state preservation)
- Opening/closing the list does not load data until you select a day.

### Caveats or limitations
- If a selected day’s JSON is missing (404), that day can be removed from the list (section 6).

---

## 9. Keyboard Shortcuts
[tags: keyboard, shortcuts, arrows, left, right, escape, tv]

### What this is
Keyboard navigation is handled by `bindArchiveKeyboardShortcuts()`.

### How to use it (explicit actions)
- `ArrowLeft`: navigate back (day/month, or hour stepping when TV step mode is “Time”).
- `ArrowRight`: navigate forward.
- `Escape`: exits TV mode.

### What happens when used
- Navigation triggers the same archive and stepping logic used by on-screen controls.

### What does NOT change (state preservation)
- Keyboard shortcuts do not introduce additional actions beyond the documented UI controls.

### Caveats or limitations
- Keyboard shortcuts apply while the dashboard page has focus.

---

## 10. Chart Swap (Special Click Zone)
[tags: swap, charts swapped, x-axis, axis, click zone, title click]

### What this is
The UI supports swapping which chart appears in the TV frame vs the usage slot.

### How to use it (explicit actions)
- Click the usage panel title (`#usage-slot .title`) to swap charts.
- In TV mode, clicking the X-axis label area can swap charts (`applyChartSwap(...)`).

### What happens when used
- Swapping changes which chart is mounted where (TV frame vs usage slot).

### What does NOT change (state preservation)
- Swapping charts does not load a different archive day.
- Exiting TV mode restores the swap state that was active before TV mode (section 7).

### Caveats or limitations
- The “axis click swaps charts” behavior is a special click zone; it is not a general click anywhere on the chart.

---

## 11. Embedded Help Chat (In-Dashboard)
[tags: help, chat, documentation, manual, ask, question]

### What this is
The dashboard includes an embedded help chat panel that answers questions using only this manual’s text.

Core elements:

- **Open button:** `#help-chat-toggle` (“Help Chat”)
- **Panel:** `#help-chat-panel`
- **Close:** `#help-chat-close` (×)
- **Messages container:** `#help-chat-messages`
- **Input:** `#help-chat-input`
- **Submit:** `#help-chat-form` / `#help-chat-send`

### How to use it (explicit actions)
- Click “Help Chat” to open the panel.
- Type a question (or a keyword) and click “Send”.

### What happens when used
- The help panel loads the manual file from `#help-chat-panel[data-manual-url]`.
- Your input is used to find matching sections based on headings and `[tags: ...]`.
- The matching manual sections are shown verbatim in the chat.

### What does NOT change (state preservation)
- Opening/closing the help chat does not navigate away from the dashboard.

### Caveats or limitations
- Help answers must be grounded only in this manual. If the manual does not contain the requested information, the help system must not invent an answer.
- If no tags/headings match your term, the help system should respond with: `No documentation matches that term.`

---

## 12. State & Persistence (What is remembered)
[tags: state, saved, remember, persistence, localstorage, settings, modes]

### What this is
Some UI state is persisted in browser `localStorage` under:

- `localStorage["thermostatDashboard.ui.v1"]`

### How to use it (explicit actions)
- Make a selection (pin a point) and/or toggle datasets; these can persist across reloads.

### What happens when used
Saved in `saveUiState()`:

- pinned point index (when available)
- pinned hour label (used for matching after archive loads)
- enabled dataset modes (`enabledModes`)

When loading a new archive:

- the UI tries to restore your pinned selection by matching the saved pinned hour label to the new day’s labels
- if a pending pin index is specified (edge-wrapping behavior), it applies that instead

### What does NOT change (state preservation)
- Persistence affects UI defaults; it does not modify the underlying archive files.

### Caveats or limitations
- Only the listed items are documented as saved.

---

## 13. Function Reference (Operator-Relevant)
[tags: functions, reference, code, dashboard.py, dashboard_client.js]

### What this is
This section maps operator-visible behaviors to the key functions involved.

### How to use it (explicit actions)
- Use this section when you need to verify what code path a control triggers.

### What happens when used
Key outputs (generator):

- `ai-bots/Temp/dashboard.html` (temp build output)
- `ai-bots/Thermostats/Web/dashboard_public.html` (published copy)
- `ai-bots/Thermostats/Web/chart hist/<YYYY-MM-DD>.{html,json}` (archive snapshots)
- `ai-bots/Thermostats/Web/dashboard_data.json` (latest payload)

Primary operator-facing JavaScript functions:

- `applyDashboardData(data, slugHint)` — replace payload and redraw UI
- `loadDashboardData(slug)` — fetch an archive JSON payload
- `scheduleArchiveLoadWithTapeRules(slug, pinIndexAfterLoad)` — animate tape then load
- `toggleMode(mode)` / `setModeSet(modes)` — dataset visibility
- `bindChartPointPicker()` / `setSelectedPoint(...)` — hover/pin logic
- `renderUsageSlotChart()` — runtime aggregation chart
- `enterTvMode()` / `exitTvMode()` — TV mode transitions

### What does NOT change (state preservation)
- This reference does not replace the behavioral sections above; it exists to support verification and maintenance.

### Caveats or limitations
- If function names change, update this section so keyword lookup remains accurate.

---

## 14. Typical Operator Walkthrough
[tags: walkthrough, steps, first time, operator, how to]

### What this is
A concrete “first run” workflow from launch to navigation and TV mode.

### How to use it (explicit actions)
Follow these steps in order:

1. Open the dashboard page. It initializes from embedded JSON.
2. If Auto-play is running and you want manual control, move the mouse or click the page to stop it.
3. Read the cards to understand current state.
4. Click dataset buttons to simplify the view (e.g., only Set Point + Building Temp).
5. Show the history chart and hover points to preview values; click to pin a time.
6. Use the history list or transport nav to load another day; watch the tape animation and wait for the redraw.
7. Use << / >> to step point-by-point; note edge wrapping can load adjacent days.
8. Double-click to enter TV mode for big-screen viewing; press Escape to exit.

### What happens when used
- You will see the cards, charts, and selected time point update as you navigate.

### What does NOT change (state preservation)
- Entering/exiting TV mode does not load a new archive day unless you explicitly navigate.

### Caveats or limitations
- If you use a keyword that is not present in any tags/headings, the help system should report that no documentation matched (section 0).
