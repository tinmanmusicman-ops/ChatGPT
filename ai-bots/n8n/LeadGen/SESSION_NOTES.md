## Session Notes (LeadGen)

1. Added `Runtime.log` tee + `status.log` so a single run captures both verbose pipeline output and distilled function-level status.
2. Config now loads from `C:\ChatGPT\shared\Global.json` with all required `LEADGEN_*` env keys; the same file supplies OpenAI/Firecrawl credentials and service-account info.
3. Runtime failures resolved: script now runs cleanly (`--row-number 2 --request-id cleancheck-2`) with no `FAIL-FAST` entries other than the expected row-number guard when omitted.
4. `status.log` (function-level success/error entries) sits next to `run_leadgen.py`; it redacts API keys/private keys but still shows key events for comparison with the n8n canvas.
5. Added `tail_log.ps1` plus registry helpers for right-click tailing of `.log` files—all scripts live at `C:\ChatGPT`.

Next steps:
- Run the same row through webhook mode to validate the HTTP trigger path.
- Confirm Google Sheet updates match n8n expectations (columns listed in README).
- Optionally prune `Runtime.log`/`status.log` before handing to others.
