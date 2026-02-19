# Thread Context - 2026-02-15

## Scope Completed

- Upwork capture hotkey pipeline (`Ctrl+Win+U`) is implemented and working in `C:\ChatGPT\ai-bots\UpWork`.
- Capture now supports both:
  - classic pagination (`?page=...`)
  - `Load More Jobs` mode (`/nx/find-work/domestic` style).
- Default capture depth via hotkey is capped to 25 pages/rounds.

## Key Files

- Capture script:
  - `C:\ChatGPT\ai-bots\UpWork\capture_visible_upwork_jobs.py`
- Browser launcher:
  - `C:\ChatGPT\ai-bots\UpWork\Start_Browser_CDP.bat`
- Docs:
  - `C:\ChatGPT\ai-bots\UpWork\README.md`
- Active AHK launcher script:
  - `C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit\EvaluateJobFit.ahk`
- Mirror AHK script:
  - `C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit.ahk`

## Runtime Behavior (Current)

- Hotkey: `Ctrl+Win+U`
- AHK command sets:
  - `NODE_NO_WARNINGS=1`
  - `UPWORK_MAX_PAGES=25`
- Output files are written to:
  - `C:\ChatGPT\ai-bots\UpWork\upwork_capture_YYYYMMDD_HHMMSS.json`
  - `C:\ChatGPT\ai-bots\UpWork\upwork_capture_YYYYMMDD_HHMMSS.md`
- Upwork popup boxes auto-timeout to avoid blocking future hotkeys.
- A short tooltip appears when capture starts.

## Important Constraints

- Firefox cannot be attached by this CDP-based pipeline.
- Use Edge CDP session for capture.
- Chrome default profile CDP may be blocked on modern builds.
- System runs in strict fail-fast mode (no retry fallback path).

## Confirmed Results

- Latest verified capture produced 200 records after load-more traversal.
- File example:
  - `C:\ChatGPT\ai-bots\UpWork\upwork_capture_20260215_233634.json`

## Next Session Suggested Start

1. Ensure Edge is running with CDP on `9222`.
2. Open Upwork search page and keep it foreground.
3. Press `Ctrl+Win+U`.
4. Review newest `upwork_capture_*.json` in `C:\ChatGPT\ai-bots\UpWork`.

## Nice-to-Have Enhancements (Not Yet Done)

- Improve field quality cleanup:
  - company extraction
  - description quality
  - tag normalization
- Add in-run HSST tagging output file after capture.
