# UpWork Workspace Context

Generated: 2026-02-17  
Location reviewed: `C:\ChatGPT\ai-bots\UpWork`

## Scope Reviewed

- Core scripts:
  - `ai-bots/UpWork/capture_visible_upwork_jobs.py`
  - `ai-bots/UpWork/evaluate_upwork_capture.py`
- Runtime/config:
  - `ai-bots/UpWork/README.md`
  - `ai-bots/UpWork/Run_Upwork_Evaluation.bat`
  - `ai-bots/UpWork/Start_Browser_CDP.bat`
  - `ai-bots/UpWork/InstallUpworkCaptureContextMenu.reg`
  - `ai-bots/UpWork/UninstallUpworkCaptureContextMenu.reg`
  - `ai-bots/UpWork/upwork_fit_profile.json`
- Captured/evaluated data artifacts:
  - `ai-bots/UpWork/upwork_capture_20260216_120420.json`
  - `ai-bots/UpWork/upwork_capture_20260216_120420.md`
  - `ai-bots/UpWork/upwork_evaluation_20260216_134101.json`
  - `ai-bots/UpWork/upwork_evaluation_20260216_134101.md`
  - `ai-bots/UpWork/upwork_evaluation_20260216_134101-BIDPACK.md`
  - `ai-bots/UpWork/Senior AI Automation Engineer for Gmail Lead Classification-BID.md`
- Execution logs:
  - `ai-bots/UpWork/logs/upwork_eval_run_20260216_132132.log`
  - `ai-bots/UpWork/logs/upwork_eval_run_20260216_132339.log`
  - `ai-bots/UpWork/logs/upwork_eval_run_20260216_132451.log`
  - `ai-bots/UpWork/logs/upwork_eval_run_20260216_134100.log`
- Non-source local browser profiles/cache also present:
  - `ai-bots/UpWork/cdp-profile/`
  - `ai-bots/UpWork/cdp-test-profile/`
  - `ai-bots/UpWork/__pycache__/`

## System Overview

1. Human-operated Upwork capture pipeline (hotkey/CDP + Playwright).
2. Deterministic evaluator scores captured jobs as `BID` / `MAYBE` / `SKIP`.
3. Optional Windows context-menu executes evaluation for selected capture files.

## Current Dataset Snapshot

- Capture file (`upwork_capture_20260216_120420.json`):
  - Total jobs: `200`
  - Jobs with URL: `200`
  - Jobs with description: `200`
  - Jobs with company value: `61`
  - Hourly: `152`
  - Fixed: `48`
  - Average tags/job: `7.14`
  - Duplicate title+url pairs: `0`
  - Jobs with unusually long `company` field (>150 chars): `56` (capture noise where description/company can merge)
- Evaluation file (`upwork_evaluation_20260216_134101.json`):
  - Total jobs: `200`
  - `BID`: `22`
  - `MAYBE`: `41`
  - `SKIP`: `137`
  - Hard stops: `47`
  - Thresholds: `BID >= 75`, `MAYBE >= 55`

## Target Job Found

- Title: `Build n8n AI Agent Workflow for Automated Lead Vetting (Google Sheets + Firecrawl + OpenAI)`
- URL: `https://www.upwork.com/jobs/Build-n8n-Agent-Workflow-for-Automated-Lead-Vetting-Google-Sheets-Firecrawl-OpenAI_~022021262165364680102/?referrer_url_path=find_work_home`
- Posted: `6 days ago`
- Rate: `Hourly: $40-$60`
- Evaluator result:
  - Recommendation: `BID`
  - Fit score: `90`
  - Confidence: `high`

## Extracted Customer Requirements (n8n Job)

- Trigger: Webhook with `rowNumber`.
- Process model: one lead row at a time from Google Sheets.
- Enrichment:
  - Find website if missing.
  - Scrape website via Firecrawl.
- Decisioning:
  - Use AI for B2B fit assessment.
  - Strict JSON output required.
- Output fields required:
  - `eligibility` (`Yes`/`No`)
  - `icp_classification`
  - `tier` (`Tier 1` / `Tier 2` / `N/A`)
  - `confidence_score`
  - `reasoning`
- Reliability requirements:
  - Handle invalid JSON
  - Handle missing websites
  - Handle ambiguous companies
  - Support manual review flags
  - Stabilize code nodes / payload parsing / sheet mapping / API reliability
- Deliverables:
  - Importable n8n workflow JSON
  - Clean commented code nodes
  - Verified E2E sample run
  - Short handoff notes

## Notes for Next Actions

- Framework created: `ai-bots/UpWork/n8n_lead_vetting_framework.json`
- This context file is baseline memory for follow-up implementation and proposal drafting.
