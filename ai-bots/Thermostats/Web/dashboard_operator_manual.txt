# Thermostat Dashboard — Operator Manual (Primary Source of Truth)

This file is the **primary documentation source of truth** for the thermostat dashboard. It is written to be consumed by both humans and an embedded help chat system.

- **Primary manual (this file):** `ai-bots/Thermostats/Web/dashboard_operator_manual.md`
- **Derived artifacts:** `ai-bots/Thermostats/Web/dashboard_operator_manual.pdf`, `ai-bots/Thermostats/Web/dashboard_operator_manual.txt`

## Source of truth (code + UI)

This manual is grounded in these files:

- `ai-bots/Thermostats/scripts/Dashboard.py` — Python generator (builds `dashboard_public.html`)
- `ai-bots/Thermostats/scripts/dashboard_client.js` — browser UI logic (all interactive behavior)
- `ai-bots/Thermostats/Web/dashboard_public.html` — generated output (HTML/CSS structure)

Important: the dashboard UI runs as **static HTML + JavaScript in the browser**. Clicking UI controls does **not** execute Python on a server.

---

## 1. What This Dashboard Is

### 1.1 What system it monitors

This dashboard monitors a thermostat/HVAC telemetry dataset stored as spreadsheet rows. The generator reads a Google Sheet and renders the dashboard page.

### 1.2 What problem it solves

It converts row-based readings into:

- a “front panel” of current values (cards)
- interactive charts (history chart + usage chart)
- a day-by-day archive navigation mechanism (the “data cassette/transport”)

### 1.3 Who it is designed for

An operator who needs to understand **what is happening now** and **how things changed over time**, without reading raw spreadsheet data.

---

## 2. Mental Model of the System

### 2.1 The “cassette” metaphor

Treat the dashboard like a **data player**:

- A **cassette** = a **single day** of saved readings (an archive day).
- The **transport** = how you move **between days** (load a different archive day).
- The **chart cursor** = how you move **within a day** (choose a point index).
- The **cards** = show values for the selected point (hover/pin).

### 2.2 What the cassette represents (real terms)

- **Current dataset** is embedded directly in the HTML as JSON in:
  - `<script id="dashboard-data-inline" type="application/json">…</script>`
- **Archive datasets** are fetched by the browser from:
  - `ai-bots/Thermostats/Web/chart hist/<YYYY-MM-DD>.json`
- **Time/indexing model**:
  - arrays are aligned by index (same index = same moment)
  - key arrays include `chartLabels[]`, `actual[]`, `setpoint[]`, `outside[]`, `cooling[]`, `fan[]`, `condenserMinutes[]`

### 2.3 What “cassette spinning” means (exactly)

- The cassette reels spin when the deck element has CSS class `playing`.
- JavaScript sets these CSS variables on the deck before starting the timer:
  - `--deck-spin-direction` (`normal` or `reverse`)
  - `--deck-spin-duration` (e.g., `1.35s`)
- After the spin timer, the UI loads the target archive JSON and redraws the dashboard.

---

## 3. Layout Overview (Small Mode vs TV Mode)

### 3.1 Small mode major areas

1. **Front-panel cards** (`#Cards`)
   - shows current/selected values (temperature, setpoint, modes, request metadata)
2. **Usage chart panel** (`#usage-slot`)
   - bar chart summarizing condenser runtime (range selectable)
3. **History/controls/transport block**
   - chart series toggles (`.chart-control[data-mode]`)
   - auto-play toggle (`#autoplay-toggle`)
   - chart step controls (`#chart-step-prev`, `#chart-step-next`, `#chart-step-value`)
   - history selector (`#chart-history`, `#chart-history-list`)
   - cassette deck/transport (`#transport-panel`, `#transport-deck`, injected `#archive-prev`/`#archive-next` buttons)

### 3.2 TV mode major areas

TV mode is a full-screen presentation mode driven by CSS class `tv-mode` on `<body>`.

In TV mode:

- the main chart is shown full-screen inside the TV frame
- the bottom bar shows history status and a tape reader deck (`#tv-transport-deck`)
- TV navigation overlay provides step mode and archive prev/next (`#tv-archive-prev`, `#tv-archive-next`)
- most small-mode elements are hidden by CSS

---

## 4. Data Cassette & Archive Loading

### 4.1 What happens when an archive day is loaded

The UI uses a date slug in the format `YYYY-MM-DD`.

Sequence:

1. UI chooses a target slug.
2. UI starts tape animation (`triggerDeckSpin(...)`).
3. UI fetches archive JSON (`loadDashboardData(slug)` -> `fetch("chart hist/<slug>.json")`).
4. UI applies payload and redraws (`applyDashboardData(data, slug)`).

### 4.2 Tape animation rules (how motion relates to time)

The UI tries to make navigation feel like a tape deck:

- next day (`deltaDays == 1`): short “fast spin”
- forward jump (`deltaDays > 1`): “fast-forward” phase then a short “play” phase
- backward jump (`deltaDays <= 0`): “rewind” phase then a short “play” phase

### 4.3 Archive list pruning (missing files)

The UI validates whether archive JSON files exist and removes missing entries from the in-memory history list:

- if a fetch returns 404, it removes that date from `dashboardData.archiveDates` and re-renders the list

---

## 5. Operator Controls (Complete Index)

This section is intentionally literal and maps each visible control to its behavior.

### 5.1 Embedded Help Chat (in-dashboard)

- **Open button:** `#help-chat-toggle` (“Help Chat”)
- **Panel:** `#help-chat-panel`
- **Close:** `#help-chat-close` (×)
- **Messages container:** `#help-chat-messages`
- **Input:** `#help-chat-input`
- **Submit:** `#help-chat-form` / `#help-chat-send`
- **Behavior:**
  - opens/closes a panel (no page navigation)
  - sends `POST` to the backend endpoint defined by `#help-chat-panel[data-endpoint]`
  - payload includes `{ question, state }` where `state` includes view mode, chart swap state, archive slug, pinned selection, and enabled modes

### 5.2 Main history chart series toggles (datasets)

Buttons: `.chart-control[data-mode]`

- `data-mode="setpoint"`: show/hide setpoint dataset
- `data-mode="actual"`: show/hide building temperature dataset
- `data-mode="outside"`: show/hide outside temperature dataset
- `data-mode="cooling"`: show/hide AC status dataset (Idle/Cooling)
- `data-mode="fan"`: show/hide fan mode dataset (Auto/Circulate/On)
- `data-mode="both"` (“Combined”): toggles all datasets as a group

Implementation:

- handler: `toggleMode(mode)`
- state: `enabledModes` Set
- persistence: saved to `localStorage` (see section 8)

### 5.3 Auto-play toggle

- **Control:** `#autoplay-toggle`
- **Behavior:**
  - toggles a mode where, after idle time, the UI cycles through modes and highlights points
  - user interaction stops auto-play and re-schedules it
- Implementation:
  - `bindAutoplayInteractions()`, `scheduleAutoplay()`, `startAutoplay()`, `stopAutoplay()`

### 5.4 Show/Hide history chart (canvas visibility)

- **Control:** `#toggle-history`
- **Behavior:**
  - `Show History Chart` -> makes canvas visible
  - `Hide History Chart` -> hides canvas
- Implementation: `showChart()` / `hideChart()`

### 5.5 Chart point selection (hover, pin, clear pin)

#### Hover

- event: `mousemove` on main chart canvas (`#history-chart`)
- behavior: if nothing is pinned, hovering updates the selection and card values

#### Pin/unpin

- event: `click` on main chart canvas (`#history-chart`)
- behavior:
  - click a point -> pin it
  - click the same pinned point again -> unpin it
  - click away (no point) -> clears pin and suppresses hover until mouseleave

#### Clear Pin button

- control: `#clear-pin` (created dynamically by JS in `ensureSelectionUi()`)
- visibility: only shown when a point is pinned
- behavior: clears pin and persists state

#### Selection indicator

- element: `#selection-indicator` (created dynamically)
- shows `Pinned: <time>` or `Hover: <time>`

### 5.6 Step through points (within-day)

- **Prev:** `#chart-step-prev` (<<)
- **Next:** `#chart-step-next` (>>)
- **Readout:** `#chart-step-value`

Behavior:

- steps by one point index (`stepPinnedPoint(delta)`)
- if stepping beyond the first/last point:
  - loads the adjacent day (if available)
  - pins to the opposite edge (index 0 or last)
- supports hold-to-repeat (press-and-hold)

### 5.7 Usage chart (runtime summary)

#### Range buttons

Buttons: `.usage-control[data-range]`

- `data-range="7d"`: last 7 days (based on available archives)
- `data-range="month"`: current month (based on archive slug UTC month)
- `data-range="year"`: aggregates by month for the current year (UTC)

Implementation: `bindUsageSlotControls()` sets `usageRangeKey` then calls `renderUsageSlotChart()`.

#### Clicking a bar

Clicking a bar in the usage chart loads the archive day associated with that bar by calling `loadDashboardData(slug)`.

### 5.8 History list (archive picker)

Core elements:

- container: `#chart-history`
- toggle header: `#chart-history-toggle`
- status label: `#chart-history-status`
- list: `#chart-history-list`

Behavior:

- archive list is built by `renderArchiveList()` and includes:
  - a month picker (last 12 months)
  - day entries for the selected month
- selecting a day:
  - closes the history panel
  - schedules a tape animation and then loads the day (`scheduleArchiveLoadWithTapeRules(slug)`)

### 5.9 Transport panel (deck + day/month stepping)

Elements:

- panel: `#transport-panel`
- deck: `#transport-deck`
- step mode radios: `#transport-step-month` / `#transport-step-day`
- nav container: `#transport-nav` (JS injects buttons here)

Behavior:

- clicking the panel toggles the history list (unless you clicked on an interactive element inside)
- injected nav buttons:
  - `#archive-prev` / `#archive-next` (created by JS)
  - behavior depends on transport step mode (day vs month)

### 5.10 Keyboard shortcuts

Handled by `bindArchiveKeyboardShortcuts()`:

- `ArrowLeft`: navigate back (day/month, or hour stepping when TV step mode is “Time”)
- `ArrowRight`: navigate forward
- In TV mode:
  - `Escape`: exits TV mode

---

## 6. Click & Double-Click Behavior (Global Rules)

### 6.1 Double-click enters/exits TV mode

- double-click main chart (`#history-chart`) OR usage chart (`#usage-slot-chart`) -> enter TV mode
- double-click while in TV mode -> exit TV mode
- `Escape` exits TV mode

### 6.2 Axis click swaps charts (special click zone)

The UI treats clicks in the X-axis label area as “swap charts”:

- clicking below the chart area boundary can swap which chart appears in the TV frame vs usage slot (`applyChartSwap(...)`)

---

## 7. Display Modes

### 7.1 Small mode

Default. Most components visible.

### 7.2 TV mode

Enabled by adding `tv-mode` to `<body>`.

In TV mode, CSS hides many small-mode elements and shows TV overlays/bottom bar.

---

## 8. State & Persistence (What is remembered)

### 8.1 Local storage key

The UI persists state to:

- `localStorage["thermostatDashboard.ui.v1"]`

### 8.2 What is saved

Saved in `saveUiState()`:

- pinned point index (when available)
- pinned hour label (used for matching after archive loads)
- enabled dataset modes (`enabledModes`)

### 8.3 What happens on archive load

When loading a new archive:

- the UI tries to restore your pinned selection by matching the saved pinned hour label to the new day’s labels
- if a pending pin index is specified (edge-wrapping behavior), it applies that instead

---

## 9. Help Chat Contract (No hallucinations)

The embedded help chat must follow these rules:

- Answers must be grounded only in this manual’s text.
- If this manual does not contain the requested information, the response must be:

`That information is not available in the documentation.`

---

## 10. Function Reference (Operator-Relevant)

### 10.1 Python generator (Dashboard.py)

The Python script generates the HTML and may also stage/commit/push generated artifacts depending on configuration.

Key outputs:

- `ai-bots/Temp/dashboard.html` (temp build output)
- `ai-bots/Thermostats/Web/dashboard_public.html` (published copy)
- `ai-bots/Thermostats/Web/chart hist/<YYYY-MM-DD>.{html,json}` (archive snapshots)
- `ai-bots/Thermostats/Web/dashboard_data.json` (latest payload)

### 10.2 JavaScript UI (dashboard_client.js)

Primary operator-facing functions:

- `applyDashboardData(data, slugHint)` — replace payload and redraw UI
- `loadDashboardData(slug)` — fetch an archive JSON payload
- `scheduleArchiveLoadWithTapeRules(slug, pinIndexAfterLoad)` — animate tape then load
- `toggleMode(mode)` / `setModeSet(modes)` — dataset visibility
- `bindChartPointPicker()` / `setSelectedPoint(...)` — hover/pin logic
- `renderUsageSlotChart()` — runtime aggregation chart
- `enterTvMode()` / `exitTvMode()` — TV mode transitions

---

## 11. Typical Operator Walkthrough

1. Open the dashboard page. It initializes from embedded JSON.
2. If Auto-play is running and you want manual control, move the mouse or click the page to stop it.
3. Read the cards to understand current state.
4. Click dataset buttons to simplify the view (e.g., only Set Point + Building Temp).
5. Show the history chart and hover points to preview values; click to pin a time.
6. Use the history list or transport nav to load another day; watch the tape animation and wait for the redraw.
7. Use << / >> to step point-by-point; note edge wrapping can load adjacent days.
8. Double-click to enter TV mode for big-screen viewing; use TV controls; press Escape to exit.

