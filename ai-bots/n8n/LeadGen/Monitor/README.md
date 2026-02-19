# LeadGen Monitor

Runtime visual monitor for `LeadGen` that watches `monitor_feed.jsonl` and animates pipeline flow.

## Start

From this folder:

```powershell
python monitor_server.py --monitor-feed ..\monitor_feed.jsonl --host 127.0.0.1 --port 8790
```

Or one-click:

```powershell
run_monitor.bat
```

The batch launcher starts the monitor server and opens:

`http://127.0.0.1:8790/`

`run_monitor.bat` launches the server with `pythonw` so no persistent command window stays open.

To start webhook + execute one flow run (row 2) without command-line input:

```powershell
run_hook_and_flow.bat
```

It writes the webhook response to:

`Monitor\last_webhook_response.json`

## What it shows

- Static flow graph based on your Python pipeline stages
- Live node status (`idle`, `running`, `success`, `error`)
- Edge pulse animation as steps progress
- Live event panel
- Raw payload pair lines (`key=value`) from the monitor feed stream

## Notes

- The monitor is read-only; all editing remains code-first.
- `status.log` and monitor feed are independent outputs.
- It tails new appended monitor feed events from the point the monitor starts.
