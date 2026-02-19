# UpWork Local Safe Capture Process

This folder contains the hotkey-driven, human-session capture pipeline for visible Upwork jobs.

## Objective

Capture only visible job cards from the active Upwork jobs page and export structured files.

## Hotkey

- `Ctrl + Win + U`

## Scope and Safety Rules

- Human session only (you are already logged into Upwork in a normal browser).
- Read-only extraction from visible page content.
- No headless login.
- No credential automation.
- No endpoint scraping.
- Fail-fast behavior on missing requirements.

## Files in This Process

- `ai-bots/UpWork/capture_visible_upwork_jobs.py`
- `ai-bots/UpWork/Start_Browser_CDP.bat`
- `ai-bots/AutoHotKey/EvaluateJobFit/EvaluateJobFit.ahk`
- `ai-bots/AutoHotKey/EvaluateJobFit.ahk`

## Runtime Flow (Ctrl+Win+U)

1. AHK hotkey handler starts (`^#u`).
2. It validates required paths:
   - Python venv executable
   - UpWork project folder
   - capture script
3. It runs `capture_visible_upwork_jobs.py` once.
4. On success:
   - shows output file paths in a message box
   - copies output paths to clipboard
5. On failure:
   - message box shows `FAIL-FAST: ...`
   - process stops

By default, capture aggregates across either mode:
- Pagination mode (`?page=...`): walks from page 1 through limit/end.
- Load-more mode (`Load More Jobs` button): clicks and accumulates batches until limit/end.

## User Prep Before Pressing Hotkey

1. Keep an Upwork jobs search tab visible and active.
2. Be logged in on that browser profile.
3. Scroll so target jobs are visible on screen.
4. Press `Ctrl + Win + U`.

## Output Location

- Folder: `C:\ChatGPT\ai-bots\UpWork\`
- Files:
  - `upwork_capture_YYYYMMDD_HHMMSS.json`
  - `upwork_capture_YYYYMMDD_HHMMSS.md`

## Deterministic Bid-Fit Evaluation

Use the local evaluator to score captured jobs for `BID / MAYBE / SKIP` before spending connects.

- Evaluator script:
  - `ai-bots/UpWork/evaluate_upwork_capture.py`
- Rubric profile:
  - `ai-bots/UpWork/upwork_fit_profile.json`

Run (latest capture file):

```powershell
C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit\.venv\Scripts\python.exe C:\ChatGPT\ai-bots\UpWork\evaluate_upwork_capture.py
```

Run (specific capture file):

```powershell
C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit\.venv\Scripts\python.exe C:\ChatGPT\ai-bots\UpWork\evaluate_upwork_capture.py --input C:\ChatGPT\ai-bots\UpWork\upwork_capture_YYYYMMDD_HHMMSS.json
```

Evaluation outputs:

- `upwork_evaluation_YYYYMMDD_HHMMSS.json`
- `upwork_evaluation_YYYYMMDD_HHMMSS.md`

Each job includes:
- `fit_score` (0-100)
- `recommendation` (`BID`, `MAYBE`, `SKIP`)
- `hard_stop` and `hard_stop_reasons`
- `positives` and `risks`

### Optional Right-Click Context Menu (Windows)

You can run evaluation by right-clicking a capture JSON file in Explorer.

Install:

```powershell
reg import "C:\ChatGPT\ai-bots\UpWork\InstallUpworkCaptureContextMenu.reg"
```

Uninstall:

```powershell
reg import "C:\ChatGPT\ai-bots\UpWork\UninstallUpworkCaptureContextMenu.reg"
```

Context menu action:
- Name: `Evaluate Upwork Capture (BID/MAYBE/SKIP)`
- Target file requirement: `upwork_capture_*.json`
- Runner: `C:\ChatGPT\ai-bots\UpWork\Run_Upwork_Evaluation.bat`
- Deep run log: `C:\ChatGPT\ai-bots\UpWork\logs\upwork_eval_run_YYYYMMDD_HHMMSS.log`
- Behavior: log auto-opens in Notepad after each context-menu run (success or failure).

## JSON Shape

```json
[
  {
    "title": "",
    "company": "",
    "rate": "",
    "type": "",
    "description": "",
    "tags": [],
    "posted": "",
    "url": ""
  }
]
```

## Markdown Shape

```md
## Upwork Capture - YYYYMMDD_HHMMSS

### JOB
Title:
Company:
Rate:
Type:
Posted:
Tags:
URL:
Description:
```

## Fail-Fast Conditions

The process stops immediately if any of these fail:

- Active foreground window title is not Upwork.
- CDP endpoint cannot be attached (`http://127.0.0.1:9222`).
- No Upwork tab found in attached browser.
- Attached tab is not Upwork jobs search.
- User appears logged out.
- No visible jobs detected.
- Required local file/path is missing.

## Logs and Debug

- Launcher log:
  - `ai-bots/AutoHotKey/EvaluateJobFit/logs/launcher_debug.log`
- Capture command output file used by AHK:
  - `ai-bots/AutoHotKey/EvaluateJobFit/logs/upwork_capture_output.txt`

## Dependency Notes

- Python runtime used by AHK:
  - `ai-bots/AutoHotKey/EvaluateJobFit/.venv/Scripts/python.exe`
- Required package:
  - `playwright`

Install (if needed):

```powershell
C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit\.venv\Scripts\python.exe -m pip install playwright
```

## Optional Scope Control

Set `UPWORK_MAX_PAGES` to limit capture depth for faster runs/tests.
- In pagination mode: max pages visited.
- In load-more mode: max load-more rounds.

Example (PowerShell):

```powershell
$env:UPWORK_MAX_PAGES='2'
C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit\.venv\Scripts\python.exe C:\ChatGPT\ai-bots\UpWork\capture_visible_upwork_jobs.py
Remove-Item Env:UPWORK_MAX_PAGES
```

## Important Operational Note

The hotkey flow does not auto-retry or auto-recover. It fails immediately and reports the exact error.

`Start_Browser_CDP.bat` launches Chrome/Edge on debug port `9222` with the default browser profile so existing Upwork login is reused.

Google Chrome versions 136 and later may block CDP on the default profile by design. If `9222` is not exposed, use a non-default `--user-data-dir` (or Chrome for Testing) and log in there.

If your daily browser is Firefox, keep using Firefox normally and run capture via Edge on `9222` (launcher now prefers Edge first).
