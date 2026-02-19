# n8n Lead Vetting Setup Guide (Beginner Safe)

Last updated: 2026-02-17  
Workflow file: `ai-bots/UpWork/n8n_lead_vetting_workflow.json`

## 1. Goal

Run one webhook call like:

```json
{"rowNumber":2,"requestId":"test-001"}
```

Then n8n should:
1. Read row 2 from your Google Sheet tab `Leads`
2. Evaluate lead fit using OpenAI + Firecrawl
3. Write results back into the same row

## 2. Your Current Config (already baked into workflow)

1. n8n type: `cloud`
2. Webhook path: `lead-vetting-prod`
3. Webhook lock: `OFF` (no auth required right now)
4. Google Sheet ID: `1y1bvxJIiJB-XhdJAJkFH1ngyOrWB29RwJeiFALiQCWw`
5. Google Sheet tab: `Leads`
6. OpenAI model: `gpt-4.1-mini`
7. Firecrawl URL: `https://api.firecrawl.dev/v1/scrape`
8. Manual review threshold: `confidence < 70`

## 3. Things You Need Before Starting

1. OpenAI API key (starts with `sk-...`)
2. Firecrawl API key
3. Google account that can edit your target sheet
4. Imported workflow in n8n (you already did this)

## 4. Required Sheet Columns (Row 1 headers)

Create these exact column names in row 1 of tab `Leads`:

1. `rowNumber`
2. `company`
3. `website`
4. `industry`
5. `country`
6. `notes`
7. `status`
8. `eligibility`
9. `icp_classification`
10. `tier`
11. `confidence_score`
12. `reasoning`
13. `enriched_website`
14. `manual_review`
15. `manual_review_reason`
16. `error_code`
17. `processed_at_utc`
18. `request_id`

Important:
1. In row 2, set `rowNumber` cell to `2`.
2. In row 2, set `company` to a real company name.

## 5. Connect Google Account in n8n

Do this first.

1. Open workflow.
2. Click node `Google Sheets - Read Row`.
3. On right panel, find `Credential to connect with` (name can vary slightly).
4. Click `Create new`.
5. Select `Google Sheets OAuth2 API`.
6. Click `Connect` or `Sign in with Google`.
7. Choose your Google account.
8. Click `Allow` on permission screen.
9. Save credential.
10. Click node `Google Sheets - Update Row`.
11. Select that same Google credential.

## 6. Add OpenAI Key in Both OpenAI Nodes

1. Click node `HTTP - Discover Website (OpenAI)`.
2. Go to `Headers`.
3. Find `Authorization`.
4. Replace value with:

```text
Bearer sk-your-real-openai-key
```

5. Click node `HTTP - Evaluate Lead (OpenAI)`.
6. Go to `Headers`.
7. Find `Authorization`.
8. Replace value with the same OpenAI key format:

```text
Bearer sk-your-real-openai-key
```

## 7. Add Firecrawl Key

1. Click node `HTTP - Firecrawl Scrape`.
2. Go to `Headers`.
3. Find `Authorization`.
4. Replace value with:

```text
Bearer your-real-firecrawl-key
```

## 8. First End-to-End Test

### 8.1 Get test webhook URL

1. Click node `Webhook Trigger`.
2. Copy the `Test URL`.

### 8.2 Put workflow in listening mode

1. Click `Execute workflow` or `Listen for test event`.

### 8.3 Send test payload

Run in PowerShell (replace URL):

```powershell
Invoke-RestMethod -Method POST -Uri "PASTE_TEST_URL_HERE" -ContentType "application/json" -Body '{"rowNumber":2,"requestId":"test-001"}'
```

### 8.4 Expected result

1. n8n execution finishes without red node.
2. Response shows `ok: true`.
3. Row 2 gets filled in output columns.

## 9. What Each Node Does (Simple)

1. `Webhook Trigger`: receives `rowNumber`.
2. `Code - Parse and Validate Payload`: checks the payload is valid.
3. `Google Sheets - Read Row`: pulls the row from `Leads`.
4. `Code - Normalize Lead Row`: standardizes input fields.
5. `IF - Website Present`: checks if website exists already.
6. `HTTP - Discover Website (OpenAI)`: tries to find website if missing.
7. `Code - Use Existing Website` or `Code - Use Discovered Website`: chooses final website.
8. `HTTP - Firecrawl Scrape`: scrapes website text.
9. `Code - Build AI Prompt Context`: creates evaluation prompt with your ICP notes.
10. `HTTP - Evaluate Lead (OpenAI)`: gets structured decision JSON.
11. `Code - Parse and Validate AI JSON`: validates output and applies threshold `< 70 => manual review`.
12. `Code - Compose Sheet Update`: maps values to your column names.
13. `Google Sheets - Update Row`: writes back to row.
14. `Respond Success`: returns final success payload.

## 10. Fast Troubleshooting

If test fails, check red node name and match below.

1. `Code - Parse and Validate Payload`
- Cause: `rowNumber` missing or not numeric.
- Fix: send body exactly like `{"rowNumber":2,"requestId":"test-001"}`.

2. `Google Sheets - Read Row`
- Cause: Google credential not connected or lookup column mismatch.
- Fix: reconnect Google credential; confirm column `rowNumber` exists and row has value `2`.

3. `HTTP - Discover Website (OpenAI)` or `HTTP - Evaluate Lead (OpenAI)`
- Cause: bad OpenAI key.
- Fix: ensure header is `Authorization: Bearer sk-...` real key, no extra spaces.

4. `HTTP - Firecrawl Scrape`
- Cause: bad Firecrawl key or blocked URL.
- Fix: ensure header is `Authorization: Bearer ...` and website is valid.

5. `Code - Parse and Validate AI JSON`
- Cause: model returned non-JSON format.
- Fix: rerun; if repeated, tighten prompt or reduce prompt size.

6. `Google Sheets - Update Row`
- Cause: output columns missing or not editable.
- Fix: create all required output headers exactly and ensure sheet write access.

## 11. Go-Live Checklist

1. Run at least 5 successful test rows.
2. Confirm manual review behavior for low-confidence cases.
3. Turn workflow `Active`.
4. Switch from test webhook URL to production webhook URL.
5. Later, add security lock (header token) once stable.

## 12. Copy/Paste Test Payloads

Minimal:

```json
{"rowNumber":2}
```

With request id:

```json
{"rowNumber":2,"requestId":"test-001"}
```

## 13. If You Need Help Debugging

Send exactly:
1. Red node name
2. Error text shown in that node
3. Screenshot of node output panel

That is enough to diagnose quickly.
