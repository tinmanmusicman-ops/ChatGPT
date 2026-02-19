#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path

WORKFLOW_ID_DEFAULT = "cl0MEdtXKusCB2K0"
NODE_NAME_DEFAULT = "11 extract_text_from_msg + body_contains_sc_marker"


def parse_flatted(text: str):
    table = json.loads(text)
    memo = {}

    def resolve_ref(idx: int):
        if idx in memo:
            return memo[idx]
        raw = table[idx]
        if isinstance(raw, dict):
            obj = {}
            memo[idx] = obj
            for k, v in raw.items():
                key = resolve(v) if isinstance(k, str) and k.isdigit() else k
                obj[key] = resolve(v)
            return obj
        if isinstance(raw, list):
            arr = []
            memo[idx] = arr
            arr.extend(resolve(v) for v in raw)
            return arr
        memo[idx] = raw
        return raw

    def resolve(v):
        if isinstance(v, str) and v.isdigit():
            i = int(v)
            if 0 <= i < len(table):
                return resolve_ref(i)
        if isinstance(v, list):
            return [resolve(x) for x in v]
        if isinstance(v, dict):
            return {k: resolve(val) for k, val in v.items()}
        return v

    return resolve_ref(0)


def get_trace(db_path: Path, workflow_id: str, node_name: str, limit: int):
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute(
        """
        SELECT ee.id, ee.startedAt, ed.data
        FROM execution_entity ee
        JOIN execution_data ed ON ed.executionId = ee.id
        WHERE ee.workflowId = ?
        ORDER BY ee.id DESC
        LIMIT ?
        """,
        (workflow_id, limit),
    )

    for execution_id, started_at, data_raw in cur.fetchall():
        try:
            data = parse_flatted(data_raw)
        except Exception:
            continue

        result_data = data.get("resultData") if isinstance(data, dict) else None
        run_data = result_data.get("runData") if isinstance(result_data, dict) else None
        if not isinstance(run_data, dict):
            continue

        node_runs = run_data.get(node_name)
        if not isinstance(node_runs, list) or not node_runs:
            continue

        first_run = node_runs[0]
        run_main = (first_run.get("data") or {}).get("main") or []
        if not run_main or not run_main[0]:
            continue

        first_item = run_main[0][0]
        payload = first_item.get("json") or {}

        trace = payload.get("debug_trace")
        con.close()
        return {
            "execution_id": execution_id,
            "started_at": started_at,
            "keep": payload.get("keep"),
            "reason": payload.get("reason"),
            "extracted_text": payload.get("extracted_text"),
            "trace": trace,
        }

    con.close()
    return None


def main():
    parser = argparse.ArgumentParser(description="Show latest RegEx debug trace from n8n execution DB")
    parser.add_argument(
        "--db",
        default=r"C:\ChatGPT\ai-bots\UpWork\n8n_data\database.sqlite",
        help="Path to n8n sqlite database",
    )
    parser.add_argument("--workflow-id", default=WORKFLOW_ID_DEFAULT)
    parser.add_argument("--node-name", default=NODE_NAME_DEFAULT)
    parser.add_argument("--scan", type=int, default=50, help="Number of latest executions to scan")
    args = parser.parse_args()

    result = get_trace(Path(args.db), args.workflow_id, args.node_name, args.scan)
    if not result:
        print("No debug trace found in recent executions.")
        print("Run the workflow once, then run this script again.")
        return

    print(f"Execution: {result['execution_id']}  StartedAt: {result['started_at']}")
    print(f"keep={result['keep']}  reason={result['reason']}")
    print(f"extracted_text={result['extracted_text']}")

    trace = result.get("trace")
    if not isinstance(trace, list) or not trace:
        print("debug_trace missing in this execution output.")
        return

    print(f"debug_trace entries: {len(trace)}")
    for entry in trace:
        stage = entry.get("stage")
        print(f"- {stage}: {json.dumps(entry, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
