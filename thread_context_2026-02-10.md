# Thread Context - 2026-02-10

Workspace root: `C:\ChatGPT`
Primary project: `C:\ChatGPT\AI-Fit-Site`

## What was completed

- Fixed resume template heading validation so dynamic placeholder headings in the empty template do not fail import.
- Tightened resume import prompt rules in Flask to enforce template-first deterministic output.
- Added deterministic new-template creation flow with auto-incremented CORE IDs.
- Updated Manage UI import flow to create and load a new empty template first, then import into it.

## Key code changes

### `EI_ControlTower/tower.py`

- Updated `RESUME_IMPORT_PROMPT` to emphasize exact template structure and fail-fast behavior.
- Added heading helpers:
  - `_normalize_heading_line(...)`
  - `_is_dynamic_template_heading(...)`
- Updated `_validate_resume_import_output(...)`:
  - No longer strict-equals all headings.
  - Enforces ordered required headings while allowing dynamic template placeholders such as:
    - `## COMPANY: XXX`
    - `### PROJECT: XXX`
  - Improved mismatch message to include the missing required heading and a heading preview.
- Added new constants and helpers for deterministic file creation:
  - `CORES_EMPTY_TEMPLATE_PATH`
  - `CORE_ID_FILE_PATTERN`
  - `_next_core_id_for_year(...)`
  - `_with_core_id_in_template(...)`
- Added endpoint:
  - `POST /cores/new-template`
  - Behavior:
    - Reads `CORES_EMPTY_TEMPLATE.md`
    - Allocates next `CORE-US-YYYY-######`
    - Injects ID into template
    - Creates new file in `C:\ChatGPT\CORES` using exclusive create mode
    - Returns `coreId`, `fileName`, and `markdown`

### `AI-Fit-Site/manage.html`

- Updated `importResumeIntoTemplate(...)` flow:
  1. Calls `POST /cores/new-template`
  2. Loads that new empty file into editor (`loadDoc(newCoreId)`)
  3. Builds template markdown from loaded empty file
  4. Sends resume + template to `/import_resume_template`
  5. Loads parsed markdown into editor for review/edit
  6. User then clicks `Save All` to persist
- Status message now reflects review/edit-first behavior before saving.

## Current behavior summary

- Import now starts from a new empty template copy.
- CORE ID increments automatically by year sequence.
- Imported content is loaded into the editor and is not considered final until `Save All`.

## Operational notes

- Flask restart is required after backend changes in `tower.py`.
- If import still fails, check `C:\ChatGPT\CORES\cores.log`.
- New heading mismatch errors now include actionable detail.

## Suggested first checks in next session

1. Restart Flask tower.
2. Open Manage page.
3. Click `Import PDF/DOCX`.
4. Confirm new file creation (for example `CORE-US-2026-00000X.md`).
5. Confirm imported content appears in editor.
6. Edit if needed and click `Save All`.

