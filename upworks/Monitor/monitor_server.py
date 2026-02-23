#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4


GRAPH_DEFINITION: dict[str, Any] = {
    "node_types": [
        {"id": "code", "label": "Code", "image": "/Images/Code.png"},
        {"id": "ss", "label": "SS", "image": "/Images/SS.png"},
        {"id": "ai", "label": "AI", "image": "/Images/AI.png"},
        {"id": "gmail", "label": "Gmail", "image": "/Images/gmail.png"},
        {"id": "if", "label": "If", "image": "/Images/If.png"},
        {"id": "sched", "label": "Sched", "image": "/Images/Sched.png"},
        {"id": "trig", "label": "Trig", "image": "/Images/Trig.png"},
        {"id": "scrape", "label": "Scrape", "image": "/Images/scrape.png"},
    ],
    "nodes": [
        {
            "id": "boot",
            "label": "Main",
            "summary": "Entrypoint and monitor startup.",
            "activity_type": "code",
            "x": 120,
            "y": 70,
            "code_source": "main.py",
            "code_preview": "def main() -> int: ...",
        },
        {
            "id": "args",
            "label": "Parse args",
            "summary": "Parses CLI config path.",
            "activity_type": "code",
            "x": 250,
            "y": 70,
            "code_source": "main.py",
            "code_preview": "def parse_args() -> argparse.Namespace: ...",
        },
        {
            "id": "config_load",
            "label": "Load Config",
            "summary": "Loads Global.json into AppConfig.",
            "activity_type": "code",
            "x": 380,
            "y": 70,
            "code_source": "config.py",
            "code_preview": "def load_config(config_path: Path) -> AppConfig: ...",
        },
        {
            "id": "run_job",
            "label": "Run Flow",
            "summary": "Executes one Upwork ingest run.",
            "activity_type": "trig",
            "x": 520,
            "y": 70,
            "code_source": "main.py",
            "code_preview": "def run(config: AppConfig) -> int: ...",
        },
        {
            "id": "imap_search",
            "label": "Find Emails",
            "summary": "Searches unread Upwork emails.",
            "activity_type": "gmail",
            "x": 660,
            "y": 70,
            "code_source": "mail_imap.py",
            "code_preview": "def search_uids(...): ...",
        },
        {
            "id": "no_emails",
            "label": "No Emails",
            "summary": "No unread Upwork emails matched the criteria.",
            "activity_type": "if",
            "x": 660,
            "y": -10,
            "code_source": "main.py",
            "code_preview": "if not uids: log_event(..., 'no_unread_upwork_emails', ...); return 0",
        },
        {
            "id": "imap_fetch",
            "label": "Fetch Email",
            "summary": "Fetches each email by UID.",
            "activity_type": "gmail",
            "x": 800,
            "y": 70,
            "code_source": "mail_imap.py",
            "code_preview": "def fetch_message(...): ...",
        },
        {
            "id": "extract",
            "label": "Extract Job",
            "summary": "Parses message id, URL, body, timestamp.",
            "activity_type": "scrape",
            "x": 940,
            "y": 70,
            "code_source": "extractor.py",
            "code_preview": "def extract_job_email(...): ...",
        },
        {
            "id": "dedupe",
            "label": "Deduplicate",
            "summary": "Skips already-seen Message IDs.",
            "activity_type": "if",
            "x": 1080,
            "y": 70,
            "code_source": "main.py",
            "code_preview": "if extracted.message_id in existing_message_ids: ...",
        },
        {
            "id": "finished",
            "label": "Finished",
            "summary": "Represents duplicate-only completion branch.",
            "activity_type": "if",
            "x": 1080,
            "y": -10,
            "code_source": "main.py",
            "code_preview": "if duplicate-only run: finish branch",
        },
        {
            "id": "ai_eval",
            "label": "AI Advice",
            "summary": "Runs advisory scoring and Do Bid hint.",
            "activity_type": "ai",
            "x": 1220,
            "y": 70,
            "code_source": "ai_eval.py",
            "code_preview": "def evaluate_job(...): ...",
        },
        {
            "id": "stage_row",
            "label": "Stage Row",
            "summary": "Builds row payload for sheet append.",
            "activity_type": "code",
            "x": 1360,
            "y": 70,
            "code_source": "main.py",
            "code_preview": "row = _build_sheet_row(...)",
        },
        {
            "id": "sheet_append",
            "label": "Write SS",
            "summary": "Appends staged rows to spreadsheet.",
            "activity_type": "ss",
            "x": 1500,
            "y": 70,
            "code_source": "sheets.py",
            "code_preview": "def append_rows(self, rows): ...",
        },
        {
            "id": "label_email",
            "label": "Move Email",
            "summary": "Adds Upwork label and removes Inbox label.",
            "activity_type": "gmail",
            "x": 1640,
            "y": 70,
            "code_source": "mail_imap.py",
            "code_preview": "add_label(...); remove_inbox_label(...); mark_as_read(...)",
        },
        {
            "id": "complete",
            "label": "Success",
            "summary": "Run finished without fatal errors.",
            "activity_type": "code",
            "x": 1780,
            "y": 20,
            "code_source": "main.py",
            "code_preview": "log_event(..., 'run_end', **summary)",
        },
        {
            "id": "error",
            "label": "Error",
            "summary": "Run failed or produced processing errors.",
            "activity_type": "code",
            "x": 960,
            "y": 320,
            "width": 220,
            "code_source": "main.py",
            "code_preview": "except (...) as exc: ...",
        },
    ],
    "edges": [
        {"source": "boot", "target": "args"},
        {"source": "args", "target": "config_load"},
        {"source": "config_load", "target": "run_job"},
        {"source": "run_job", "target": "imap_search"},
        {
            "source": "imap_search",
            "target": "no_emails",
            "source_anchor": "top",
            "target_anchor": "bottom",
        },
        {"source": "imap_search", "target": "imap_fetch"},
        {"source": "imap_fetch", "target": "extract"},
        {"source": "extract", "target": "dedupe"},
        {
            "source": "dedupe",
            "target": "finished",
            "source_anchor": "top",
            "target_anchor": "bottom",
        },
        {"source": "dedupe", "target": "ai_eval"},
        {"source": "ai_eval", "target": "stage_row"},
        {"source": "stage_row", "target": "sheet_append"},
        {"source": "sheet_append", "target": "label_email"},
        {"source": "label_email", "target": "complete"},
        {
            "source": "config_load",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "imap_search",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "dedupe",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "stage_row",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "label_email",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "run_job",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "imap_fetch",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "extract",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "ai_eval",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
        {
            "source": "sheet_append",
            "target": "error",
            "source_anchor": "bottom",
            "target_anchor": "top",
        },
    ],
    "pipeline_reset_nodes": [
        "run_job",
        "imap_search",
        "no_emails",
        "imap_fetch",
        "extract",
        "dedupe",
        "finished",
        "ai_eval",
        "stage_row",
        "sheet_append",
        "label_email",
        "complete",
        "error",
    ],
}

NODE_CODE_SYMBOL: dict[str, str] = {
    "boot": "main",
    "args": "parse_args",
    "config_load": "load_config",
    "run_job": "run",
    "imap_search": "ImapMailbox.search_uids",
    "no_emails": "run",
    "imap_fetch": "ImapMailbox.fetch_message",
    "extract": "extract_job_email",
    "dedupe": "run",
    "finished": "run",
    "ai_eval": "evaluate_job",
    "stage_row": "_build_sheet_row",
    "sheet_append": "SheetsClient.append_rows",
    "label_email": "ImapMailbox.remove_inbox_label",
    "complete": "run",
    "error": "main",
}


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds")


def _short_ts(ts_utc: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.strftime("%H:%M:%S.%f")[:-3]


def _status_event(
    *,
    source: str,
    status: str,
    message: str,
    node_id: str | None,
    request_id: str,
    ts_utc: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    ts_value = ts_utc or _utc_now_iso()
    payload: dict[str, Any] = {
        "kind": "status",
        "source": source,
        "status": status,
        "message": message,
        "ts_utc": ts_value,
        "ts": _short_ts(ts_value),
        "request_id": request_id,
    }
    if node_id:
        payload["node_id"] = node_id
    if extra:
        payload.update(extra)
    return payload


def _payload_event(
    *,
    source: str,
    key: str,
    value: Any,
    request_id: str,
    ts_utc: str,
) -> dict[str, Any]:
    return {
        "kind": "payload_pair",
        "source": source,
        "key": key,
        "value": value,
        "ts_utc": ts_utc,
        "ts": _short_ts(ts_utc),
        "request_id": request_id,
        "raw_line": f"{key}={value}",
    }


def _text_event(*, line: str, request_id: str, source: str) -> dict[str, Any]:
    ts_value = _utc_now_iso()
    return {
        "kind": "text",
        "source": source,
        "raw_line": line,
        "ts_utc": ts_value,
        "ts": _short_ts(ts_value),
        "request_id": request_id,
    }


def _resolve_static_path(static_dir: Path, relative_path: str) -> Path:
    relative = relative_path.lstrip("/")
    path = (static_dir / relative).resolve()
    if static_dir not in path.parents and path != static_dir:
        raise RuntimeError(f"Invalid static path: {relative_path}")
    return path


def _find_graph_node(node_id: str) -> dict[str, Any] | None:
    for node in GRAPH_DEFINITION.get("nodes", []):
        if isinstance(node, dict) and str(node.get("id", "")).strip() == node_id:
            return node
    return None


def _load_node_code(project_root: Path, node_id: str) -> dict[str, Any]:
    node = _find_graph_node(node_id)
    if node is None:
        raise RuntimeError(f"Unknown node_id: {node_id}")

    code_source = str(node.get("code_source", "")).strip()
    if not code_source:
        raise RuntimeError(f"Node {node_id} missing code_source")

    source_path = (project_root / code_source).resolve()
    if project_root.resolve() not in source_path.parents and source_path != project_root.resolve():
        raise RuntimeError(f"Code source escapes project root: {code_source}")
    if not source_path.exists() or not source_path.is_file():
        raise RuntimeError(f"Code source file not found: {source_path}")

    code_text = source_path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "node_id": node_id,
        "code_source": code_source,
        "code_path": str(source_path),
        "code_symbol": NODE_CODE_SYMBOL.get(node_id, ""),
        "code_line_start": 1,
        "code": code_text,
    }


def _open_node_in_vscode(project_root: Path, node_id: str) -> dict[str, Any]:
    payload = _load_node_code(project_root=project_root, node_id=node_id)
    code_cli = shutil.which("code")
    if not code_cli:
        raise RuntimeError("VS Code CLI not found on PATH (expected 'code').")
    target = f"{payload['code_path']}:1"
    subprocess.Popen([code_cli, "-g", target], cwd=str(project_root))
    return {"ok": True, "node_id": node_id, "target": target}


def _validate_graph(static_dir: Path, project_root: Path) -> None:
    node_types = GRAPH_DEFINITION.get("node_types")
    if not isinstance(node_types, list) or not node_types:
        raise RuntimeError("GRAPH_DEFINITION.node_types must be a non-empty list")

    valid_type_ids: set[str] = set()
    for item in node_types:
        if not isinstance(item, dict):
            raise RuntimeError("node_types entries must be objects")
        type_id = str(item.get("id", "")).strip()
        image = str(item.get("image", "")).strip()
        if not type_id or not image:
            raise RuntimeError("Each node type must include id and image")
        img_path = _resolve_static_path(static_dir, image)
        if not img_path.exists() or not img_path.is_file():
            raise RuntimeError(f"Missing node type image: {img_path}")
        valid_type_ids.add(type_id)

    node_ids: set[str] = set()
    for node in GRAPH_DEFINITION.get("nodes", []):
        if not isinstance(node, dict):
            raise RuntimeError("nodes entries must be objects")
        node_id = str(node.get("id", "")).strip()
        activity_type = str(node.get("activity_type", "")).strip()
        if not node_id:
            raise RuntimeError("Node missing id")
        if activity_type not in valid_type_ids:
            raise RuntimeError(f"Node {node_id} has invalid activity_type {activity_type}")
        _load_node_code(project_root, node_id)
        node_ids.add(node_id)

    for edge in GRAPH_DEFINITION.get("edges", []):
        if not isinstance(edge, dict):
            raise RuntimeError("edges entries must be objects")
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source not in node_ids or target not in node_ids:
            raise RuntimeError(f"Invalid edge {source}->{target}")


class EventBus:
    def __init__(self, history_limit: int, feed_path: Path) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._event_id = 0
        self.feed_path = feed_path
        self.feed_path.parent.mkdir(parents=True, exist_ok=True)
        self.feed_path.touch(exist_ok=True)
        self._load_history()

    def _load_history(self) -> None:
        lines = self.feed_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > self._history.maxlen:
            lines = lines[-self._history.maxlen :]
        for raw in lines:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            self._event_id += 1
            parsed["event_id"] = self._event_id
            self._history.append(parsed)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._event_id += 1
            payload = dict(event)
            payload["event_id"] = self._event_id
            self._history.append(payload)
            with self.feed_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
            subscribers = list(self._subscribers)

        for sub in subscribers:
            try:
                sub.put_nowait(payload)
            except queue.Full:
                continue

    def get_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


class UpworksRunner:
    def __init__(self, *, project_root: Path, config_path: Path, python_exe: str, bus: EventBus) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.python_exe = python_exe
        self.bus = bus
        self._lock = threading.Lock()
        self._active_proc: subprocess.Popen[str] | None = None
        self._run_state: dict[str, dict[str, Any]] = {}

    def _set_run_flag(self, request_id: str, flag: str, value: bool) -> None:
        with self._lock:
            state = self._run_state.setdefault(request_id, {})
            state[flag] = bool(value)

    def _get_run_flag(self, request_id: str, flag: str, default: bool = False) -> bool:
        with self._lock:
            return bool(self._run_state.get(request_id, {}).get(flag, default))

    def _set_run_value(self, request_id: str, key: str, value: Any) -> None:
        with self._lock:
            state = self._run_state.setdefault(request_id, {})
            state[key] = value

    def _get_run_value(self, request_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._run_state.get(request_id, {}).get(key, default)

    def _mark_ai_error_uid(self, request_id: str, uid: str) -> None:
        if not uid:
            return
        with self._lock:
            state = self._run_state.setdefault(request_id, {})
            uid_set = state.get("ai_error_uids")
            if not isinstance(uid_set, set):
                uid_set = set()
                state["ai_error_uids"] = uid_set
            uid_set.add(uid)

    def _has_ai_error_uid(self, request_id: str, uid: str) -> bool:
        if not uid:
            return False
        with self._lock:
            state = self._run_state.get(request_id, {})
            uid_set = state.get("ai_error_uids")
            return isinstance(uid_set, set) and uid in uid_set

    def _clear_ai_error_uid(self, request_id: str, uid: str) -> None:
        if not uid:
            return
        with self._lock:
            state = self._run_state.get(request_id, {})
            uid_set = state.get("ai_error_uids")
            if isinstance(uid_set, set):
                uid_set.discard(uid)

    def trigger(self, *, request_id: str, row_number: int, cold_start: bool) -> dict[str, Any]:
        with self._lock:
            if self._active_proc is not None and self._active_proc.poll() is None:
                raise RuntimeError(f"A run is already active (pid={self._active_proc.pid}).")

            thread = threading.Thread(
                target=self._run,
                kwargs={"request_id": request_id, "row_number": row_number, "cold_start": cold_start},
                daemon=True,
                name=f"upworks-run-{request_id[:8]}",
            )
            thread.start()

        return {
            "ok": True,
            "triggered": {
                "mode": "cold_start" if cold_start else "normal",
                "rowNumber": row_number,
                "requestId": request_id,
                "command": [self.python_exe, "main.py", "--config", str(self.config_path)],
            },
        }

    def _run(self, *, request_id: str, row_number: int, cold_start: bool) -> None:
        self.bus.publish(
            _status_event(
                source="Function main",
                status="start",
                message=f"trigger mode={'cold_start' if cold_start else 'normal'} row={row_number}",
                node_id="boot",
                request_id=request_id,
            )
        )
        self.bus.publish(
            _status_event(
                source="Function parse_args",
                status="ok",
                message="arguments prepared",
                node_id="args",
                request_id=request_id,
            )
        )
        self.bus.publish(
            _status_event(
                source="Function load_config",
                status="start",
                message=f"config={self.config_path}",
                node_id="config_load",
                request_id=request_id,
            )
        )

        cmd = [self.python_exe, "main.py", "--config", str(self.config_path)]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            self.bus.publish(
                _status_event(
                    source="Function subprocess.Popen",
                    status="error",
                    message=str(exc),
                    node_id="error",
                    request_id=request_id,
                )
            )
            return

        with self._lock:
            self._active_proc = proc

        out_thread = threading.Thread(
            target=self._consume_stream,
            kwargs={"stream": proc.stdout, "request_id": request_id, "stderr": False},
            daemon=True,
        )
        err_thread = threading.Thread(
            target=self._consume_stream,
            kwargs={"stream": proc.stderr, "request_id": request_id, "stderr": True},
            daemon=True,
        )
        out_thread.start()
        err_thread.start()

        return_code = proc.wait()
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)

        final_node = "error" if return_code != 0 else None
        final_edge_from = str(self._get_run_value(request_id, "last_error_node", "") or "").strip()
        final_status = "ok" if return_code == 0 else "error"
        final_message = (
            "workflow process exited with code 0"
            if return_code == 0
            else f"workflow process exited with code {return_code}"
        )
        if final_node:
            self.bus.publish(
                _status_event(
                    source="status_log",
                    status="start",
                    message=f"{final_node} start",
                    node_id=final_node,
                    request_id=request_id,
                    **({"edge_from": final_edge_from} if final_edge_from else {}),
                )
            )
        self.bus.publish(
            _status_event(
                source="status_log",
                status=final_status,
                message=final_message,
                node_id=final_node,
                request_id=request_id,
                **({"edge_from": final_edge_from} if final_edge_from else {}),
            )
        )

        with self._lock:
            self._active_proc = None
            self._run_state.pop(request_id, None)

    def _consume_stream(self, *, stream: Any, request_id: str, stderr: bool) -> None:
        if stream is None:
            return
        try:
            for raw_line in stream:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                if stderr:
                    self.bus.publish(_text_event(line=line, request_id=request_id, source="stderr"))
                    continue
                self._consume_stdout_line(line=line, request_id=request_id)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _consume_stdout_line(self, *, line: str, request_id: str) -> None:
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            self.bus.publish(_text_event(line=line, request_id=request_id, source="stdout"))
            return
        if not isinstance(loaded, dict):
            self.bus.publish(_text_event(line=line, request_id=request_id, source="stdout"))
            return

        for event in self._map_record(record=loaded, request_id=request_id):
            self.bus.publish(event)

    def _map_record(self, *, record: dict[str, Any], request_id: str) -> list[dict[str, Any]]:
        ts_utc = str(record.get("timestamp") or _utc_now_iso())
        event_name = str(record.get("event", "")).strip()
        message = str(record.get("message", event_name)).strip() or event_name
        level = str(record.get("level", "INFO")).upper()

        def step(
            node_id: str,
            source: str,
            final_status: str,
            final_message: str,
            edge_from: str | None = None,
        ) -> list[dict[str, Any]]:
            return [
                _status_event(
                    source=source,
                    status="start",
                    message=f"{node_id} start",
                    node_id=node_id,
                    request_id=request_id,
                    ts_utc=ts_utc,
                    **({"edge_from": edge_from} if edge_from else {}),
                ),
                _status_event(
                    source=source,
                    status=final_status,
                    message=final_message,
                    node_id=node_id,
                    request_id=request_id,
                    ts_utc=ts_utc,
                    **({"edge_from": edge_from} if edge_from else {}),
                ),
            ]

        if event_name == "config_load_failed":
            config_path = str(record.get("config_path", "")).strip()
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            message_text = f"{error_detail}"
            if config_path:
                message_text = f"{message_text} (config={config_path})"
            self._set_run_value(request_id, "last_error_node", "config_load")
            events: list[dict[str, Any]] = []
            events.extend(step("config_load", "Function load_config", "error", message_text))
            events.extend(step("error", "main.run", "error", message_text, edge_from="config_load"))
            return events

        if event_name in {"imap_search_failed", "imap_connect_failed"}:
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            self._set_run_value(request_id, "last_error_node", "imap_search")
            events: list[dict[str, Any]] = []
            events.extend(step("imap_search", "ImapMailbox.search_uids", "error", error_detail))
            events.extend(step("error", "main.run", "error", error_detail, edge_from="imap_search"))
            return events

        if event_name == "imap_search_start":
            return [
                _status_event(
                    source="ImapMailbox.search_uids",
                    status="start",
                    message="searching unread emails",
                    node_id="imap_search",
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            ]

        if event_name == "imap_fetch_start":
            return [
                _status_event(
                    source="ImapMailbox.fetch_message",
                    status="start",
                    message="fetching email",
                    node_id="imap_fetch",
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            ]

        if event_name == "imap_fetch_ok":
            return [
                _status_event(
                    source="ImapMailbox.fetch_message",
                    status="ok",
                    message="email fetched",
                    node_id="imap_fetch",
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            ]

        if event_name == "extract_record_index":
            index_raw = record.get("index", 0)
            total_raw = record.get("total", 0)
            try:
                index_value = int(index_raw)
            except (TypeError, ValueError):
                index_value = 0
            try:
                total_value = int(total_raw)
            except (TypeError, ValueError):
                total_value = 0
            if index_value <= 0:
                index_value = 1
            display_value = str(index_value)
            if total_value > 0:
                display_value = f"{index_value}/{total_value}"
            return [
                _payload_event(
                    source="extract",
                    key="record_index",
                    value=display_value,
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            ]

        if event_name == "imap_fetch_failed":
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            self._set_run_value(request_id, "last_error_node", "imap_fetch")
            return step("imap_fetch", "ImapMailbox.fetch_message", "error", error_detail)

        if event_name == "extract_ok":
            return step("extract", "extractor.extract_job_email", "ok", "job extracted")

        if event_name == "dedupe_new":
            return step("dedupe", "main.run", "ok", "message id is new")

        if event_name == "dedupe_failed":
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            self._set_run_value(request_id, "last_error_node", "dedupe")
            events: list[dict[str, Any]] = []
            events.extend(step("dedupe", "main.run", "error", error_detail))
            events.extend(step("error", "main.run", "error", error_detail, edge_from="dedupe"))
            return events

        if event_name == "stage_row_failed":
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            self._set_run_value(request_id, "last_error_node", "stage_row")
            events: list[dict[str, Any]] = []
            events.extend(step("stage_row", "main._build_sheet_row", "error", error_detail))
            events.extend(step("error", "main.run", "error", error_detail, edge_from="stage_row"))
            return events

        if event_name == "move_email_failed":
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            self._set_run_value(request_id, "last_error_node", "label_email")
            events: list[dict[str, Any]] = []
            events.extend(step("label_email", "ImapMailbox.remove_inbox_label", "error", error_detail))
            events.extend(step("error", "main.run", "error", error_detail, edge_from="label_email"))
            return events

        if event_name == "run_start":
            self._set_run_flag(request_id, "no_emails_path", False)
            self._set_run_flag(request_id, "last_record_duplicate", False)
            self._set_run_value(request_id, "last_error_node", "")
            self._set_run_value(request_id, "duplicate_count", 0)
            with self._lock:
                state = self._run_state.setdefault(request_id, {})
                state["ai_error_uids"] = set()
            return [
                _status_event(
                    source="Function load_config",
                    status="ok",
                    message="config loaded",
                    node_id="config_load",
                    request_id=request_id,
                    ts_utc=ts_utc,
                ),
                _status_event(
                    source="Function LeadVettingPipeline.run_single_row",
                    status="start",
                    message=f"run_id={record.get('run_id', '')}",
                    node_id="run_job",
                    request_id=request_id,
                    ts_utc=ts_utc,
                ),
            ]

        if event_name == "emails_found":
            count_value_raw = record.get("count", record.get("emails_found", 0))
            try:
                count_value = int(count_value_raw)
            except (TypeError, ValueError):
                count_value = 0
            events: list[dict[str, Any]] = []
            events.append(
                _status_event(
                    source="ImapMailbox.search_uids",
                    status="ok",
                    message=f"emails_found={count_value}",
                    node_id="imap_search",
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            )
            events.append(
                _payload_event(
                    source="imap_fetch",
                    key="emails_found",
                    value=count_value,
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            )
            return events

        if event_name == "no_unread_upwork_emails":
            self._set_run_flag(request_id, "no_emails_path", True)
            events: list[dict[str, Any]] = []
            events.append(
                _status_event(
                    source="main.run",
                    status="ok",
                    message="main completed (no emails path)",
                    node_id="boot",
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            )
            events.extend(step("imap_search", "main.run", "ok", str(record.get("detail", message))))
            events.extend(step("no_emails", "main.run", "ok", "no unread upwork emails"))
            return events

        if event_name == "duplicate_skipped":
            self._set_run_flag(request_id, "last_record_duplicate", True)
            duplicate_count_raw = self._get_run_value(request_id, "duplicate_count", 0)
            try:
                duplicate_count = int(duplicate_count_raw)
            except (TypeError, ValueError):
                duplicate_count = 0
            duplicate_count += 1
            self._set_run_value(request_id, "duplicate_count", duplicate_count)
            events: list[dict[str, Any]] = []
            events.extend(step("dedupe", "main.run", "ok", "duplicate skipped"))
            events.append(
                _payload_event(
                    source="dedupe",
                    key="duplicate_count",
                    value=duplicate_count,
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            )
            for event in events:
                if event.get("node_id") == "dedupe" and event.get("status") == "ok":
                    event["is_duplicate"] = True
            return events

        if event_name in {"ai_accepted", "ai_rejected"}:
            status_name = "ok"
            return step("ai_eval", "ai_eval.evaluate_job", status_name, message)

        if event_name in {"ai_advisory_failed", "ai_evaluation_failed"}:
            uid = str(record.get("uid", "")).strip()
            self._mark_ai_error_uid(request_id, uid)
            self._set_run_value(request_id, "last_error_node", "ai_eval")
            error_detail = str(record.get("error") or message or event_name).strip() or event_name
            return step("ai_eval", "ai_eval.evaluate_job", "error", error_detail)

        if event_name == "staged_for_sheet":
            self._set_run_flag(request_id, "last_record_duplicate", False)
            uid = str(record.get("uid", "")).strip()
            ai_failed = self._has_ai_error_uid(request_id, uid)
            events: list[dict[str, Any]] = []
            if ai_failed:
                self._clear_ai_error_uid(request_id, uid)
                return []
            events.extend(step("stage_row", "main._build_sheet_row", "ok", message))
            return events

        if event_name == "no_new_jobs_to_write":
            return [
                _status_event(
                    source="main.run",
                    status="ok",
                    message="no new jobs to write",
                    node_id="run_job",
                    request_id=request_id,
                    ts_utc=ts_utc,
                )
            ]

        if event_name == "run_end":
            rows_written = int(record.get("rows_written", 0) or 0)
            errors = int(record.get("errors", 0) or 0)
            duplicates_skipped = int(record.get("duplicates_skipped", 0) or 0)
            no_emails_path = self._get_run_flag(request_id, "no_emails_path", False)
            last_record_duplicate = self._get_run_flag(request_id, "last_record_duplicate", False)
            events: list[dict[str, Any]] = [
                _status_event(
                    source="main.run",
                    status="ok",
                    message="run_end",
                    node_id="run_job",
                    request_id=request_id,
                    ts_utc=ts_utc,
                ),
            ]
            if rows_written > 0:
                events.extend(
                    step(
                        "sheet_append",
                        "SheetsClient.append_rows",
                        "ok",
                        f"rows_written={rows_written}",
                    )
                )
                events.extend(
                    step(
                        "label_email",
                        "ImapMailbox.remove_inbox_label",
                        "ok",
                        "labels updated for written rows",
                    )
                )
            summary_keys = [
                "run_id",
                "emails_found",
                "emails_processed",
                "duplicates_skipped",
                "extraction_skipped",
                "ai_advisory_true",
                "ai_advisory_false",
                "ai_advisory_errors",
                "rows_staged",
                "rows_written",
                "errors",
            ]
            for key in summary_keys:
                if key in record:
                    events.append(_payload_event(source="upworks.run_end", key=key, value=record.get(key), request_id=request_id, ts_utc=ts_utc))
            if errors > 0:
                edge_from = str(self._get_run_value(request_id, "last_error_node", "") or "").strip() or None
                events.extend(
                    step(
                        "error",
                        "main.run",
                        "error",
                        f"run completed with errors={errors}",
                        edge_from=edge_from,
                    )
                )
            elif not no_emails_path:
                if last_record_duplicate:
                    events.extend(step("finished", "main.run", "ok", "run completed", edge_from="dedupe"))
                elif rows_written > 0:
                    events.extend(step("complete", "main.run", "ok", "run completed", edge_from="label_email"))
                elif duplicates_skipped > 0:
                    events.extend(step("finished", "main.run", "ok", "run completed", edge_from="dedupe"))
                else:
                    events.extend(step("complete", "main.run", "ok", "run completed"))
            return events

        return [
            _status_event(
                source="upworks.log",
                status="error" if level == "ERROR" else "info",
                message=message,
                node_id="run_job",
                request_id=request_id,
                ts_utc=ts_utc,
            )
        ]


class MonitorHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        static_dir: Path,
        project_root: Path,
        bus: EventBus,
        runner: UpworksRunner,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.static_dir = static_dir
        self.project_root = project_root
        self.bus = bus
        self.runner = runner
        self.shutdown_signal = threading.Event()


class MonitorHandler(BaseHTTPRequestHandler):
    server: MonitorHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/":
            self._serve_static("index.html")
            return
        if route == "/graph":
            self._json_response(GRAPH_DEFINITION)
            return
        if route == "/history":
            self._json_response({"events": self.server.bus.get_history()})
            return
        if route == "/node-code":
            self._node_code_response(parsed.query)
            return
        if route == "/open-in-vscode":
            self._open_in_vscode_response(parsed.query)
            return
        if route == "/events":
            self._stream_events()
            return
        if route.startswith("/") and route != "/":
            self._serve_static(route.lstrip("/"))
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/trigger-run":
            self._trigger_response(cold_start=False)
            return
        if route == "/trigger-cold-run":
            self._trigger_response(cold_start=True)
            return
        self.send_error(404, "Not Found")

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def _serve_static(self, relative_path: str) -> None:
        try:
            path = _resolve_static_path(self.server.static_dir, relative_path)
        except RuntimeError:
            self.send_error(400, "Bad Request")
            return
        if not path.is_file():
            self.send_error(404, "Not Found")
            return

        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json_response(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, error: str) -> None:
        self._json_response({"ok": False, "error": error}, status=status)

    def _read_json_body(self) -> dict[str, Any]:
        content_length_text = self.headers.get("Content-Length", "").strip()
        if not content_length_text:
            return {}
        try:
            content_length = int(content_length_text)
        except ValueError as exc:
            raise RuntimeError("Invalid Content-Length header") from exc
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Request body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("JSON payload must be an object")
        return payload

    def _node_code_response(self, query: str) -> None:
        params = parse_qs(query, keep_blank_values=False)
        node_ids = params.get("node_id", [])
        if not node_ids:
            self._json_error(400, "Missing node_id")
            return
        node_id = str(node_ids[0]).strip()
        if not node_id:
            self._json_error(400, "Empty node_id")
            return
        try:
            payload = _load_node_code(self.server.project_root, node_id)
        except RuntimeError as exc:
            self._json_error(404, str(exc))
            return
        self._json_response(payload)

    def _open_in_vscode_response(self, query: str) -> None:
        params = parse_qs(query, keep_blank_values=False)
        node_ids = params.get("node_id", [])
        if not node_ids:
            self._json_error(400, "Missing node_id")
            return
        node_id = str(node_ids[0]).strip()
        if not node_id:
            self._json_error(400, "Empty node_id")
            return
        try:
            payload = _open_node_in_vscode(self.server.project_root, node_id)
        except RuntimeError as exc:
            self._json_error(500, str(exc))
            return
        self._json_response(payload)

    def _trigger_response(self, *, cold_start: bool) -> None:
        try:
            payload = self._read_json_body()
        except RuntimeError as exc:
            self._json_error(400, str(exc))
            return

        row_raw = payload.get("rowNumber", 2)
        try:
            row_number = int(row_raw)
        except (TypeError, ValueError):
            self._json_error(400, "rowNumber must be an integer >= 2")
            return
        if row_number < 2:
            self._json_error(400, "rowNumber must be an integer >= 2")
            return

        request_id = str(payload.get("requestId", "")).strip() or str(uuid4())
        try:
            response_payload = self.server.runner.trigger(
                request_id=request_id,
                row_number=row_number,
                cold_start=cold_start,
            )
        except RuntimeError as exc:
            self._json_error(409, str(exc))
            return
        self._json_response(response_payload)

    def _stream_events(self) -> None:
        sub = self.server.bus.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            while not self.server.shutdown_signal.is_set():
                try:
                    event = sub.get(timeout=10.0)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=True)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.server.bus.unsubscribe(sub)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upworks flow monitor")
    parser.add_argument(
        "--monitor-feed",
        type=Path,
        default=(Path(__file__).resolve().parent / "monitor_feed.jsonl"),
        help="Path to monitor feed jsonl file",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8791, help="Bind port")
    parser.add_argument("--history-limit", type=int, default=1200, help="Number of events kept in memory")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(r"C:\ChatGPT\shared\Global.json"),
        help="Path to Global.json used by upworks/main.py",
    )
    parser.add_argument(
        "--python-exe",
        type=str,
        default=(sys.executable or "python"),
        help="Python executable used to run main.py",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    monitor_dir = Path(__file__).resolve().parent
    static_dir = (monitor_dir / "static").resolve()
    project_root = monitor_dir.parent.resolve()
    feed_path = args.monitor_feed.expanduser().resolve()
    config_path = args.config.expanduser().resolve()

    if not static_dir.exists() or not static_dir.is_dir():
        raise RuntimeError(f"Missing static directory: {static_dir}")
    if args.port <= 0 or args.port > 65535:
        raise RuntimeError("--port must be between 1 and 65535")
    if args.history_limit <= 0:
        raise RuntimeError("--history-limit must be > 0")

    _validate_graph(static_dir=static_dir, project_root=project_root)

    bus = EventBus(history_limit=args.history_limit, feed_path=feed_path)
    runner = UpworksRunner(
        project_root=project_root,
        config_path=config_path,
        python_exe=str(args.python_exe),
        bus=bus,
    )

    bus.publish(
        _status_event(
            source="status_log",
            status="ok",
            message="upworks monitor initialized",
            node_id="boot",
            request_id="",
        )
    )

    server = MonitorHTTPServer(
        server_address=(str(args.host), int(args.port)),
        request_handler_class=MonitorHandler,
        static_dir=static_dir,
        project_root=project_root,
        bus=bus,
        runner=runner,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "service": "upworks-monitor",
                "listen": f"http://{args.host}:{args.port}/",
                "monitorFeed": str(feed_path),
                "projectRoot": str(project_root),
                "config": str(config_path),
                "pythonExe": str(args.python_exe),
            },
            ensure_ascii=True,
        )
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown_signal.set()
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
