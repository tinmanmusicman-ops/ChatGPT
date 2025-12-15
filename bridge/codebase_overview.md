# ChatGPT Automation Codebase Overview

## What this repo is
This repository bundles a set of small automation “bots” (email processors, fax tools, thermostat dashboards, security inbox scanners, scam analyzers, etc.) plus a lightweight Flask front-end called the Control Tower. The bots live in the `ai-bots` workspace; the Control Tower provides a simple UI and a handful of stub endpoints that document how to trigger those automations.

## Repository map
- **EI_ControlTower/** – Flask entry point (`tower.py`), static UI assets under `ui/`, and stub modules that document intended pipelines. Schedules a nightly thermostat dashboard snapshot.
- **ai-bots/** – Individual automation workspaces.
  - **Jobs/** – Email-to-Google-Sheets workflow; drivers in `scripts/` and credentials/configs in `bot-assets/`.
  - **Fax/** – Fax utilities such as `send_irsfax.py`, with supporting configs and assets.
  - **Thermostats/** – Thermostat automation and dashboard scripts (e.g., `scripts/Dashboard.py`).
  - **Security/** – Gmail pollers that merge per-project configs with shared defaults (see `shared/Global.json`).
  - **Scams/** – Email analysis helpers plus stored transcripts/configs.
  - **Resume/** – Output location for generated resumes/pdfs consumed by the Control Tower.
  - **Tools/** and **Information/** – Supporting scripts, helpers, and docs for niche tasks.
  - **config-editor/** – Config management scripts, reference PDFs, and sample assets.
- **bridge/** – Collaboration handoffs (this overview and `bridge/README.md`). These files are tracked on `develop` under `bridge/`.
- **Images/** – Shared image assets served by the Control Tower.
- **BuildRequirements/**, `index.html`, `offscreen_doc.html` – Additional assets and reference material.

## Control Tower (EI_ControlTower)
- **App surface**: `tower.py` exposes `/tower` for the UI, `/health` for probes, static asset routes, and many stub endpoints (job import, scam check, thermostat controls, fax actions, security notifications, config operations). Each stub wires to a placeholder function in `modules/` but can be expanded to run the real bot scripts.
- **Log handling**: `/tower/read-log` and `/tower/clear-log` read or reset the shared log at `modules/job_pipeline.LOG_FILE_PATH`, keeping UI access simple.
- **Shared paths**: Routes serve files from `Images/` and PDF outputs from `ai-bots/Resume/` so bot outputs surface through the UI.
- **Nightly job**: `_seconds_until_next_snapshot()` and `schedule_dashboard_snapshot()` in `tower.py` run `ai-bots/Thermostats/scripts/Dashboard.py` just after midnight, appending stdout/stderr to the shared log.
- **Local run**: `python EI_ControlTower/tower.py` launches the Flask app on port 5000 with debug enabled.

## Working inside ai-bots
- **Scripts are the entry points**: Each bot keeps runnable drivers under `scripts/`. Look here first when tracing a workflow.
- **Configs live in bot-assets**: Credentials and runtime settings sit in each bot’s `bot-assets/` (with some shared JSON defaults in Security’s `shared/` folder). Keep secrets out of version control.
- **Docs in source/**: Many bots carry quickstart guides or references under `source/`—useful when wiring stubs to real actions.

## Suggested next steps for newcomers
1. **Run the Control Tower** to explore the UI and stub endpoints, then extend a route to call a bot script end-to-end.
2. **Pick one bot** (e.g., `ai-bots/Jobs/scripts` or `ai-bots/Security/scripts`) and read its README or source docs to understand inputs/outputs.
3. **Trace configuration flow** by comparing a bot’s `bot-assets/*.json` with any shared defaults; adopt the same pattern for new automations.
4. **Review `ai-bots/migration_log.md`** for recent structural changes before refactoring configs or scripts.
