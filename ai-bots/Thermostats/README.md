# Thermostats Project

Hosts the thermostat automation model, including configuration helpers and reference files. scripts/ contains the seam_thermostat_temp.py automation, while bot-assets/ houses sample configs and flows, and source/ can store documentation.

## Embedded Help Chat (Operator Manual Only)

The dashboard includes an embedded help chat panel that answers questions using only the operator manual PDF.

- Backend API: `ai-bots/Thermostats/scripts/dashboard_help_api.py`
- Operator manual (primary): `ai-bots/Thermostats/Web/dashboard_operator_manual.md`
- Operator manual PDF (derived): `ai-bots/Thermostats/Web/dashboard_operator_manual.pdf`
- Dashboard HTML: `ai-bots/Thermostats/Web/dashboard_public.html`

If you already run the Flask Control Tower (`EI_ControlTower/tower.py`), you can use its route:

- Flask endpoint: `POST /tower/api/help-chat`

### Run the help API locally

1. Install dependencies:
   - `python -m pip install -r ai-bots/Thermostats/scripts/help_chat_requirements.txt`
2. Set your OpenAI key:
   - `setx OPENAI_API_KEY "..."` (then restart your terminal)
3. Start the API:
   - `python ai-bots/Thermostats/scripts/dashboard_help_api.py`

The dashboard chat calls `http://localhost:8000/api/help-chat` by default.

If you’re using the Flask Control Tower route, the default Flask port is `5000`, so the chat endpoint is:

- `http://localhost:5000/tower/api/help-chat`

You can also set:

- `HELP_CHAT_ENDPOINT=http://localhost:5000/tower/api/help-chat`

### Configure endpoint (optional)

- Dashboard generator env var: `HELP_CHAT_ENDPOINT` (used as the chat panel `data-endpoint`)
- API env vars:
  - `DASHBOARD_HELP_MANUAL` (override manual path)
  - `DASHBOARD_HELP_MODEL` (default: `gpt-4o-mini`)
