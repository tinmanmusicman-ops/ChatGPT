# LeadGen HSST Python Pipeline

This folder contains a Python replacement for the n8n lead-vetting workflow.

## What It Does

For one row at a time:

1. Reads the exact row from Google Sheets.
2. Validates required lead input (`company`).
3. Uses existing `website` or discovers website via OpenAI.
4. Scrapes website with Firecrawl.
5. Evaluates fit with OpenAI and strict JSON parsing.
6. Writes structured results back to the same row.
7. Writes error status + error code to the row on deterministic failures.

## Required Sheet Columns

Input columns:

- `company`
- `website`
- `industry`
- `country`
- `notes`

Output columns:

- `status`
- `eligibility`
- `icp_classification`
- `tier`
- `confidence_score`
- `reasoning`
- `enriched_website`
- `manual_review`
- `manual_review_reason`
- `error_code`
- `processed_at_utc`
- `request_id`

## Setup

1. Create venv and install deps:

```powershell
cd C:\ChatGPT\ai-bots\n8n\LeadGen
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env`.

3. Set all required env vars from `.env` in your shell/session.

PowerShell example:

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $parts = $_.Split('=',2)
  [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}
```

## Run

Direct row number:

```powershell
python run_leadgen.py --row-number 2 --request-id test-001
```

Payload file mode:

```powershell
python run_leadgen.py --payload-file C:\ChatGPT\ai-bots\UpWork\payload_source_from_exec34.json
```

Expected stdout:

```json
{"ok":true,"rowNumber":2,"status":"COMPLETE","requestId":"test-001","updatedRanges":["Leads!G2"],"ignoredColumns":[]}
```

## Webhook Mode (n8n-style trigger)

Start webhook server:

```powershell
python run_webhook.py
```

One-click launcher (double-click or run from terminal):

```powershell
start_webhook.bat
```

Optional custom bind/path:

```powershell
python run_webhook.py --host 127.0.0.1 --port 8787 --path /webhook/lead-vetting-prod
```

Test call with the same payload shape:

```powershell
Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:8787/webhook/lead-vetting-prod" `
  -ContentType "application/json" `
  -Body '{"rowNumber":2,"requestId":"test-001"}'
```

Accepted payloads:

- `{"rowNumber":2,"requestId":"test-001"}`
- `{"body":{"rowNumber":2,"requestId":"test-001"}}`

Health check:

```powershell
Invoke-RestMethod -Method GET -Uri "http://127.0.0.1:8787/health"
```

## Deterministic Error Behavior

- Missing env var: process fails immediately (`FAIL-FAST`), no execution.
- Missing required lead data (`company`): row gets `status=ERROR` with `error_code`.
- Missing website after discovery: row gets `status=ERROR` with `error_code`.
- Invalid AI JSON: row gets `status=ERROR` with `error_code`.
- Low confidence (`confidence_score < LEADGEN_MANUAL_REVIEW_THRESHOLD`): `manual_review=Yes`.
