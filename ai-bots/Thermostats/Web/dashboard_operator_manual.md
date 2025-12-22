# Thermostat Dashboard — Operator Manual

This manual is written for a first-time operator. It explains how the dashboard behaves **based on the shipped UI structure and source code**.

**Source of truth files:**
- `C:/ChatGPT/ai-bots/Thermostats/scripts/Dashboard.py` (Python generator)
- `C:/ChatGPT/ai-bots/Thermostats/scripts/dashboard_client.js` (Browser UI logic)
- `ai-bots/Thermostats/Web/dashboard_public.html` (generated output)

> Note: This dashboard runs as static HTML + JavaScript in the browser. Clicking controls does **not** execute Python on a server.

## 1. What This Dashboard Is

- **What system it controls/monitors:** a thermostat/HVAC telemetry dataset (project folder name: `Thermostats`). The Python script reads rows from a Google Sheet and generates a dashboard page.
- **What problem it solves:** converts raw rows (timestamps, temperatures, modes, runtime) into a readable “front panel” plus charts, and lets the operator load prior days as archived snapshots.
- **Who it is designed for:** someone operating/monitoring the system who needs to understand current status and trends without reading the raw sheet.

## 2. Mental Model of the System

Think of the dashboard as a **data player** with a cassette deck:

- A **cassette** represents **one day of saved data** (an “archive day”).
- The **transport** moves **between days** (loads a different archive JSON file).
- The **chart cursor** moves **within a day** (picks a point index).
- The **front-panel cards** show values for the currently selected point (hover/pin).

### What the cassette represents in real terms

- **Current data** is embedded into the HTML in a `<script id="dashboard-data-inline" type="application/json">…</script>` block.
- **Archive data** is loaded from `ai-bots/Thermostats/Web/chart hist/<YYYY-MM-DD>.json` using `fetch()` in the browser.
- **Time indexing** is array-based: a point index selects aligned values across arrays like `chartLabels[]`, `actual[]`, `setpoint[]`, `outside[]`, `cooling[]`, `fan[]`, etc.

### What the spinning cassette means

- The reels spin when the deck element has CSS class `playing`.
- Direction and speed are controlled by CSS variables `--deck-spin-direction` and `--deck-spin-duration` that the JavaScript sets before scheduling the archive load.

## 3. Layout Overview

### Major areas (small mode)

- **A. Front-panel cards** (`#Cards`): current values (temps, modes, etc.).
- **B. Usage chart** (`#usage-slot`): bar chart of condenser runtime totals across a selected range (7 days / month / year).
- **C. Controls + history + transport**: series toggles, auto-play, step buttons, and a cassette transport panel used to navigate archived days.

### TV mode (big/full-screen mode)

- **TV frame** shows the main history chart full-screen.
- **Bottom bar** shows a history selector and a tape reader deck.
- **Overlay controls** provide chart mode buttons and navigation.

## 4. Data Cassette

### What happens when a cassette (archive day) is loaded

From `dashboard_client.js`:

1. The UI chooses an archive **slug** (format `YYYY-MM-DD`).
2. The UI starts the tape animation (`triggerDeckSpin(...)`).
3. After the spin timer, it calls `loadDashboardData(slug)` which fetches `chart hist/<slug>.json`.
4. On success, it calls `applyDashboardData(data, slug)` which replaces in-memory state and redraws charts/cards.

### Transport controls vs. time navigation

- **Between-day navigation:** uses archive slugs (`navigateArchiveByDays(...)`, `navigateArchiveByMonths(...)`, plus the history list).
- **Within-day navigation:** uses the selected point index (`stepPinnedPoint(...)` and chart hover/pin).
- **Edge behavior:** stepping past the first/last point can load an adjacent day and pin to the opposite edge (continuous “scrolling” feel).

## 5. Buttons and Controls

> Important: buttons trigger JavaScript functions in `dashboard_client.js`. They do **not** call Python functions directly.

### 5.1 Chat Help link

- **Control:** `#help-chat-link` (“Chat Help”)
- **Click behavior:** opens the configured chatbot URL in a new tab.
- **Python function triggered:** none (static HTML link).
- **State changes:** none in the dashboard.

### 5.2 Main history chart controls (series visibility)

Controls: `.chart-control[data-mode=…]`

- `setpoint`, `actual`, `outside`, `cooling`, `fan`: toggles each dataset via `toggleMode(mode)`; redraws the chart and saves mode state to localStorage.
- `both` (“Combined”): toggles all datasets on/off as a group in `toggleMode("both")`.

### 5.3 Auto-play

- **Control:** `#autoplay-toggle`
- **Click behavior:** toggles auto-play on/off (managed by `bindAutoplayInteractions()`, `startAutoplay()`, `stopAutoplay()`).
- **What changes:** after idle time, auto-play cycles series combinations and highlights points; user interaction stops and reschedules auto-play.

### 5.4 Show/Hide History chart

- **Control:** `#toggle-history`
- **Click behavior:** toggles the main chart canvas display using `showChart()` / `hideChart()`.
- **What changes:** chart canvas visibility and button label (`Show History Chart` ↔ `Hide History Chart`).

### 5.5 Step controls (within-day point navigation)

- **Controls:** `#chart-step-prev` and `#chart-step-next`
- **Click behavior:** calls `stepPinnedPoint(-1)` or `stepPinnedPoint(1)`.
- **Hold behavior:** buttons support hold-to-repeat (`bindHoldRepeat(...)`) after a delay.
- **State changes:** updates pinned selection and the card readouts; may load adjacent days when stepping beyond edges.

### 5.6 Usage chart controls (runtime aggregation)

- **Controls:** `.usage-control[data-range="7d"|"month"|"year"]`
- **Click behavior:** sets `usageRangeKey` and calls `renderUsageSlotChart()`.
- **Click on a bar:** loads that day’s archive via `loadDashboardData(slug)`.

### 5.7 Transport panel and history list (between-day navigation)

- **History list UI:** `#chart-history` / `#chart-history-toggle` / `#chart-history-list` plus dynamic month picker built by `renderArchiveList()`.
- **Open/close history list:** controlled by `setHistoryExpanded(...)`, `showHistoryFiles()`, `hideHistoryFiles()`.
- **Selecting a day:** clicking a history entry schedules an archive load via `scheduleArchiveLoadWithTapeRules(slug)`.
- **Transport panel click:** `bindTransportHistoryToggle()` toggles the history list; it also supports “load by clicking the deck” when a pending selection is armed.

### 5.8 Keyboard shortcuts

- **Left/Right arrows:** handled by `bindArchiveKeyboardShortcuts()` to navigate (in TV mode, they respect TV step mode).
- **Escape (TV mode):** exits TV mode.

## 6. Click and Double-Click Behavior

### 6.1 Single-click selection behavior (main chart)

- Hover a point (mousemove): previews the point (updates cards) when nothing is pinned.
- Click a point: pins it (click again on same point unpins).
- Click empty area: clears pin and suppresses hover updates until the mouse leaves and re-enters.
- `Clear Pin` button appears only while pinned (created/managed in `ensureSelectionUi()` and updated by `updateSelectionIndicator()`).

### 6.2 Double-click behavior

- Double-click the main chart OR the usage chart: enter TV mode (`enterTvMode()`).
- Double-click while in TV mode: exit TV mode (`exitTvMode()`).

### 6.3 State preserved across view changes

- UI state is stored in localStorage key `thermostatDashboard.ui.v1` via `saveUiState()` and restored by `loadUiState()`.
- Saved items include: pinned point (or pinned hour label) and enabled series modes.

## 7. Display Modes

### 7.1 Small dashboard mode

- Default mode. Most components are visible (cards, usage chart, controls/transport).
- The big TV frame is hidden by the body class `hide-big-chart` and shown by removing it.

### 7.2 Big TV / full-screen mode

- Enabled by adding `tv-mode` to `document.body`.
- Many small-mode elements are hidden by CSS in TV mode.
- Navigation and controls are provided through the overlay and bottom bar.

### 7.3 Enter/exit

- Enter: double-click either chart.
- Exit: press `Escape` or double-click again.

## 8. Form Behavior

There is no form submission. This is a single-page UI with state stored in memory and localStorage.

- **Updates dynamically:** cards, totals, chart visibility, tooltips, selection indicators, history status.
- **Does not reset unless changed:** selected series modes and pinned selection (persisted).
- **Resets on archive load:** chart datasets/labels are replaced, then the UI attempts to re-apply saved pin/modes.

## 9. Chatbot Interaction

From the dashboard code, the chatbot is accessed via a link and is not embedded in the dashboard.

- **Used for:** explaining what is on screen and guiding the operator through the UI.
- **Allowed actions (based on dashboard code):** the dashboard itself exposes no server endpoints; the chatbot cannot directly change thermostat settings through this page.
- **What it can realistically do:** instruct the operator to click specific dashboard controls and interpret the resulting state.

## 10. Function Reference (Critical Section)

### 10.1 Python generator functions

46 functions found in `C:/ChatGPT/ai-bots/Thermostats/scripts/Dashboard.py`.

| Function | Docstring | Called by | Returns value |
|---|---|---|---|
| `_baseline_anchor_temps(target: date, *, full_sun: bool) -> dict[int, float]` | — | build_projected_dashboard_payload | Yes |
| `_classify_condition_from_weather(flags: List[str], precip: List[float]) -> str` | — | build_projected_dashboard_payload | Yes |
| `_col_to_index(col: str) -> int` | — | _ensure_range_includes | Yes |
| `_daterange_inclusive(start: date, end: date) -> Iterable[date]` | — | run_projected_range | No/None |
| `_day_condition(target: date) -> str` | Deterministic day condition from date only (no external/weather dependencies). Returns: "full_sun", "mixed", or "rainy". | build_projected_dashboard_payload | Yes |
| `_daylight_char_for_hour(hour: int) -> str` | — | build_projected_dashboard_payload | Yes |
| `_ensure_range_includes(range_value: str, column: str) -> str` | — | — | Yes |
| `_extract_letters(cell: str) -> str` | — | _ensure_range_includes | Yes |
| `_extract_open_meteo_day_hourly(payload: dict, target_day: date) -> tuple[List[float], List[int], List[int], List[float]]` | — | _fetch_open_meteo_hourly_for_day | Yes |
| `_fan_mode_for_hour(target: date, hour: int) -> str` | — | build_projected_dashboard_payload | Yes |
| `_fetch_open_meteo_hourly_for_day(target_day: date, tz: str, lat: float, lon: float) -> tuple[List[float], List[int], List[int], List[float]]` | — | build_projected_dashboard_payload | Yes |
| `_filter_hourly_rows(rows: List[List[str]], step: int = 12) -> List[List[str]]` | Keep roughly hourly samples (every `step` rows) plus the latest row. | — | Yes |
| `_find_index_in_headers(headers: List[str], keywords: Tuple[str, ...]) -> Optional[int]` | — | _reconstruct_history_rows_from_payload | Yes |
| `_fmt_open_meteo_outside_raw(flag: str, dayc: str, temp_f: float) -> str` | — | build_projected_dashboard_payload | Yes |
| `_format_archive_label(slug: str) -> str` | — | build_dashboard_html, run_projected_range | Yes |
| `_hourly_drop_for_condition(condition: str) -> float` | — | build_projected_dashboard_payload | Yes |
| `_http_get_json(url: str, params: dict) -> dict` | — | _fetch_open_meteo_hourly_for_day | Yes |
| `_interpolate_hourly_from_anchors(anchors: dict[int, float]) -> List[float]` | — | build_projected_dashboard_payload | Yes |
| `_load_credentials() -> Credentials` | — | get_drive_service, get_sheets_service | Yes |
| `_load_dash_config() -> dict` | Load sheet config from Thermostats config.json, then bot-assets/config.json, then defaults. | — | Yes |
| `_load_drive_credentials() -> Credentials` | Load user OAuth credentials from shared Tokens.json for Drive uploads. | get_drive_upload_service | Yes |
| `_load_float(value, default: float) -> float` | — | — | Yes |
| `_load_global_root() -> Path` | — | — | Yes |
| `_load_shared_config() -> dict` | — | — | Yes |
| `_next_version_name(desired: str, existing_names: List[str]) -> str` | — | — | Yes |
| `_normalize_flag(value, default = True) -> bool` | — | — | Yes |
| `_open_meteo_day_char(is_day_flag: int) -> str` | — | build_projected_dashboard_payload | Yes |
| `_open_meteo_flag(code: int, is_day_flag: int) -> str` | — | build_projected_dashboard_payload | Yes |
| `_parse_date_only(value: str) -> date` | — | main | Yes |
| `_reconstruct_history_rows_from_payload(payload: dict) -> Tuple[List[str], List[str], List[List[str]]]` | — | run_test_mode_dashboard | Yes |
| `_setpoint_for_hour(target: date, hour: int) -> float` | — | build_projected_dashboard_payload | Yes |
| `build_dashboard_html(headers: List[str], latest_row: List[str], history_rows: List[List[str]], output_path: Path) -> str` | — | run_live_dashboard, run_test_mode_dashboard | Yes |
| `build_projected_dashboard_payload(target: date, archive_dates: List[dict], *, weather_source: str = 'auto', simulate_requests: bool = False, request_every_days: int = 3, request_setpoint_delta_f: float = 2.0, request_setpoint_deltas_f: Optional[List[float]] = None, request_deltas_mode: str = 'random') -> tuple[dict, dict]` | Create a full dashboard payload JSON for the archive viewer, generated from date only. Returns (payload, summary). | run_projected_range | Yes |
| `fetch_sheet_data() -> Tuple[List[str], List[str], List[List[str]]]` | Return headers, latest row, and history rows. | run_live_dashboard | Yes |
| `get_drive_service()` | — | resolve_sheet_id | Yes |
| `get_drive_upload_service()` | — | push_dashboard_to_drive | Yes |
| `get_or_create_drive_folder(service, folder_name: str) -> str` | — | push_dashboard_to_drive | Yes |
| `get_sheets_service()` | — | fetch_sheet_data | Yes |
| `git_autopush(html_path: Path, extra_paths: Optional[List[Path]] = None) -> None` | Stage, commit, and push the generated dashboard copy. | run_live_dashboard | No/None |
| `main(argv: Optional[List[str]] = None) -> None` | — | — | No/None |
| `push_dashboard_to_drive(html_path: Path, timestamp_suffix: Optional[str] = None) -> str` | — | run_live_dashboard | Yes |
| `resolve_sheet_id() -> str` | Prefer explicit ID; otherwise resolve by file name. | fetch_sheet_data | Yes |
| `run_live_dashboard() -> None` | — | main | No/None |
| `run_projected_range(start: date, end: date, *, weather_source: str = 'auto', simulate_requests: bool = False, request_every_days: int = 3, request_setpoint_delta_f: float = 2.0, request_setpoint_deltas_f: Optional[List[float]] = None, request_deltas_mode: str = 'random') -> List[dict]` | Generate/overwrite archive JSON datasets for each day in [start, end]. Returns the per-day summaries printed during generation. | main | Yes |
| `run_test_mode_dashboard() -> None` | — | run_live_dashboard | No/None |
| `upload_or_version_file(service, folder_id: str, filename: str, content: bytes, mime_type: str) -> Tuple[str, str]` | — | push_dashboard_to_drive | Yes |

### 10.2 JavaScript UI functions (key operators)

This manual references these primary UI functions in `dashboard_client.js` (not exhaustive):

- `applyDashboardData(data, slugHint)` — apply new payload and redraw UI
- `loadDashboardData(slug)` — fetch an archive JSON file
- `scheduleArchiveLoadWithTapeRules(slug, pinIndexAfterLoad)` — animate tape then load
- `toggleMode(mode)` / `setModeSet(modes)` — control which datasets are visible
- `bindChartPointPicker()` / `setSelectedPoint(...)` — hover/pin point selection
- `renderUsageSlotChart()` — build the runtime aggregation bar chart
- `enterTvMode()` / `exitTvMode()` — full-screen display mode

## 11. Typical Usage Flow

1. Open the dashboard page; it initializes from embedded JSON.
2. If Auto-play starts and you want manual control, move the mouse or click to stop it.
3. Use the front-panel cards to read current status; show/hide series for clarity.
4. Show the main chart and hover to preview points; click to pin a moment in time.
5. Use history navigation (history list, transport nav, arrow keys) to load a prior day; watch for the tape spin then redraw.
6. Use << / >> to step within the day (and optionally across days via edge wrapping).
7. Double-click to enter TV mode for a big-screen view; navigate with overlays; press Escape to exit.
