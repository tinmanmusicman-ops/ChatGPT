# Thermostat Dashboard Operator Manual

This guide explains every visible feature of the dashboard from a user perspective. Follow the simple steps below to read the data, change what you see, and move between days.

## Creators:
[tags: author]
Hope, Sparky, Stinky and Tim
## Open the Dashboard and Get Oriented
[tags: overview, dashboard, cards, set point, temperature, outside, fan, condenser, timestamp]
1. Open the dashboard page in your browser; it loads automatically with the latest available data.
2. Notice the set of cards near the top—each card shows a key value such as the thermostat set point, building temperature, outside air, fan status, and condenser minutes.
3. Read the timestamp card to confirm how fresh the readings are before making judgments.

[tags: card, current, value, top, metric, set point, building temperature, outside, fan, compare]
1. Look at the card grid to see the most recent value for each metric.
2. Pay attention to highlighted labels (Set Point, Building Temperature, Outside, Fan) to understand the system’s immediate state.
3. If you need to compare a value, keep multiple cards in view; they update together whenever another point is selected.

## Explore the Timeline Chart
[tags: chart, history, timeline, hover, pin, temperature]

1. Find the large history chart—it plots every recorded time point for the selected day.
2. Hover your mouse over the line to highlight a point; the cards refresh to show the readings for that moment, so you can inspect precise temperatures.
3. Click one of those points to pin it and lock the cards to that time until you clear the pin or click elsewhere.

## Toggle Chart Layers
[tags: chart, tv, set point, building temp, outside temp, ac status, fan mode, combined]

1. Click the buttons beneath the TV frame (Set Point, Building Temp, Outside Temp, AC Status, Fan Mode, Combined) to add or remove those lines from the chart.
2. Use the Combined view when you want all controls active, or switch to a single series when you need a cleaner readout.
3. The chart redraws instantly; use whichever combination makes the story of that day easiest to understand.

## Step Through the Timeline
[tags: chart, step, buttons, data point, day]

1. Use the << and >> buttons near the chart to step backward or forward one data point at a time.
2. Hold down the step buttons if you want to move through several points quickly.
3. The selected time wraps around—stepping past the edge loads the next or previous day automatically, so you can continue the story without manually switching files.

## Choose a Day from the History List
[tags: chart, history, archive, month, day, cards]
1. Click the “History” toggle above the chart to open the archive picker.
2. Choose the month you care about from the left column, then click the day you want; the dashboard closes the list and loads that day.
3. As soon as a new day loads, the cards and chart refresh to show its data. If an archive is missing, it disappears from the list, keeping only available days.

## Navigate with the Tape Controls
[tags: tape, cassette, step mode, day, week, month, date, 600A]

1. Use the << and >> cassette buttons near the tape graphic to jump backward or forward by one day, week, or month depending on the selected step mode (Day, Month, Hour).
2. Watch the tape reels animate whenever a new day loads; the movement signals that the dashboard is fetching a different archive file.
3. You can also click the month/day readouts below the tape to jump directly to specific dates.

## Scan Runtime with the Usage Chart
[tags: usage, chart, bar, condenser, runtime, weekly, monthly, yearly, range]
1. Look at the small bar chart (Usage) to compare condenser runtime over weekly, monthly, or yearly ranges.
2. Click the range buttons (7d, Month, Year) to change how much history the bars cover.
3. Click any bar to load that day in the main view; the cards and history chart update to match.

## Enter and Exit TV Mode
[tags: tv, display, chart, bigger, larger, double-click, history list, usage chart, big screen, escape]

1. Double-click the main chart area to enter TV mode, which puts the dashboard inside the large television frame for presentations.
2. In TV mode, the history list and usage chart hide so the focus stays on the big screen display.
3. Double-click again or press Escape to exit TV mode and return to the desktop layout.

## Get Help From the Embedded Assistant
1. Click the “Help Chat” button to open the help panel on the left.
2. Type a question in plain English (for example, “What does the history list do?”) and press Send.
3. The chat answers using only the operator manual text, so it always describes the dashboard features exactly as they appear.

## Keep Track of Saved Settings
[tags: chart, pinned point, datasets, step mode, visit, reload]
1. The dashboard remembers your pinned point, selected datasets, and step mode for the next visit.
2. If you ever want to start fresh, reload the page and the dashboard resets to the default unpinned view.

Follow these steps whenever you need to interpret the dashboard, compare days, or present the data to others. Everything on the page reacts instantly to your clicks, so feel free to explore each control until you are comfortable with the layout.


## Tape Navigation System (Technical Summary)

[tags: tech, tape, cassette, navigation, time index, rewind, fast forward, emulation]

### Purpose
The tape navigation system provides a deterministic, linear mechanism for moving through
time-based data. At the code level, it is designed to emulate the behavior of a physical
cassette tape in order to make historical navigation predictable, inspectable, and reversible.

This system is intentionally not random-access search.

---

### Core Concept
At runtime, the tape is represented as an **ordered time index**.
Each position on the tape corresponds to a concrete timestamp or aggregated time slice
(hour, day, week, or month).

All movement operates by advancing or retreating along this ordered index.

There is always:
- a current tape position
- a previous position
- a next position

No implicit jumps are allowed.

---

### Rewind and Fast-Forward (Conceptual)
Rewind and fast-forward are implemented as **index traversal operations**:

- Rewind moves backward along the index
- Fast-forward moves forward along the index
- Step size is controlled by the active step mode
- Boundary checks prevent underflow or overflow

At the code level, this is simple arithmetic over an ordered list, not date math
or calendar inference.

This mirrors physical tape behavior: movement is sequential and observable.

---

### Step Modes
Step modes control **granularity**, not data:

- Hourly
- Daily
- Weekly
- Monthly

Changing step mode alters how far the index advances per action,
without modifying the underlying data set.

This allows both fine inspection and coarse historical scanning
using the same traversal logic.

---

### Why This Design Was Chosen
According to Tim, the tape navigation system was not chosen for a technical necessity.
There were simpler and more conventional ways to implement time navigation.

Instead, the tape metaphor was chosen deliberately for a few specific reasons.

First, it introduces a sense of **nostalgia**. The visual and behavioral reference to
physical media is intentional—it serves as a reminder of how far technology has come,
while still relying on interaction models that feel familiar and intuitive.

Second, the tape makes a **statement about progression**. It connects past and future by
pairing an old interaction metaphor with modern, real-time data systems. The intent was
not to recreate the past, but to use it as a frame for understanding what comes next.

Third, the tape provided a practical **bench test for the HSST model**. It was complex
enough to require real coordination and iteration, yet contained enough to implement
quickly. This allowed for repeated requests, fast refinement, and direct observation of
what Stinky could accomplish when guided by clear, structured prompts.

Aside from minor tweaks, the tape system—from concept to working implementation—was
completed in approximately two hours. This made it a low-risk, real-world proving ground
for validating the HSST workflow under actual development conditions.

In short, the tape exists as much as a **demonstration of collaboration and capability**
as it does as a navigation tool.

---

### Relationship to Search
The tape is a **temporal navigation mechanism**, not a content search system.

It is optimized for:
- reviewing history
- scanning patterns over time
- understanding progression and change

Search answers “what,” while the tape answers “when” and “how did we get here.”

---

### Key Invariants
- The tape index is always ordered
- Movement is always deterministic
- No hidden jumps or implicit filtering
- UI state reflects index state exactly
- Every position maps to a real data point



## Card Grid System (Technical Summary)
[tags: tech, cards, metrics, state, snapshot]

### Purpose
The card grid provides a real-time snapshot of key thermostat metrics. At the code level,
cards are a synchronized view layer bound to the currently selected time index.

### Core Behavior
- Cards update whenever the active time index changes
- Values are derived from parsed archive JSON, not recalculated
- Highlighting reflects state transitions (e.g., fan mode)

---

## Timeline Chart System (Technical Summary)
[tags: tech, chart, timeline, history, hover, pin]

### Purpose
The timeline chart visualizes all recorded data points for a selected day as an ordered series.

### Core Behavior
- Hover events preview data without mutating state
- Click (pin) locks the global time index
- All downstream UI components read from the pinned index

---

## History Archive Loader (Technical Summary)
[tags: tech, history, archive, json, loader]

### Purpose
The history loader resolves day-based archives into structured JSON at runtime.

### Core Behavior
- Archive selection changes the active dataset
- Missing archives are filtered deterministically
- All views refresh from the new archive source

---

## Usage Chart System (Technical Summary)
[tags: tech, usage, runtime, bar chart, aggregation]

### Purpose
The usage chart aggregates condenser runtime across configurable time windows.

### Core Behavior
- Uses precomputed totals per day
- Clicking a bar rebinds the main timeline view
- Range selection changes aggregation window, not source data

---

## TV Mode Presentation Layer (Technical Summary)
[tags: tech, tv mode, presentation, layout]

### Purpose
TV mode is a presentation-focused layout state, not a data mode.

### Core Behavior
- Toggles CSS/layout only
- Suppresses secondary UI panels
- Does not affect data loading or indexing

---

## Embedded Help Chat System (Technical Summary)
[tags: tech, help chat, search, indexing, markdown]

### Purpose
The embedded help chat provides deterministic documentation lookup using the operator manual.

### Core Behavior
- Loads manual at runtime (live file read)
- Parses sections by headers and tag blocks
- Matches queries via tag-based keyword logic

---

## Help Search Spell Correction (Technical Summary)
[tags: tech, spellcheck, tags, search correction]

### Purpose
Spell correction improves query tolerance while remaining deterministic.

### Core Behavior
- Builds vocabulary from known tags
- Corrects query terms before tokenization
- Never introduces terms not present in documentation

---

## Tag Suppression Rendering Control (Technical Summary)
[tags: tech, tags, rendering, ui control]

### Purpose
Tag suppression separates diagnostic metadata from user-facing content.

### Core Behavior
- Tags remain indexed and searchable
- Suppression occurs only at render time
- Controlled by explicit UI toggle state
