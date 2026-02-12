# Thread Context - 2026-02-11

Workspace root: `C:\ChatGPT`
Project reviewed: `C:\ChatGPT\AI-Fit-Site`
Review scope: `Job.html`, `manage.html`, `tower.config.json`, existing context artifact alignment

## Review Findings (Severity Ordered)

1. HIGH - Manage credential is hardcoded and exposed in logs.
- `AI-Fit-Site/Job.html:1536` hardcodes `MANAGE_PASSWORD` as plaintext.
- `AI-Fit-Site/Job.html:1758` and `AI-Fit-Site/Job.html:1768` log expected password and character codes to debug output.
- `AI-Fit-Site/Job.html:1560` posts those debug lines to `/cores/log`.
- Risk: anyone with source/log access can recover the gate credential.

2. HIGH - Manage access control is client-side only and bypassable.
- `AI-Fit-Site/Job.html:1149` exposes direct link to `/AI-Fit-Site/manage?id=CORE-US-2026-000001`.
- `AI-Fit-Site/Job.html:2168` enforces password only in the button click handler.
- `AI-Fit-Site/manage.html:2760` boots and loads document data without auth validation.
- Risk: direct navigation to manage URL bypasses the Job-page prompt.

3. MEDIUM - Critical errors are swallowed, reducing diagnosability and masking broken states.
- Startup flow silently ignores failures at `AI-Fit-Site/manage.html:2768`.
- Similar silent catches appear around reload/open/save and interaction flows (for example `AI-Fit-Site/manage.html:2511`, `AI-Fit-Site/manage.html:2524`, `AI-Fit-Site/manage.html:2547`, `AI-Fit-Site/manage.html:2554`).
- Risk: blank/partial UI states occur with little operator signal.

## Current Runtime Wiring

- Tower base URL source: `AI-Fit-Site/tower.config.json`.
- Job page AI calls route through tower (`/tower/ask-ai`, `/tower/contact`) after config load.
- Manage page content load path is `/CORES/<coreId>.md` (via `loadDoc`).

## Notes For Next Session

1. Move manage authorization to server-side route protection (not just client JS prompt).
2. Remove plaintext password handling and stop logging secret material.
3. Replace silent catches in critical load/save paths with user-visible status and deterministic fail-fast messaging.
4. Re-test direct URL access to `/AI-Fit-Site/manage` after auth hardening.
