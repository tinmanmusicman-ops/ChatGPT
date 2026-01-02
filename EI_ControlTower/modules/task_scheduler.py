import json
import subprocess
from dataclasses import asdict, dataclass


HSST_TASK_DESCRIPTION = "HSST"


@dataclass(frozen=True)
class ScheduledTaskInfo:
    task_name: str
    task_path: str
    state: str | None = None
    author: str | None = None
    description: str | None = None


def list_tasks_with_description(description: str) -> list[ScheduledTaskInfo]:
    escaped_description = description.replace("'", "''")
    ps_script = f"""
$ErrorActionPreference = 'Stop'
Get-ScheduledTask |
  Where-Object {{ $_.Description -eq '{escaped_description}' }} |
  Select-Object TaskName, TaskPath, State, Author, Description |
  ConvertTo-Json -Depth 4
""".strip()

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Failed to query scheduled tasks: {stderr or 'unknown error'}")

    stdout = (result.stdout or "").strip()
    if not stdout:
        return []

    payload = json.loads(stdout)
    if isinstance(payload, dict):
        payload = [payload]

    tasks: list[ScheduledTaskInfo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        tasks.append(
            ScheduledTaskInfo(
                task_name=str(item.get("TaskName", "")).strip(),
                task_path=str(item.get("TaskPath", "")).strip(),
                state=(str(item["State"]).strip() if item.get("State") is not None else None),
                author=(str(item["Author"]).strip() if item.get("Author") is not None else None),
                description=(
                    str(item["Description"]).strip() if item.get("Description") is not None else None
                ),
            )
        )

    return [t for t in tasks if t.task_name and t.task_path]


def list_hsst_tasks() -> list[ScheduledTaskInfo]:
    return list_tasks_with_description(HSST_TASK_DESCRIPTION)


def list_hsst_tasks_payload() -> list[dict]:
    return [asdict(task) for task in list_hsst_tasks()]
