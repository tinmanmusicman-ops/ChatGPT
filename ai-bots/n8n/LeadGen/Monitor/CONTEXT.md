# LeadGen Monitor Context

Last updated: 2026-02-19

## What this monitor does

- Visualizes LeadGen flow execution from `monitor_feed.jsonl`.
- Shows node state (`idle`, `running`, `success`, `error`) and live events.
- Lets you click nodes to inspect code.
- Lets you open VS Code directly at the exact code section for a node.

## Main files

- `Monitor/monitor_server.py`
  - Serves UI and event APIs.
  - Defines graph nodes, edges, node types, and node metadata.
  - Maps runtime events to graph nodes.
  - Extracts code by node from source files (AST + section markers).
  - Exposes `/open-in-vscode` to launch `code -g`.
- `Monitor/static/index.html`
  - Inline CSS + JS for graph UI.
  - Node hover tooltips.
  - Node click code modal.
  - `Open in VS Code` button.
  - Zoom controls and running-state blink behavior.

## Data flow

1. `run_leadgen.py` writes monitor events to `monitor_feed.jsonl`.
2. `monitor_server.py` tails that file and pushes SSE events.
3. Browser subscribes to `/events` and updates node states.

## Important APIs

- `GET /graph` -> graph definition + node metadata.
- `GET /history` -> buffered recent events.
- `GET /events` -> server-sent event stream.
- `GET /node-code?node_id=<id>` -> live extracted code block for node.
- `GET /open-in-vscode?node_id=<id>` -> launches `code -g file:line`.

## Node code extraction model

- Node id -> symbol path mapping via `NODE_CODE_SYMBOL_PATHS`.
- Optional section slicing for nodes that share a master function via `NODE_CODE_SECTION_MARKERS`.
- Extraction is validated at monitor startup (fail-fast if mapping breaks).

## Run / reload workflow

- Start monitor: `Monitor/run_monitor.bat` (or `python Monitor/monitor_server.py`).
- If `monitor_server.py` changes: restart monitor process.
- If `index.html` changes: hard refresh browser (`Ctrl+F5`).
- For VS Code jump feature: ensure `code --version` works and VS Code is installed.

## Current behavior notes

- Some nodes map to sections inside `LeadVettingPipeline.run_single_row`.
- Section extraction uses text markers, so line edits in `pipeline.py` may require marker updates.
- Running blink is timer-driven in JS and stops when node leaves `running`.

