# LeadGen Work Context

## Objective
Maintain and extend the HSST-style Python lead-vetting pipeline that mirrors the n8n workflow behavior for row-level processing in Google Sheets.

## Current Runtime Entry Points
- `run_leadgen.py`
  - `--mode single`: process one row from CLI/payload file.
  - `--mode webhook`: run local webhook endpoint for n8n-style trigger payloads.
- `run_webhook.py`
  - Thin wrapper that calls `run_leadgen.py --mode webhook`.

## Core Processing Flow
1. Load `.env` values (without overriding existing environment values).
2. Build `Config` from required env vars.
3. Read one row from Google Sheets.
4. Normalize/validate lead fields.
5. Use existing website or discover website with OpenAI.
6. Scrape website with Firecrawl.
7. Evaluate lead fit with OpenAI.
8. Parse strict JSON decision payload.
9. Write success/error columns back to the same sheet row.

## Key Modules
- `leadgen/pipeline.py`: orchestration for single-row run and sheet updates.
- `leadgen/google_sheets.py`: sheet read/update by row and header map.
- `leadgen/openai_client.py`: OpenAI Responses API calls.
- `leadgen/firecrawl_client.py`: scrape calls.
- `leadgen/parser.py`: output parsing/validation.
- `leadgen/prompts.py`: prompt composition and row normalization.
- `leadgen/hsst_log.py`: JSON event logger used by pipeline.

## Logging Behavior
- Runtime-level logging now tees all stdout/stderr from `run_leadgen.py` into:
  - `C:\ChatGPT\ai-bots\n8n\LeadGen\Runtime.log`
- Pipeline JSON events continue through `HSSTLogger` and also appear in `Runtime.log` because they print to stdout.

## Expected Inputs
- CLI row mode: `--row-number`, optional `--request-id`.
- Payload file mode: JSON object with `rowNumber` and optional `requestId`.
- Webhook mode accepts either:
  - `{"rowNumber":2,"requestId":"..."}`
  - `{"body":{"rowNumber":2,"requestId":"..."}}`

## Constraints
- Fail-fast behavior is intentional for missing env vars and malformed inputs.
- Required Google and API credentials remain external (env + credential file).
- Sheet output keys must exist as headers to be updated.
