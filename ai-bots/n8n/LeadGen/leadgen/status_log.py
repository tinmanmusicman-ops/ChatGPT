from __future__ import annotations

import atexit
import inspect
import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO, Callable

_STATUS_LOG_INITIALIZED = False
_STATUS_LOG_HANDLE: TextIO | None = None
_MONITOR_FEED_HANDLE: TextIO | None = None
_STATUS_LOG_LOCK = threading.Lock()
_THREAD_STATE = threading.local()


def _normalize_request_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        text = text[1:-1].strip()
    return text


def _redact_secrets(text: str) -> str:
    out = str(text)
    if "-----BEGIN PRIVATE KEY-----" in out:
        return "[REDACTED_PRIVATE_KEY]"
    out = re.sub(r"\bsk-[A-Za-z0-9_\-]+\b", "[REDACTED_OPENAI_KEY]", out)
    out = re.sub(r"\bfc-[A-Za-z0-9_\-]+\b", "[REDACTED_FIRECRAWL_KEY]", out)
    out = re.sub(r"\bBearer\s+[A-Za-z0-9_\-\.=]+\b", "Bearer [REDACTED_TOKEN]", out, flags=re.IGNORECASE)
    return out


def _format_status_line(function_name: str, status: str, message: str | None) -> str:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    depth = getattr(_THREAD_STATE, "depth", 0)
    indent = "\t" * depth
    base = f"{ts} {indent}{function_name} {status}"
    if not message:
        return base
    clean_message = _redact_secrets(message)
    return f"{base} {clean_message}"


def _status_event(function_name: str, status: str, message: str | None = None) -> None:
    if _STATUS_LOG_HANDLE is None:
        return
    clean_message = _redact_secrets(message or "")
    depth = getattr(_THREAD_STATE, "depth", 0)
    line = _format_status_line(function_name, status, clean_message)
    with _STATUS_LOG_LOCK:
        _STATUS_LOG_HANDLE.write(line + "\n")
        _STATUS_LOG_HANDLE.flush()
    payload: dict[str, Any] = {
        "kind": "status",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "depth": depth,
        "source": function_name,
        "status": status,
        "message": clean_message,
    }
    request_id = _normalize_request_id(getattr(_THREAD_STATE, "request_id", ""))
    if request_id:
        payload["request_id"] = request_id
    _write_monitor_feed_event(payload)
    _THREAD_STATE.last_source = function_name


def _write_status_line(line: str) -> None:
    if _STATUS_LOG_HANDLE is None:
        return
    with _STATUS_LOG_LOCK:
        _STATUS_LOG_HANDLE.write(line + "\n")
        _STATUS_LOG_HANDLE.flush()


def _write_monitor_feed_event(event: dict[str, Any]) -> None:
    if _MONITOR_FEED_HANDLE is None:
        return
    payload = json.dumps(event, ensure_ascii=True)
    with _STATUS_LOG_LOCK:
        _MONITOR_FEED_HANDLE.write(payload + "\n")
        _MONITOR_FEED_HANDLE.flush()


def _close_status_log() -> None:
    global _STATUS_LOG_HANDLE
    global _MONITOR_FEED_HANDLE
    if _STATUS_LOG_HANDLE is not None:
        try:
            _STATUS_LOG_HANDLE.flush()
            _STATUS_LOG_HANDLE.close()
        finally:
            _STATUS_LOG_HANDLE = None
    if _MONITOR_FEED_HANDLE is not None:
        try:
            _MONITOR_FEED_HANDLE.flush()
            _MONITOR_FEED_HANDLE.close()
        finally:
            _MONITOR_FEED_HANDLE = None


def initialize_status_log(status_log_path: Path, monitor_feed_path: Path) -> None:
    global _STATUS_LOG_INITIALIZED
    global _STATUS_LOG_HANDLE
    global _MONITOR_FEED_HANDLE
    if _STATUS_LOG_INITIALIZED:
        return
    status_log_path.parent.mkdir(parents=True, exist_ok=True)
    monitor_feed_path.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_LOG_HANDLE = status_log_path.open("a", encoding="utf-8", buffering=1)
    _MONITOR_FEED_HANDLE = monitor_feed_path.open("a", encoding="utf-8", buffering=1)
    _status_event("status_log", "ok", f"boot {status_log_path.name}")
    atexit.register(_close_status_log)
    _STATUS_LOG_INITIALIZED = True


def track_status(function_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request_id = ""
            try:
                bound = signature.bind_partial(*args, **kwargs)
                request_id = _normalize_request_id(bound.arguments.get("request_id", ""))
            except TypeError:
                request_id = ""
            with request_context(request_id):
                _status_event(function_name, "start")
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    _status_event(function_name, "error", str(exc))
                    raise
                _status_event(function_name, "ok")
                return result

        return wrapper

    return decorator


def log_event(function_name: str, status: str, message: str | None = None) -> None:
    _status_event(function_name, status, message)


def log_raw_line(message: str, source: str | None = None) -> None:
    clean = _redact_secrets(message)
    _write_status_line(clean)
    resolved_source = source if source else getattr(_THREAD_STATE, "last_source", "")
    payload: dict[str, Any] = {
        "kind": "text",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "depth": getattr(_THREAD_STATE, "depth", 0),
        "source": resolved_source,
        "status": "info",
        "message": clean,
    }
    if "=" in clean:
        key, value = clean.split("=", 1)
        key_text = key.strip()
        value_text = value.strip()
        payload["kind"] = "payload_pair"
        payload["key"] = key_text
        payload["value"] = value_text
        if key_text == "request_id":
            normalized = _normalize_request_id(value_text)
            if normalized:
                _THREAD_STATE.request_id = normalized
    request_id = _normalize_request_id(getattr(_THREAD_STATE, "request_id", ""))
    if request_id:
        payload["request_id"] = request_id
    _write_monitor_feed_event(payload)


@contextmanager
def indent_context() -> Callable[..., Any]:
    depth = getattr(_THREAD_STATE, "depth", 0)
    _THREAD_STATE.depth = depth + 1
    try:
        yield
    finally:
        _THREAD_STATE.depth = depth


@contextmanager
def request_context(request_id: str | None) -> Callable[..., Any]:
    previous = _normalize_request_id(getattr(_THREAD_STATE, "request_id", ""))
    normalized = _normalize_request_id(request_id)
    if normalized:
        _THREAD_STATE.request_id = normalized
    elif hasattr(_THREAD_STATE, "request_id"):
        delattr(_THREAD_STATE, "request_id")
    try:
        yield
    finally:
        if previous:
            _THREAD_STATE.request_id = previous
        elif hasattr(_THREAD_STATE, "request_id"):
            delattr(_THREAD_STATE, "request_id")
