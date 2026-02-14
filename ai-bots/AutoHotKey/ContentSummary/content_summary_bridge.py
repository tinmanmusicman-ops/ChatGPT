from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
TMP_DIR = PROJECT_DIR / "tmp"
LOG_DIR = PROJECT_DIR / "logs"
LAST_HTML_PATH = LOG_DIR / "last_content_summary.html"
LAST_TEXT_PATH = LOG_DIR / "last_content_summary.txt"
LAST_ERROR_PATH = LOG_DIR / "last_content_summary_error.txt"
SUMMARIZER_SCRIPT = PROJECT_DIR / "summarize_content.py"
PYTHON_EXE = Path(r"C:\ChatGPT\ai-bots\AutoHotKey\EvaluateJobFit\.venv\Scripts\python.exe")


class BridgeError(RuntimeError):
    pass


def _read_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _run_summary(text: str) -> dict[str, str]:
    clean = text.strip()
    if not clean:
        raise BridgeError("No text selected to summarize.")
    if not PYTHON_EXE.exists():
        raise BridgeError(f"Python executable not found: {PYTHON_EXE}")
    if not SUMMARIZER_SCRIPT.exists():
        raise BridgeError(f"Summarizer script not found: {SUMMARIZER_SCRIPT}")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    input_path = TMP_DIR / "content_from_browser.txt"
    input_path.write_text(clean, encoding="utf-8")

    result = subprocess.run(
        [str(PYTHON_EXE), str(SUMMARIZER_SCRIPT), str(input_path), "--no-open"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        error_text = _read_if_exists(LAST_ERROR_PATH) or result.stderr.strip() or result.stdout.strip()
        if not error_text:
            error_text = f"Summarizer failed with exit code {result.returncode}."
        raise BridgeError(error_text)

    if not LAST_HTML_PATH.exists():
        raise BridgeError(f"Summary HTML was not generated: {LAST_HTML_PATH}")

    return {
        "url": "http://127.0.0.1:8765/last",
        "text": _read_if_exists(LAST_TEXT_PATH),
    }


class SummaryBridgeHandler(BaseHTTPRequestHandler):
    server_version = "ContentSummaryBridge/1.0"

    def _set_headers(self, status: int, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._set_headers(204)

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            self._set_headers(200)
            self.wfile.write(b'{"ok":true,"service":"content-summary-bridge"}')
            return

        if self.path.startswith("/last"):
            if not LAST_HTML_PATH.exists():
                self._set_headers(404)
                self.wfile.write(b'{"ok":false,"error":"No summary html found yet."}')
                return
            try:
                html = LAST_HTML_PATH.read_text(encoding="utf-8")
            except OSError as exc:
                self._set_headers(500)
                self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
                return
            self._set_headers(200, "text/html; charset=utf-8")
            self.wfile.write(html.encode("utf-8"))
            return

        self._set_headers(404)
        self.wfile.write(b'{"ok":false,"error":"Not found"}')

    def do_POST(self) -> None:
        if self.path != "/summarize":
            self._set_headers(404)
            self.wfile.write(b'{"ok":false,"error":"Not found"}')
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        payload_raw = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except json.JSONDecodeError as exc:
            self._set_headers(400)
            self.wfile.write(json.dumps({"ok": False, "error": f"Invalid JSON: {exc}"}).encode("utf-8"))
            return

        text = payload.get("text", "")
        if not isinstance(text, str):
            self._set_headers(400)
            self.wfile.write(b'{"ok":false,"error":"text must be a string"}')
            return

        try:
            result = _run_summary(text)
        except BridgeError as exc:
            self._set_headers(500)
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
            return
        except subprocess.TimeoutExpired:
            self._set_headers(500)
            self.wfile.write(b'{"ok":false,"error":"Summarizer timed out."}')
            return
        except Exception as exc:  # pragma: no cover - safety net
            self._set_headers(500)
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
            return

        self._set_headers(200)
        self.wfile.write(json.dumps({"ok": True, **result}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - keep bridge quiet
        return


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local bridge for browser right-click Content Summary.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        server = ThreadingHTTPServer((args.host, args.port), SummaryBridgeHandler)
    except OSError as exc:
        if "10048" in str(exc):
            return 0
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"content_summary_bridge listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
