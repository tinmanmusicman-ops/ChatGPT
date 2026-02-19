#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import mimetypes
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from uuid import uuid4


GRAPH_DEFINITION: dict[str, Any] = {
    "node_types": [
        {"id": "code", "label": "Code", "image": "/Images/Code.png"},
        {"id": "ss", "label": "SS", "image": "/Images/SS.png"},
        {"id": "ai", "label": "AI", "image": "/Images/AI.png"},
        {"id": "scrape", "label": "Scrape", "image": "/Images/Scrape.png"},
        {"id": "gmail", "label": "Gmail", "image": "/Images/gmail.png"},
        {"id": "if", "label": "If", "image": "/Images/If.png"},
        {"id": "sched", "label": "Sched", "image": "/Images/Sched.png"},
        {"id": "trig", "label": "Trig", "image": "/Images/Trig.png"},
    ],
    "nodes": [
        {
            "id": "boot",
            "label": "boot",
            "summary": "Marks monitor startup and status log initialization.",
            "activity_type": "code",
            "x": 120,
            "y": 70,
            "code_source": "run_leadgen.py",
            "code_preview": (
                "initialize_status_log(\n"
                "    script_dir / \"status.log\",\n"
                "    script_dir / \"monitor_feed.jsonl\",\n"
                ")\n"
                "_init_runtime_log(runtime_log_path)"
            ),
        },
        {
            "id": "args",
            "label": "parse args",
            "summary": "Parses mode, row input, and webhook runtime options.",
            "activity_type": "code",
            "x": 205,
            "y": 70,
            "code_source": "run_leadgen.py",
            "code_preview": (
                "parser.add_argument(\"--mode\", choices=[\"single\", \"webhook\"], default=\"single\")\n"
                "parser.add_argument(\"--row-number\", type=int, default=0)\n"
                "parser.add_argument(\"--payload-file\", type=str, default=\"\")\n"
                "parser.add_argument(\"--host\", type=str, default=\"127.0.0.1\")\n"
                "parser.add_argument(\"--port\", type=int, default=8787)\n"
                "return parser.parse_args()"
            ),
        },
        {
            "id": "env",
            "label": "load env",
            "summary": "Loads .env variables into the process environment.",
            "activity_type": "code",
            "x": 290,
            "y": 70,
            "code_source": "run_leadgen.py",
            "code_preview": (
                "for raw_line in dotenv_path.read_text(encoding=\"utf-8\").splitlines():\n"
                "    line = raw_line.strip()\n"
                "    if not line or line.startswith(\"#\"):\n"
                "        continue\n"
                "    key, value = line.split(\"=\", 1)\n"
                "    if key not in os.environ:\n"
                "        os.environ[key] = value"
            ),
        },
        {
            "id": "global",
            "label": "load global",
            "summary": "Loads Global.json and injects required keys into env.",
            "activity_type": "code",
            "x": 375,
            "y": 70,
            "code_source": "run_leadgen.py",
            "code_preview": (
                "global_path = _resolve_global_json_path(script_dir)\n"
                "global_cfg = _read_global_json(global_path)\n"
                "_set_env_if_missing(\"OPENAI_API_KEY\", _first_nonempty(global_cfg, (...)))\n"
                "_set_env_if_missing(\"LEADGEN_GOOGLE_SHEET_ID\", _first_nonempty(global_cfg, (...)))\n"
                "if not os.getenv(\"LEADGEN_GOOGLE_CREDENTIALS_FILE\", \"\").strip():\n"
                "    os.environ[\"LEADGEN_GOOGLE_CREDENTIALS_FILE\"] = str(_materialize_service_account_from_global(...))"
            ),
        },
        {
            "id": "webhook_handler",
            "label": "webhook POST",
            "summary": "Receives webhook payload and validates request body.",
            "activity_type": "code",
            "x": 460,
            "y": 70,
            "code_source": "run_leadgen.py",
            "code_preview": (
                "payload = _read_json_body(self)\n"
                "row_number, request_id = _extract_payload_fields(payload)\n"
                "result = pipeline.run_single_row(row_number=row_number, request_id=request_id)\n"
                "_json_response(self, 200, {\n"
                "    \"ok\": result.ok,\n"
                "    \"status\": result.status,\n"
                "    \"updatedRanges\": result.updated_ranges,\n"
                "})"
            ),
        },
        {
            "id": "run_single",
            "label": "run row",
            "summary": "Runs lead vetting pipeline for one spreadsheet row.",
            "activity_type": "code",
            "x": 545,
            "y": 70,
            "code_source": "run_leadgen.py",
            "code_preview": (
                "row_number, request_id = _resolve_inputs(args)\n"
                "result = pipeline.run_single_row(row_number=row_number, request_id=request_id)\n"
                "print(json.dumps({\n"
                "    \"ok\": result.ok,\n"
                "    \"rowNumber\": result.row_number,\n"
                "    \"status\": result.status,\n"
                "}, ensure_ascii=True))"
            ),
        },
        {
            "id": "sheet_read",
            "label": "sheet read",
            "summary": "Reads the target lead row from Google Sheets.",
            "activity_type": "ss",
            "x": 630,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "raw_row = self.sheets.read_row(row_number)\n"
                "self.logger.event(\"sheet_row_read\", row_number=row_number, request_id=effective_request_id)\n"
                "log_event(\"LeadVettingPipeline.sheet\", \"ok\", \"row read\")"
            ),
        },
        {
            "id": "normalize",
            "label": "normalize",
            "summary": "Normalizes row fields into pipeline input format.",
            "activity_type": "code",
            "x": 715,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "normalized = normalize_row(\n"
                "    raw=raw_row,\n"
                "    row_number=row_number,\n"
                "    request_id=effective_request_id,\n"
                "    sheet_id=self.config.google_sheet_id,\n"
                "    sheet_tab=self.config.google_sheet_tab,\n"
                ")\n"
                "context = dict(normalized)"
            ),
        },
        {
            "id": "website_resolve",
            "label": "website",
            "summary": "Discovers or verifies the best website for the lead.",
            "activity_type": "ai",
            "x": 800,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "if not context[\"final_website\"]:\n"
                "    discovered = self.openai.discover_website(\n"
                "        company=normalized[\"company_name\"],\n"
                "        industry=normalized[\"industry\"],\n"
                "        country=normalized[\"country\"],\n"
                "    )\n"
                "    context[\"final_website\"] = discovered\n"
                "    context[\"website_source\"] = \"ai_discovered\""
            ),
        },
        {
            "id": "firecrawl_scrape",
            "label": "scrape",
            "summary": "Scrapes website content for context and enrichment.",
            "activity_type": "scrape",
            "x": 885,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "scraped = self.firecrawl.scrape_markdown(context[\"final_website\"])\n"
                "self.logger.event(\"website_scraped\", scraped_chars=len(scraped))\n"
                "log_event(\"LeadVettingPipeline.website_scraped\", \"ok\", f\"chars={len(scraped)}\")\n"
                "log_event(\"LeadVettingPipeline.scrape_preview\", \"info\", f\"{scraped[:60].replace('\\\\n', ' ')}\")"
            ),
        },
        {
            "id": "prompt_build",
            "label": "build prompt",
            "summary": "Builds the model prompt from row data and scrape data.",
            "activity_type": "code",
            "x": 970,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "prompt = build_prompt_context(\n"
                "    company_name=normalized[\"company_name\"],\n"
                "    final_website=context[\"final_website\"],\n"
                "    industry=normalized[\"industry\"],\n"
                "    country=normalized[\"country\"],\n"
                "    notes=normalized[\"notes\"],\n"
                "    scraped_text=scraped,\n"
                ")"
            ),
        },
        {
            "id": "ai_evaluate",
            "label": "AI eval",
            "summary": "Calls the AI model to evaluate lead fit and output fields.",
            "activity_type": "ai",
            "x": 1055,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "ai_response = self.openai.evaluate(\n"
                "    prompt_system=prompt[\"prompt_system\"],\n"
                "    prompt_user=prompt[\"prompt_user\"],\n"
                ")\n"
                "response_text = ai_response if isinstance(ai_response, str) else json.dumps(ai_response)\n"
                "log_event(\"LeadVettingPipeline.openai\", \"ok\", f\"evaluate len={len(response_text.strip())}\")"
            ),
        },
        {
            "id": "decision_parse",
            "label": "decision",
            "summary": "Parses AI output into structured decision payload.",
            "activity_type": "code",
            "x": 1140,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "decision = parse_and_validate_ai_json(\n"
                "    openai_response=ai_response,\n"
                "    manual_review_threshold=self.config.manual_review_threshold,\n"
                "    website_source=context[\"website_source\"],\n"
                ")\n"
                "log_event(\"LeadVettingPipeline.decision\", \"info\", f\"manual_review={decision['manual_review']}\")"
            ),
        },
        {
            "id": "sheet_update",
            "label": "sheet update",
            "summary": "Writes final decision and enrichment values to Sheets.",
            "activity_type": "ss",
            "x": 1225,
            "y": 70,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "update_payload = self._compose_success_update(context, decision)\n"
                "_log_json_pairs(\"LeadVettingPipeline.sheet_update_payload\", update_payload)\n"
                "update_result = self.sheets.update_row_columns(row_number, update_payload)\n"
                "_log_json_pairs(\"LeadVettingPipeline.sheet_update_result\", update_result)\n"
                "\n"
                "error_payload = self._compose_error_update(...)\n"
                "_log_json_pairs(\"LeadVettingPipeline.sheet_update_payload\", error_payload)\n"
                "update_result = self.sheets.update_row_columns(row_number, error_payload)\n"
                "_log_json_pairs(\"LeadVettingPipeline.sheet_update_result\", update_result)"
            ),
        },
        {
            "id": "complete",
            "label": "success",
            "summary": "Represents successful completion for the current row.",
            "activity_type": "code",
            "x": 1310,
            "y": 45,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "return PipelineResult(\n"
                "    ok=True,\n"
                "    row_number=row_number,\n"
                "    status=update_payload[\"status\"],\n"
                "    request_id=effective_request_id,\n"
                "    updated_ranges=update_result[\"updated_keys\"],\n"
                "    ignored_keys=update_result[\"ignored_keys\"],\n"
                ")"
            ),
        },
        {
            "id": "error",
            "label": "error",
            "summary": "Represents pipeline or write failure for the current row.",
            "activity_type": "code",
            "x": 1310,
            "y": 110,
            "code_source": "leadgen/pipeline.py",
            "code_preview": (
                "error_payload = self._compose_error_update(\n"
                "    request_id=effective_request_id,\n"
                "    code=exc.code,\n"
                "    message=exc.message,\n"
                "    final_website=context.get(\"final_website\", \"\"),\n"
                ")\n"
                "update_result = self.sheets.update_row_columns(row_number, error_payload)\n"
                "return PipelineResult(ok=False, row_number=row_number, status=\"ERROR\", request_id=effective_request_id, ...)"
            ),
        },
    ],
    "edges": [
        {"source": "boot", "target": "args"},
        {"source": "args", "target": "env"},
        {"source": "env", "target": "global"},
        {"source": "global", "target": "webhook_handler"},
        {"source": "webhook_handler", "target": "run_single"},
        {"source": "run_single", "target": "sheet_read"},
        {"source": "sheet_read", "target": "normalize"},
        {"source": "normalize", "target": "website_resolve"},
        {"source": "website_resolve", "target": "firecrawl_scrape"},
        {"source": "firecrawl_scrape", "target": "prompt_build"},
        {"source": "prompt_build", "target": "ai_evaluate"},
        {"source": "ai_evaluate", "target": "decision_parse"},
        {"source": "decision_parse", "target": "sheet_update"},
        {"source": "sheet_update", "target": "complete"},
        {"source": "sheet_update", "target": "error"},
    ],
    "pipeline_reset_nodes": [
        "run_single",
        "sheet_read",
        "normalize",
        "website_resolve",
        "firecrawl_scrape",
        "prompt_build",
        "ai_evaluate",
        "decision_parse",
        "sheet_update",
        "complete",
        "error",
    ],
}

NODE_CODE_SYMBOL_PATHS: dict[str, list[str]] = {
    "boot": ["main"],
    "args": ["_parse_args"],
    "env": ["_load_env_file"],
    "global": ["_load_hsst_global_into_env"],
    "webhook_handler": ["_run_webhook_mode", "Handler", "do_POST"],
    "run_single": ["_run_single_mode"],
    "sheet_read": ["LeadVettingPipeline", "run_single_row"],
    "normalize": ["LeadVettingPipeline", "run_single_row"],
    "website_resolve": ["LeadVettingPipeline", "run_single_row"],
    "firecrawl_scrape": ["LeadVettingPipeline", "run_single_row"],
    "prompt_build": ["LeadVettingPipeline", "run_single_row"],
    "ai_evaluate": ["LeadVettingPipeline", "run_single_row"],
    "decision_parse": ["LeadVettingPipeline", "run_single_row"],
    "sheet_update": ["LeadVettingPipeline", "run_single_row"],
    "complete": ["LeadVettingPipeline", "run_single_row"],
    "error": ["LeadVettingPipeline", "run_single_row"],
}

NODE_CODE_SECTION_MARKERS: dict[str, dict[str, Any]] = {
    "sheet_read": {
        "start": "raw_row = self.sheets.read_row(row_number)",
        "end": "normalized = normalize_row(",
    },
    "normalize": {
        "start": "normalized = normalize_row(",
        "end": "if not context[\"final_website\"]:",
    },
    "website_resolve": {
        "start": "if not context[\"final_website\"]:",
        "end": "scraped = self.firecrawl.scrape_markdown(",
    },
    "firecrawl_scrape": {
        "start": "scraped = self.firecrawl.scrape_markdown(",
        "end": "prompt = build_prompt_context(",
    },
    "prompt_build": {
        "start": "prompt = build_prompt_context(",
        "end": "ai_response = self.openai.evaluate(",
    },
    "ai_evaluate": {
        "start": "ai_response = self.openai.evaluate(",
        "end": "decision = parse_and_validate_ai_json(",
    },
    "decision_parse": {
        "start": "decision = parse_and_validate_ai_json(",
        "end": "update_payload = self._compose_success_update(context, decision)",
    },
    "sheet_update": {
        "start": "update_payload = self._compose_success_update(context, decision)",
        "end": "with indent_context():",
    },
    "complete": {
        "start": "return PipelineResult(",
        "end": "except LeadGenError as exc:",
    },
    "error": {
        "start": "except LeadGenError as exc:",
    },
}


def _find_graph_node(node_id: str) -> dict[str, Any] | None:
    nodes = GRAPH_DEFINITION.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id", "")).strip() == node_id:
            return node
    return None


def _find_symbol_node_in_body(body: list[ast.stmt], symbol_path: list[str]) -> ast.AST | None:
    if not symbol_path:
        return None
    name = symbol_path[0]
    target: ast.AST | None = None
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and stmt.name == name:
            target = stmt
            break
    if target is None:
        return None
    if len(symbol_path) == 1:
        return target
    if not isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return None
    return _find_symbol_node_in_body(target.body, symbol_path[1:])


def _extract_symbol_source(file_path: Path, symbol_path: list[str]) -> tuple[str, int]:
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"Code source file not found: {file_path}")
    source_text = file_path.read_text(encoding="utf-8")
    parsed = ast.parse(source_text, filename=str(file_path))
    node = _find_symbol_node_in_body(parsed.body, symbol_path)
    if node is None:
        raise RuntimeError(f"Symbol path not found in {file_path}: {'/'.join(symbol_path)}")
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        raise RuntimeError(f"Symbol node missing line metadata in {file_path}: {'/'.join(symbol_path)}")

    start_line = int(getattr(node, "lineno"))
    end_line = int(getattr(node, "end_lineno"))
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        start_line = min(start_line, min(int(getattr(decorator, "lineno", start_line)) for decorator in decorators))
    lines = source_text.splitlines()
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise RuntimeError(f"Symbol line range invalid in {file_path}: {'/'.join(symbol_path)}")
    return "\n".join(lines[start_line - 1 : end_line]) + "\n", start_line


def _extract_node_section_source(node_id: str, symbol_source: str) -> tuple[str, int]:
    markers = NODE_CODE_SECTION_MARKERS.get(node_id)
    if markers is None:
        return symbol_source, 1
    start_marker = str(markers.get("start", "")).strip()
    if not start_marker:
        raise RuntimeError(f"Node {node_id} section marker missing start")
    end_marker = str(markers.get("end", "")).strip()

    lines = symbol_source.splitlines()
    start_idx = -1
    for idx, line in enumerate(lines):
        if start_marker in line:
            start_idx = idx
            break
    if start_idx < 0:
        raise RuntimeError(f"Node {node_id} section start marker not found: {start_marker}")

    end_idx = len(lines)
    if end_marker:
        found_end = -1
        for idx in range(start_idx + 1, len(lines)):
            if end_marker in lines[idx]:
                found_end = idx
                break
        if found_end < 0:
            raise RuntimeError(f"Node {node_id} section end marker not found: {end_marker}")
        end_idx = found_end

    section = lines[start_idx:end_idx]
    if not section:
        raise RuntimeError(f"Node {node_id} section markers produced empty source")
    return "\n".join(section).strip("\n") + "\n", start_idx + 1


def _load_node_code_payload(project_root: Path, node_id: str) -> dict[str, Any]:
    node = _find_graph_node(node_id)
    if node is None:
        raise RuntimeError(f"Unknown node_id: {node_id}")
    code_source = str(node.get("code_source", "")).strip()
    if not code_source:
        raise RuntimeError(f"Node {node_id} missing code_source")
    symbol_path = NODE_CODE_SYMBOL_PATHS.get(node_id)
    if not symbol_path:
        raise RuntimeError(f"Node {node_id} missing symbol mapping")
    source_path = (project_root / code_source).resolve()
    expected_root = project_root.resolve()
    if expected_root not in source_path.parents and source_path != expected_root:
        raise RuntimeError(f"Code source escapes project root: {code_source}")
    symbol_source, symbol_start_line = _extract_symbol_source(source_path, symbol_path)
    source_text, section_start_line = _extract_node_section_source(node_id=node_id, symbol_source=symbol_source)
    absolute_start_line = symbol_start_line + section_start_line - 1
    return {
        "ok": True,
        "node_id": node_id,
        "code_source": code_source,
        "code_path": str(source_path),
        "code_symbol": ".".join(symbol_path),
        "code_line_start": absolute_start_line,
        "code": source_text,
    }


def _open_node_in_vscode(project_root: Path, node_id: str) -> dict[str, Any]:
    payload = _load_node_code_payload(project_root=project_root, node_id=node_id)
    code_cli = shutil.which("code")
    if not code_cli:
        raise RuntimeError("VS Code CLI not found on PATH (expected 'code').")
    target = f"{payload['code_path']}:{payload['code_line_start']}"
    try:
        subprocess.Popen([code_cli, "-g", target], cwd=str(project_root))
    except Exception as exc:
        raise RuntimeError(f"Failed to launch VS Code: {exc}") from exc
    return {
        "ok": True,
        "node_id": node_id,
        "target": target,
    }


def _post_webhook_request(webhook_url: str, outbound_payload: dict[str, Any], timeout_sec: float) -> tuple[int, dict[str, Any]]:
    request_bytes = json.dumps(outbound_payload, ensure_ascii=True).encode("utf-8")
    request = Request(
        webhook_url,
        data=request_bytes,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Webhook HTTP error: {exc.code} {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Webhook connection error: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(f"Webhook trigger failed: {exc}") from exc

    try:
        webhook_payload = json.loads(response_body) if response_body.strip() else {}
    except json.JSONDecodeError:
        webhook_payload = {"raw": response_body}
    return status, webhook_payload


def _parse_webhook_url_components(webhook_url: str) -> tuple[str, str, int, str]:
    parsed = urlparse(webhook_url)
    scheme = str(parsed.scheme).strip().lower()
    host = str(parsed.hostname or "").strip()
    if scheme not in {"http", "https"}:
        raise RuntimeError(f"Unsupported webhook URL scheme: {scheme}")
    if not host:
        raise RuntimeError("Webhook URL missing host")
    port = int(parsed.port or (443 if scheme == "https" else 80))
    path = str(parsed.path or "/").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return scheme, host, port, path


def _list_listening_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["netstat", "-ano"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Unable to query listeners with netstat -ano")
    pids: set[int] = set()
    marker = f":{port}"
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if marker not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pid_text = parts[-1].strip()
        if pid_text.isdigit():
            pids.add(int(pid_text))
    return sorted(pids)


def _kill_pid(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        check=False,
        capture_output=True,
        text=True,
    )


def _wait_for_health(health_url: str, timeout_sec: float, poll_sec: float = 0.7) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        request = Request(health_url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=2) as response:
                if int(getattr(response, "status", 200)) < 500:
                    return
        except Exception:
            time.sleep(poll_sec)
            continue
    raise RuntimeError("webhook health endpoint never responded")


def _trigger_cold_start_run(
    project_root: Path,
    monitor_dir: Path,
    webhook_url: str,
    row_number: int,
    request_id: str,
    health_timeout_sec: float,
) -> dict[str, Any]:
    scheme, host, port, path = _parse_webhook_url_components(webhook_url)
    if scheme != "http":
        raise RuntimeError("Cold start trigger currently supports http webhook URLs only")

    pids = _list_listening_pids(port)
    for pid in pids:
        _kill_pid(pid)

    python_exe = sys.executable or shutil.which("python")
    if not python_exe:
        raise RuntimeError("Python executable not found for cold start")

    boot_out = (monitor_dir / "last_webhook_boot.log").resolve()
    boot_err = (monitor_dir / "last_webhook_boot.err.log").resolve()
    out_handle = boot_out.open("w", encoding="utf-8")
    err_handle = boot_err.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [
                str(python_exe),
                "run_webhook.py",
                "--host",
                host,
                "--port",
                str(port),
                "--path",
                path,
            ],
            cwd=str(project_root),
            stdout=out_handle,
            stderr=err_handle,
            text=True,
        )
    finally:
        out_handle.close()
        err_handle.close()

    health_url = f"{scheme}://{host}:{port}/health"
    try:
        _wait_for_health(health_url=health_url, timeout_sec=health_timeout_sec)
    except Exception as exc:
        if proc.poll() is not None:
            raise RuntimeError(f"webhook exited early. see: {boot_err}") from exc
        raise

    outbound_payload = {"rowNumber": row_number, "requestId": request_id}
    status, webhook_payload = _post_webhook_request(
        webhook_url=webhook_url,
        outbound_payload=outbound_payload,
        timeout_sec=60,
    )
    response_path = (monitor_dir / "last_webhook_response.json").resolve()
    response_path.write_text(json.dumps(webhook_payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "triggered": {
            "webhook_url": webhook_url,
            "rowNumber": row_number,
            "requestId": request_id,
            "mode": "cold_start",
        },
        "killed_pids": pids,
        "webhook_status": status,
        "webhook_response": webhook_payload,
        "boot_logs": {
            "stdout": str(boot_out),
            "stderr": str(boot_err),
            "response": str(response_path),
            "webhook_pid": proc.pid,
        },
    }


def map_event_to_node(source: str, status: str, message: str) -> str | None:
    if source == "status_log":
        return "boot"
    if source == "Function main":
        return "boot"
    if source == "Function _parse_args":
        return "args"
    if source == "Function _load_env_file":
        return "env"
    if source == "Function _load_hsst_global_into_env":
        return "global"
    if source == "Function _run_single_mode":
        return "run_single"
    if source == "Function _run_webhook_mode":
        return "webhook_handler"
    if source in {"Function Handler.do_POST", "Function Handler.do_GET"}:
        return "webhook_handler"
    if source == "Function LeadVettingPipeline.run_single_row":
        if status == "error":
            return "error"
        return "run_single"
    if source in {"LeadVettingPipeline.sheet", "LeadVettingPipeline.raw_row"}:
        return "sheet_read"
    if source == "LeadVettingPipeline.normalized":
        return "normalize"
    if source in {"LeadVettingPipeline.website", "LeadVettingPipeline.openai_discovery_payload"}:
        return "website_resolve"
    if source == "LeadVettingPipeline.openai":
        lowered = message.lower()
        if "discover_website" in lowered or "discover=" in lowered:
            return "website_resolve"
        if "evaluate" in lowered:
            return "ai_evaluate"
    if source in {"LeadVettingPipeline.website_scraped", "LeadVettingPipeline.scrape_preview"}:
        return "firecrawl_scrape"
    if source == "LeadVettingPipeline.prompt":
        return "prompt_build"
    if source in {"LeadVettingPipeline.ai_response_payload", "LeadVettingPipeline.ai_response"}:
        return "ai_evaluate"
    if source == "LeadVettingPipeline.decision":
        return "decision_parse"
    if source.startswith("LeadVettingPipeline.sheet_update"):
        return "sheet_update"
    if source == "LeadVettingPipeline.sheet_updated_success":
        return "complete"
    if source == "LeadVettingPipeline.sheet_updated_error":
        return "error"
    return None


class EventBus:
    def __init__(self, history_limit: int) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._event_id = 0

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._event_id += 1
            payload = dict(event)
            payload["event_id"] = self._event_id
            self._history.append(payload)
            subscribers = list(self._subscribers)
        for sub in subscribers:
            try:
                sub.put_nowait(payload)
            except queue.Full:
                continue

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        sub: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    def get_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)


class MonitorFeedTailer(threading.Thread):
    def __init__(self, monitor_feed_path: Path, bus: EventBus, poll_interval: float = 0.2) -> None:
        super().__init__(name="monitor-feed-tailer", daemon=True)
        self.monitor_feed_path = monitor_feed_path
        self.bus = bus
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.monitor_feed_path.parent.mkdir(parents=True, exist_ok=True)
        self.monitor_feed_path.touch(exist_ok=True)
        offset = self.monitor_feed_path.stat().st_size
        while not self._stop_event.is_set():
            current_size = self.monitor_feed_path.stat().st_size
            if current_size < offset:
                offset = 0
            if current_size == offset:
                time.sleep(self.poll_interval)
                continue
            with self.monitor_feed_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            for raw_line in chunk.splitlines():
                parsed = self._parse_line(raw_line.rstrip("\r\n"))
                if parsed is not None:
                    self.bus.publish(parsed)

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        if not line:
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return {"kind": "text", "raw_line": line}
        if not isinstance(event, dict):
            return {"kind": "text", "raw_line": line}
        source = str(event.get("source", ""))
        status = str(event.get("status", ""))
        message = str(event.get("message", ""))
        if not event.get("node_id"):
            event["node_id"] = map_event_to_node(source=source, status=status, message=message)
        kind = str(event.get("kind", "text"))
        if kind == "status" and "ts" not in event:
            event["ts"] = _format_short_ts(str(event.get("ts_utc", "")))
        if "raw_line" not in event:
            if kind == "payload_pair":
                event["raw_line"] = f"{event.get('key', '')}={event.get('value', '')}"
            else:
                event["raw_line"] = message
        return event


def _format_short_ts(ts_utc: str) -> str:
    if not ts_utc:
        return ""
    try:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.strftime("%H:%M:%S.%f")[:-3]


def _resolve_static_relative_path(static_dir: Path, relative_path: str) -> Path:
    relative = relative_path.lstrip("/")
    candidate = (static_dir / relative).resolve()
    if static_dir not in candidate.parents and candidate != static_dir:
        raise RuntimeError(f"Static path escapes static dir: {relative_path}")
    return candidate


def _validate_graph_definition(static_dir: Path) -> None:
    node_types = GRAPH_DEFINITION.get("node_types")
    if not isinstance(node_types, list) or not node_types:
        raise RuntimeError("GRAPH_DEFINITION.node_types must be a non-empty list")

    valid_type_ids: set[str] = set()
    for item in node_types:
        if not isinstance(item, dict):
            raise RuntimeError("GRAPH_DEFINITION.node_types entries must be objects")
        type_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        image = str(item.get("image", "")).strip()
        if not type_id or not label or not image:
            raise RuntimeError("Each node type must define id, label, and image")
        if type_id in valid_type_ids:
            raise RuntimeError(f"Duplicate node type id: {type_id}")
        image_path = _resolve_static_relative_path(static_dir, image)
        if not image_path.exists() or not image_path.is_file():
            raise RuntimeError(f"Missing node type image file: {image_path}")
        valid_type_ids.add(type_id)

    nodes = GRAPH_DEFINITION.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError("GRAPH_DEFINITION.nodes must be a non-empty list")
    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise RuntimeError("GRAPH_DEFINITION.nodes entries must be objects")
        node_id = str(node.get("id", "")).strip()
        activity_type = str(node.get("activity_type", "")).strip()
        summary = str(node.get("summary", "")).strip()
        code_source = str(node.get("code_source", "")).strip()
        code_preview = str(node.get("code_preview", "")).strip()
        if not node_id:
            raise RuntimeError("Each node must define id")
        if node_id in node_ids:
            raise RuntimeError(f"Duplicate node id: {node_id}")
        if activity_type not in valid_type_ids:
            raise RuntimeError(f"Node {node_id} has unknown activity_type: {activity_type}")
        if not summary:
            raise RuntimeError(f"Node {node_id} missing summary")
        if not code_source:
            raise RuntimeError(f"Node {node_id} missing code_source")
        if not code_preview:
            raise RuntimeError(f"Node {node_id} missing code_preview")
        _load_node_code_payload(project_root=static_dir.parent.parent.resolve(), node_id=node_id)
        node_ids.add(node_id)

    edges = GRAPH_DEFINITION.get("edges")
    if not isinstance(edges, list):
        raise RuntimeError("GRAPH_DEFINITION.edges must be a list")
    for edge in edges:
        if not isinstance(edge, dict):
            raise RuntimeError("GRAPH_DEFINITION.edges entries must be objects")
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source not in node_ids:
            raise RuntimeError(f"Edge source node not found: {source}")
        if target not in node_ids:
            raise RuntimeError(f"Edge target node not found: {target}")

    reset_nodes = GRAPH_DEFINITION.get("pipeline_reset_nodes")
    if not isinstance(reset_nodes, list):
        raise RuntimeError("GRAPH_DEFINITION.pipeline_reset_nodes must be a list")
    for node_id in reset_nodes:
        if str(node_id) not in node_ids:
            raise RuntimeError(f"Reset node not found: {node_id}")


class MonitorHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        static_dir: Path,
        monitor_dir: Path,
        project_root: Path,
        webhook_url: str,
        default_row_number: int,
        webhook_health_timeout_sec: float,
        bus: EventBus,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.static_dir = static_dir
        self.monitor_dir = monitor_dir
        self.project_root = project_root
        self.webhook_url = webhook_url
        self.default_row_number = default_row_number
        self.webhook_health_timeout_sec = webhook_health_timeout_sec
        self.bus = bus
        self.shutdown_signal = threading.Event()


class MonitorHandler(BaseHTTPRequestHandler):
    server: MonitorHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/":
            self._serve_static_path("index.html")
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
            self._serve_static_path(route.lstrip("/"))
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/trigger-run":
            self._trigger_run_response()
            return
        if route == "/trigger-cold-run":
            self._trigger_cold_run_response()
            return
        self.send_error(404, "Not Found")

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def _serve_static_path(self, relative_path: str) -> None:
        try:
            path = _resolve_static_relative_path(self.server.static_dir, relative_path)
        except RuntimeError:
            self.send_error(400, "Bad Request")
            return
        if not path.is_file():
            self.send_error(404, "Not Found")
            return
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        header_content_type = content_type
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            header_content_type = f"{content_type}; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", header_content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json_response(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps({"ok": False, "error": message}, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            payload = _load_node_code_payload(project_root=self.server.project_root, node_id=node_id)
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
            payload = _open_node_in_vscode(project_root=self.server.project_root, node_id=node_id)
        except RuntimeError as exc:
            self._json_error(500, str(exc))
            return
        self._json_response(payload)

    def _read_json_request_body(self) -> dict[str, Any]:
        content_length_raw = self.headers.get("Content-Length", "").strip()
        if not content_length_raw:
            return {}
        try:
            content_length = int(content_length_raw)
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

    def _trigger_run_response(self) -> None:
        try:
            payload = self._read_json_request_body()
        except RuntimeError as exc:
            self._json_error(400, str(exc))
            return

        row_raw = payload.get("rowNumber", self.server.default_row_number)
        try:
            row_number = int(row_raw)
        except (TypeError, ValueError):
            self._json_error(400, "rowNumber must be an integer >= 2")
            return
        if row_number < 2:
            self._json_error(400, "rowNumber must be an integer >= 2")
            return

        request_id_raw = payload.get("requestId", "")
        request_id = str(request_id_raw).strip() if request_id_raw is not None else ""
        if not request_id:
            request_id = str(uuid4())

        outbound_payload = {"rowNumber": row_number, "requestId": request_id}
        try:
            status, webhook_payload = _post_webhook_request(
                webhook_url=self.server.webhook_url,
                outbound_payload=outbound_payload,
                timeout_sec=60,
            )
        except RuntimeError as exc:
            self._json_error(502, str(exc))
            return

        response_payload: dict[str, Any] = {
            "ok": True,
            "triggered": {
                "webhook_url": self.server.webhook_url,
                "rowNumber": row_number,
                "requestId": request_id,
            },
            "webhook_status": status,
            "webhook_response": webhook_payload,
        }
        self._json_response(response_payload)

    def _trigger_cold_run_response(self) -> None:
        try:
            payload = self._read_json_request_body()
        except RuntimeError as exc:
            self._json_error(400, str(exc))
            return

        row_raw = payload.get("rowNumber", self.server.default_row_number)
        try:
            row_number = int(row_raw)
        except (TypeError, ValueError):
            self._json_error(400, "rowNumber must be an integer >= 2")
            return
        if row_number < 2:
            self._json_error(400, "rowNumber must be an integer >= 2")
            return

        request_id_raw = payload.get("requestId", "")
        request_id = str(request_id_raw).strip() if request_id_raw is not None else ""
        if not request_id:
            request_id = str(uuid4())

        try:
            response_payload = _trigger_cold_start_run(
                project_root=self.server.project_root,
                monitor_dir=self.server.monitor_dir,
                webhook_url=self.server.webhook_url,
                row_number=row_number,
                request_id=request_id,
                health_timeout_sec=self.server.webhook_health_timeout_sec,
            )
        except RuntimeError as exc:
            self._json_error(500, str(exc))
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
                payload = json.dumps(event, ensure_ascii=True)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            self.server.bus.unsubscribe(sub)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LeadGen flow monitor (monitor feed visualizer)")
    parser.add_argument(
        "--monitor-feed",
        type=Path,
        default=(Path(__file__).resolve().parent.parent / "monitor_feed.jsonl"),
        help="Path to monitor feed jsonl file",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8790, help="Bind port")
    parser.add_argument("--history-limit", type=int, default=1000, help="Number of events kept in memory")
    parser.add_argument(
        "--webhook-url",
        default="http://127.0.0.1:8787/webhook/lead-vetting-prod",
        help="Webhook URL to trigger a run from the monitor UI",
    )
    parser.add_argument(
        "--default-row-number",
        type=int,
        default=2,
        help="Default row number used by the Run Job button",
    )
    parser.add_argument(
        "--webhook-health-timeout-sec",
        type=float,
        default=25.0,
        help="Seconds to wait for webhook health during cold start trigger",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    monitor_feed_path = args.monitor_feed.expanduser().resolve()
    monitor_dir = Path(__file__).resolve().parent
    static_dir = (monitor_dir / "static").resolve()
    project_root = (monitor_dir.parent).resolve()
    if not static_dir.exists():
        raise RuntimeError(f"Missing static directory: {static_dir}")
    if args.default_row_number < 2:
        raise RuntimeError("--default-row-number must be >= 2")
    if float(args.webhook_health_timeout_sec) <= 0:
        raise RuntimeError("--webhook-health-timeout-sec must be > 0")
    _validate_graph_definition(static_dir)

    bus = EventBus(history_limit=args.history_limit)
    tailer = MonitorFeedTailer(monitor_feed_path=monitor_feed_path, bus=bus)
    tailer.start()

    server = MonitorHTTPServer(
        server_address=(args.host, args.port),
        request_handler_class=MonitorHandler,
        static_dir=static_dir,
        monitor_dir=monitor_dir.resolve(),
        project_root=project_root,
        webhook_url=str(args.webhook_url).strip(),
        default_row_number=int(args.default_row_number),
        webhook_health_timeout_sec=float(args.webhook_health_timeout_sec),
        bus=bus,
    )

    print(
        json.dumps(
            {
                "ok": True,
                "service": "leadgen-monitor",
                "listen": f"http://{args.host}:{args.port}/",
                "monitorFeed": str(monitor_feed_path),
                "webhookUrl": str(args.webhook_url).strip(),
                "defaultRowNumber": int(args.default_row_number),
                "webhookHealthTimeoutSec": float(args.webhook_health_timeout_sec),
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
        tailer.stop()
        tailer.join(timeout=2.0)
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
