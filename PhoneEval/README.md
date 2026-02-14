# PhoneEval Step-by-Step

PhoneEval is the phone-facing web app that sends text to your Flask POST /analyze endpoint and displays the returned summary.

## 1) Architecture

Flow:
1. On phone, user selects text and uses Share (or pastes text manually).
2. PhoneEval frontend sends text to Flask POST /analyze.
3. Flask reads OpenAI key from local global.json, calls OpenAI server-side, and returns strict JSON.
4. PhoneEval shows result and supports copy/share of output.

Important:
- API key is never exposed in browser code.
- GitHub Pages hosts only static frontend files.
- Flask does all AI processing.

## 2) Relevant Paths

- Phone frontend folder: C:\ChatGPT\PhoneEval
- Flask app: C:\ChatGPT\EI_ControlTower\tower.py
- API key source used by /analyze: C:\ChatGPT\ai-bots\shared\global.json

PhoneEval files:
- PhoneEval/index.html
- PhoneEval/manifest.webmanifest
- PhoneEval/sw.js
- PhoneEval/icon.svg

## 3) Flask Endpoints (Current)

From tower.py:
- GET /phone-eval -> serves PhoneEval/index.html
- GET /phone-eval/<path:filename> -> serves static PhoneEval assets
- POST /analyze -> AI analysis endpoint
- OPTIONS /analyze -> CORS preflight

Analyze endpoint behavior:
- Accepts JSON body with text, and form fallback (text field).
- If empty text: {"error":"No text received"} with HTTP 400.
- If text length < 10: {"error":"Text too short to analyze"} with HTTP 400.
- On OpenAI/network failure: JSON error with HTTP 5xx/4xx.
- On success returns strict JSON:
  - summary
  - key_points
  - action_items

OpenAI runtime details:
- Model: OPENAI_MODEL env var or default gpt-4o-mini
- Temperature: 0.2
- Max tokens: 450
- Word limit enforcement in response: 150 words total

CORS for /analyze:
- Open CORS helper is used.
- Access-Control-Allow-Origin is request origin, or * if origin missing.
- Allowed methods: POST, OPTIONS
- Allowed headers: Content-Type

## 4) Start Flask Locally

From C:\ChatGPT\EI_ControlTower:

```powershell
python tower.py
```

Default local server from code:
- Host: 0.0.0.0
- Port: 5000

Local URLs:
- http://127.0.0.1:5000/phone-eval
- http://127.0.0.1:5000/analyze

## 5) Verify /analyze with curl

```powershell
curl.exe -X POST "http://127.0.0.1:5000/analyze" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Please review this update. We moved deployment to Friday, QA signoff is pending, and release notes must be sent by Thursday.\"}"
```

Expected response shape:

```json
{
  "summary": "...",
  "key_points": "...",
  "action_items": "..."
}
```

## 6) Configure PhoneEval Frontend

1. Open PhoneEval/index.html from Flask route (/phone-eval) or GitHub Pages URL.
2. Endpoint resolution is deterministic and fail-fast:
   - Query override: `?endpoint=https://.../analyze`
   - Pinned endpoint from `Save Endpoint`
   - Same-origin `/analyze` when not on `*.github.io`
   - `./tower.config.json` when on GitHub Pages
3. If none of those are available, Analyze fails until endpoint is corrected.
4. Endpoint must be a valid absolute URL with path exactly `/analyze`.
4. In Flask Analyze Endpoint, set your live endpoint:
   - Local test: http://127.0.0.1:5000/analyze
   - Tunnel/public: https://<your-tunnel-domain>/analyze
5. Tap Save Endpoint.
6. Paste text and tap Analyze.

## 7) Publish to GitHub Pages

You have two common options:

Option A (recommended for quick setup):
1. Create branch gh-pages.
2. Copy contents of PhoneEval folder to the root of gh-pages.
3. In repo settings, set GitHub Pages source to gh-pages branch root.

Option B:
1. Move/copy PhoneEval contents to a docs folder in main branch.
2. In repo settings, set GitHub Pages source to main branch /docs.

After publish:
- GitHub Pages URL hosts frontend only.
- Frontend must point to your Flask public /analyze URL.
- For dynamic tunnel rollover, keep tower config updated by watchdog (see next section).

## 7.1) Dynamic Tunnel Updates (same process as other tools)

`EI_ControlTower/quick_tunnel_watchdog.py` updates `towerBaseUrl` in config files as tunnel URLs rotate.

Default config targets now include:
- C:\ChatGPT\tower.config.json
- C:\ChatGPT\AI-Fit-Site\tower.config.json
- C:\ChatGPT\CORES\tower.config.json
- C:\ChatGPT\PhoneEval\tower.config.json

PhoneEval reads `./tower.config.json` in the published PhoneEval site and auto-builds `/analyze` from `towerBaseUrl`.

## 7.2) GitHub Pages Auto-sync

When you run `quick_tunnel_watchdog` with `--pages-branch gh-pages` (or another Pages branch name) it now calls `PhoneEval/sync_phoneeval_pages.py` to copy the latest PhoneEval directory into that branch, commit, and push.

Minimum arguments for automatic sync:

```powershell
python EI_ControlTower/quick_tunnel_watchdog.py \
  --pages-branch gh-pages \
  --pages-source-dir PhoneEval \
  --pages-target-path . \
  --pages-commit-message "Sync PhoneEval site ({url})"
```

The helper script uses `git worktree` and respects whatever `towerBaseUrl` you just wrote, so the branch you publish from GitHub Pages always receives the fresh tunnel URL (`tower.config.json` travels with the rest of the files).

If you prefer to sync manually (for example when testing), run:

```powershell
python PhoneEval/sync_phoneeval_pages.py --branch gh-pages --base-url https://respect-clinics-lines-argue.trycloudflare.com
```

Ensure `git` can write the branch (the script will create it if missing) and that the helper can remove the temporary worktree after each run.

## 8) Phone Install and Use

Android (best support):
1. Open the GitHub Pages URL in Chrome.
2. Install app (Add to Home Screen).
3. Select text in any app/browser and tap Share.
4. Choose PhoneEval.
5. Tap Analyze.

iPhone:
- Use page as paste/analyze app in Safari.
- Share-to-web-app behavior is limited on iOS; manual paste is the reliable path.

## 9) Request and Response Contract

Request:

```json
{
  "text": "raw content to analyze"
}
```

Success response:

```json
{
  "summary": "3-5 sentence concise overview",
  "key_points": "short key points line",
  "action_items": "actions or None"
}
```

Error response examples:

```json
{"error":"No text received"}
```

```json
{"error":"Text too short to analyze"}
```

```json
{"error":"AI request failed"}
```

## 10) Troubleshooting

- Error No text received:
  - Confirm payload contains text.
  - Confirm client sends JSON with Content-Type: application/json.

- Error Non-JSON response:
  - Endpoint is wrong or tunnel target is not Flask `/analyze`.
  - Confirm endpoint path is exactly `/analyze`.
  - Confirm tunnel/domain currently resolves and points to the active Flask server.

- Error Text too short to analyze:
  - Send at least 10 characters.

- Error related to global config:
  - Ensure file exists: C:\ChatGPT\ai-bots\shared\global.json
  - Ensure it contains openai_api_key or OPENAI_API_KEY.

- CORS errors in browser:
  - Confirm request is sent to /analyze.
  - Confirm server is running updated tower.py.
  - Confirm tunnel/public URL points to current local server.

- Phone app does not receive shared text:
  - Confirm PWA is installed.
  - Confirm manifest.webmanifest and sw.js are served from same origin.
  - On iOS, use manual paste flow.

## 11) Security Notes

- Do not put API keys in any frontend file.
- Keep global.json on server only.
- For production, add auth/token and rate limiting on /analyze.
