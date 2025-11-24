# VS Code Foundation Kit

1) Put these files into your project root (next to `scam_analyzer.py`).
2) Copy `.env.example` to `.env` and set your `OPENAI_API_KEY`.
3) In VS Code:
   - Run task **Create venv**.
   - Run task **Install requirements**.
   - Press F5 (or choose **Run Scam Analyzer**) to debug with breakpoints.
4) Use `Run (no debug)` task for quick manual runs inside the venv.

Tips:
- Set breakpoints in `scam_analyzer.py` to inspect variables (headers, body, AI response).
- Log output goes to `scam_analyzer.log` when using `logging.ini` (if you wire it in the code).
