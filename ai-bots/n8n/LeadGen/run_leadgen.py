#!/usr/bin/env python3
from __future__ import annotations

import atexit
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from datetime import datetime, timezone
from typing import Any, TextIO
from uuid import uuid4

from leadgen.config import Config
from leadgen.errors import LeadGenError
from leadgen.pipeline import LeadVettingPipeline
from leadgen.status_log import initialize_status_log, track_status


class FailFastError(RuntimeError):
    pass


_RUNTIME_LOG_INITIALIZED = False
_RUNTIME_LOG_HANDLE: TextIO | None = None
_RUNTIME_LOG_LOCK = threading.Lock()
_ORIGINAL_STDOUT: TextIO | None = None
_ORIGINAL_STDERR: TextIO | None = None
_SERVICE_ACCOUNT_REQUIRED_KEYS = (
    "type",
    "project_id",
    "private_key_id",
    "private_key",
    "client_email",
    "client_id",
    "auth_uri",
    "token_uri",
    "auth_provider_x509_cert_url",
    "client_x509_cert_url",
)

class _TeeStream:
    def __init__(self, primary: TextIO, log_handle: TextIO, lock: threading.Lock) -> None:
        self.primary = primary
        self.log_handle = log_handle
        self.lock = lock

    def write(self, data: str) -> int:
        if not data:
            return 0
        text = str(data)
        with self.lock:
            written = self.primary.write(text)
            try:
                self.log_handle.write(text)
                self.log_handle.flush()
            except Exception:
                pass
        return written if isinstance(written, int) else len(text)

    def flush(self) -> None:
        with self.lock:
            try:
                self.primary.flush()
            except Exception:
                pass
            try:
                self.log_handle.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return bool(getattr(self.primary, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self.primary, "encoding", "utf-8")

@track_status("Function _close_runtime_log")
def _close_runtime_log() -> None:
    global _RUNTIME_LOG_HANDLE
    global _ORIGINAL_STDOUT
    global _ORIGINAL_STDERR

    if _ORIGINAL_STDOUT is not None:
        sys.stdout = _ORIGINAL_STDOUT
    if _ORIGINAL_STDERR is not None:
        sys.stderr = _ORIGINAL_STDERR

    if _RUNTIME_LOG_HANDLE is not None:
        try:
            _RUNTIME_LOG_HANDLE.flush()
            _RUNTIME_LOG_HANDLE.close()
        finally:
            _RUNTIME_LOG_HANDLE = None

@track_status("Function _init_runtime_log")
def _init_runtime_log(runtime_log_path: Path) -> None:
    global _RUNTIME_LOG_INITIALIZED
    global _RUNTIME_LOG_HANDLE
    global _ORIGINAL_STDOUT
    global _ORIGINAL_STDERR

    if _RUNTIME_LOG_INITIALIZED:
        return

    runtime_log_path.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_LOG_HANDLE = runtime_log_path.open("a", encoding="utf-8", buffering=1)
    _RUNTIME_LOG_HANDLE.write(
        f'{{"ts_utc":"{datetime.now(timezone.utc).isoformat()}","event":"runtime_boot","pid":{os.getpid()},"script":"{Path(__file__).resolve().as_posix()}"}}\n'
    )
    _RUNTIME_LOG_HANDLE.flush()

    stdout = sys.stdout if sys.stdout is not None else sys.__stdout__
    stderr = sys.stderr if sys.stderr is not None else sys.__stderr__
    if stdout is None or stderr is None:
        raise FailFastError("stdout/stderr unavailable for runtime logging")

    _ORIGINAL_STDOUT = stdout
    _ORIGINAL_STDERR = stderr
    sys.stdout = _TeeStream(stdout, _RUNTIME_LOG_HANDLE, _RUNTIME_LOG_LOCK)
    sys.stderr = _TeeStream(stderr, _RUNTIME_LOG_HANDLE, _RUNTIME_LOG_LOCK)

    atexit.register(_close_runtime_log)
    _RUNTIME_LOG_INITIALIZED = True


@track_status("Function _load_env_file")
def _load_env_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    if not dotenv_path.is_file():
        raise FailFastError(f".env path exists but is not a file: {dotenv_path}")

    for line_no, raw_line in enumerate(dotenv_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise FailFastError(f"Invalid .env format at line {line_no}: {dotenv_path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise FailFastError(f"Empty .env key at line {line_no}: {dotenv_path}")
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value



@track_status("Function _resolve_global_json_path")
def _resolve_global_json_path(script_dir: Path) -> Path:
    override = os.getenv("LEADGEN_GLOBAL_JSON", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # HSST standard location for shared runtime context.
    return (script_dir.parents[2] / "shared" / "Global.json").resolve()


@track_status("Function _read_global_json")
def _read_global_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FailFastError(f"Missing Global.json: {path}")
    if not path.is_file():
        raise FailFastError(f"Global.json path is not a file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FailFastError(f"Global.json is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FailFastError(f"Global.json root must be an object: {path}")
    return payload


def _first_nonempty(cfg: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = cfg.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _set_env_if_missing(name: str, value: str) -> None:
    if not value:
        return
    if os.getenv(name, "").strip():
        return
    os.environ[name] = value


@track_status("Function _materialize_service_account_from_global")
def _materialize_service_account_from_global(global_cfg: dict[str, Any], output_path: Path) -> Path:
    missing = [key for key in _SERVICE_ACCOUNT_REQUIRED_KEYS if not str(global_cfg.get(key, "")).strip()]
    if missing:
        raise FailFastError(
            "Global.json missing service-account keys required for Google auth: " + ", ".join(missing)
        )

    payload: dict[str, Any] = {key: global_cfg[key] for key in _SERVICE_ACCOUNT_REQUIRED_KEYS}
    if str(global_cfg.get("universe_domain", "")).strip():
        payload["universe_domain"] = global_cfg["universe_domain"]

    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return output_path


@track_status("Function _load_hsst_global_into_env")
def _load_hsst_global_into_env(script_dir: Path, runtime_log_path: Path) -> None:
    global_path = _resolve_global_json_path(script_dir)
    global_cfg = _read_global_json(global_path)

    _set_env_if_missing("OPENAI_API_KEY", _first_nonempty(global_cfg, ("OPENAI_API_KEY", "openai_api_key")))
    _set_env_if_missing("FIRECRAWL_API_KEY", _first_nonempty(global_cfg, ("FIRECRAWL_API_KEY", "firecrawl_api_key")))
    _set_env_if_missing(
        "LEADGEN_GOOGLE_SHEET_ID",
        _first_nonempty(global_cfg, ("LEADGEN_GOOGLE_SHEET_ID", "google_sheet_id", "spreadsheet_id")),
    )
    _set_env_if_missing(
        "LEADGEN_GOOGLE_SHEET_TAB",
        _first_nonempty(global_cfg, ("LEADGEN_GOOGLE_SHEET_TAB", "google_sheet_tab", "worksheet_name")),
    )
    _set_env_if_missing("LEADGEN_OPENAI_MODEL", _first_nonempty(global_cfg, ("LEADGEN_OPENAI_MODEL", "openai_model")))
    _set_env_if_missing(
        "LEADGEN_OPENAI_BASE_URL",
        _first_nonempty(global_cfg, ("LEADGEN_OPENAI_BASE_URL", "openai_base_url")),
    )
    _set_env_if_missing(
        "LEADGEN_FIRECRAWL_BASE_URL",
        _first_nonempty(global_cfg, ("LEADGEN_FIRECRAWL_BASE_URL", "firecrawl_base_url")),
    )
    _set_env_if_missing(
        "LEADGEN_MANUAL_REVIEW_THRESHOLD",
        _first_nonempty(global_cfg, ("LEADGEN_MANUAL_REVIEW_THRESHOLD", "manual_review_threshold")),
    )
    _set_env_if_missing(
        "LEADGEN_LOG_FILE",
        _first_nonempty(global_cfg, ("LEADGEN_LOG_FILE", "leadgen_log_file")) or str(runtime_log_path),
    )
    _set_env_if_missing("LEADGEN_DEFAULT_ROW", _first_nonempty(global_cfg, ("LEADGEN_DEFAULT_ROW",)))

    if not os.getenv("LEADGEN_GOOGLE_CREDENTIALS_FILE", "").strip():
        candidate_path = _first_nonempty(
            global_cfg,
            ("LEADGEN_GOOGLE_CREDENTIALS_FILE", "google_credentials_file", "service_account_json", "service_account"),
        )
        if candidate_path:
            path = Path(candidate_path).expanduser()
            if not path.is_absolute():
                path = (global_path.parent / path).resolve()
            if not path.exists():
                raise FailFastError(f"Global-configured Google credentials file not found: {path}")
            os.environ["LEADGEN_GOOGLE_CREDENTIALS_FILE"] = str(path)
        else:
            generated = (script_dir / ".service_account.from_global.json").resolve()
            os.environ["LEADGEN_GOOGLE_CREDENTIALS_FILE"] = str(
                _materialize_service_account_from_global(global_cfg, generated)
            )

    print(
        json.dumps(
            {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "event": "global_json_loaded",
                "global_path": str(global_path),
            },
            ensure_ascii=True,
        )
    )
@track_status("Function _read_payload_file")
def _read_payload_file(payload_file: str) -> dict[str, Any]:
    path = Path(payload_file).expanduser().resolve()
    if not path.exists():
        raise FailFastError(f"Missing payload file: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise FailFastError(f"Payload file is empty: {path}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FailFastError(f"Payload file is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FailFastError(f"Payload JSON must be an object: {path}")
    return payload
@track_status("Function _parse_args")
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-contained LeadGen runner (single row mode or webhook mode).",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "webhook"],
        default="single",
        help="single = process one row; webhook = run HTTP endpoint",
    )
    parser.add_argument("--row-number", type=int, default=0, help="Google Sheet row number (2+).")
    parser.add_argument("--request-id", type=str, default="", help="Optional request id for traceability.")
    parser.add_argument(
        "--payload-file",
        type=str,
        default="",
        help="Optional JSON file like {\"rowNumber\":2,\"requestId\":\"abc\"}.",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Webhook bind host.")
    parser.add_argument("--port", type=int, default=8787, help="Webhook bind port.")
    parser.add_argument("--path", type=str, default="/webhook/lead-vetting-prod", help="Webhook path.")
    return parser.parse_args()
@track_status("Function _resolve_inputs")
def _resolve_inputs(args: argparse.Namespace) -> tuple[int, str]:
    if args.payload_file:
        payload = _read_payload_file(args.payload_file)
        source = payload.get("body") if isinstance(payload.get("body"), dict) else payload
        row_raw = source.get("rowNumber", source.get("row_number", source.get("row")))
        request_id = str(source.get("requestId", source.get("request_id", ""))).strip()
        try:
            row_number = int(row_raw)
        except (TypeError, ValueError) as exc:
            raise FailFastError("Payload rowNumber must be an integer >= 2") from exc
    else:
        row_number = int(args.row_number)
        if row_number < 2:
            default_row = os.getenv("LEADGEN_DEFAULT_ROW", "").strip()
            if default_row:
                try:
                    row_number = int(default_row)
                except ValueError as exc:
                    raise FailFastError("LEADGEN_DEFAULT_ROW must be an integer >= 2") from exc
        request_id = str(args.request_id or "").strip()

    if row_number < 2:
        raise FailFastError("row_number must be integer >= 2")
    return row_number, request_id
@track_status("Function _json_response")
def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
@track_status("Function _read_json_body")
def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = handler.headers.get("Content-Length", "").strip()
    if not content_length:
        raise FailFastError("Missing Content-Length header")
    try:
        length = int(content_length)
    except ValueError as exc:
        raise FailFastError("Invalid Content-Length header") from exc
    if length <= 0:
        raise FailFastError("Request body is empty")
    raw = handler.rfile.read(length).decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FailFastError("Request body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise FailFastError("JSON payload must be an object")
    return payload
@track_status("Function _extract_payload_fields")
def _extract_payload_fields(payload: dict[str, Any]) -> tuple[int, str]:
    source = payload.get("body") if isinstance(payload.get("body"), dict) else payload
    row_raw = source.get("rowNumber", source.get("row_number", source.get("row")))
    try:
        row_number = int(row_raw)
    except (TypeError, ValueError) as exc:
        raise FailFastError("rowNumber must be an integer >= 2") from exc
    if row_number < 2:
        raise FailFastError("rowNumber must be an integer >= 2")
    request_id = str(source.get("requestId", source.get("request_id", ""))).strip() or str(uuid4())
    return row_number, request_id
@track_status("Function _run_single_mode")
def _run_single_mode(args: argparse.Namespace, pipeline: LeadVettingPipeline) -> int:
    row_number, request_id = _resolve_inputs(args)
    result = pipeline.run_single_row(row_number=row_number, request_id=request_id)
    print(
        json.dumps(
            {
                "ok": result.ok,
                "rowNumber": result.row_number,
                "status": result.status,
                "requestId": result.request_id,
                "updatedRanges": result.updated_ranges,
                "ignoredColumns": result.ignored_keys,
            },
            ensure_ascii=True,
        )
    )
    return 0
@track_status("Function _run_webhook_mode")
def _run_webhook_mode(args: argparse.Namespace, pipeline: LeadVettingPipeline) -> int:
    webhook_path = args.path if args.path.startswith("/") else f"/{args.path}"

    class Handler(BaseHTTPRequestHandler):
        @track_status("Function Handler.do_POST")
        def do_POST(self) -> None:  # noqa: N802
            if self.path != webhook_path:
                _json_response(self, 404, {"ok": False, "error": "Not Found", "path": self.path})
                return
            try:
                payload = _read_json_body(self)
                row_number, request_id = _extract_payload_fields(payload)
            except FailFastError as exc:
                _json_response(self, 400, {"ok": False, "error": str(exc)})
                return

            try:
                result = pipeline.run_single_row(row_number=row_number, request_id=request_id)
            except Exception as exc:
                _json_response(self, 500, {"ok": False, "error": f"Unhandled pipeline error: {exc}"})
                return

            _json_response(
                self,
                200,
                {
                    "ok": result.ok,
                    "rowNumber": result.row_number,
                    "status": result.status,
                    "requestId": result.request_id,
                    "updatedRanges": result.updated_ranges,
                    "ignoredColumns": result.ignored_keys,
                },
            )

        @track_status("Function Handler.do_GET")
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                _json_response(self, 200, {"ok": True, "service": "leadgen-webhook"})
                return
            _json_response(self, 404, {"ok": False, "error": "Not Found", "path": self.path})

        @track_status("Function Handler.log_message")
        def log_message(self, fmt: str, *a: Any) -> None:
            print(f"WEBHOOK {self.address_string()} {fmt % a}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        json.dumps(
            {
                "ok": True,
                "service": "leadgen-webhook",
                "listen": f"http://{args.host}:{args.port}{webhook_path}",
                "health": f"http://{args.host}:{args.port}/health",
            },
            ensure_ascii=True,
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
@track_status("Function main")
def main() -> int:

    try:
        script_dir = Path(__file__).resolve().parent
        initialize_status_log(
            script_dir / "status.log",
            script_dir / "monitor_feed.jsonl",
        )
        runtime_log_path = script_dir / "Runtime.log"
        _init_runtime_log(runtime_log_path)
        args = _parse_args()
        _load_env_file(script_dir / ".env")
        _load_hsst_global_into_env(script_dir, runtime_log_path)
        config = Config.from_env()
        pipeline = LeadVettingPipeline(config)
        if args.mode == "webhook":
            return _run_webhook_mode(args, pipeline)
        return _run_single_mode(args, pipeline)
    except (FailFastError, LeadGenError, RuntimeError) as exc:
        print(f"FAIL-FAST: {exc}")
        return 1
    except Exception as exc:
        print(f"FAIL-FAST: Unexpected crash: {exc}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
