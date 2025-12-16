"""
Job Pipeline Module, Phase C
Streams Python script output for Control Tower job actions directly into the
shared dashboard log instead of relying on batch files.
"""

import subprocess
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_FILE_PATH = REPO_ROOT / "ai-bots" / "Logs" / "dashboard_log.txt"


def append_log(text: str):
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(text)


def run_and_stream(label: str, script_path: str):
    append_log(f"=== {label} STARTED ===\n")

    try:
        process = subprocess.Popen(
            ["python", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
    except Exception as exc:
        append_log(f"=== {label} FAILED ===\n{exc}\n")
        append_log(f"=== {label} FINISHED ===\n")
        return

    def stream_pipe(pipe, prefix: str = ""):
        for line in iter(pipe.readline, ""):
            append_log(f"{prefix}{line}")
        pipe.close()

    def monitor_process():
        stdout_thread = threading.Thread(target=stream_pipe, args=(process.stdout,))
        stderr_thread = threading.Thread(target=stream_pipe, args=(process.stderr, "[stderr] "))
        stdout_thread.start()
        stderr_thread.start()
        stdout_thread.join()
        stderr_thread.join()
        process.wait()
        append_log(f"=== {label} FINISHED ===\n")

    threading.Thread(target=monitor_process, daemon=True).start()


def stub():
    """Legacy stub for endpoints that still rely on placeholder behavior."""
    print("Job pipeline stub invoked.")


def run_import_job():
    run_and_stream(
        "Import Job",
        r"C:\ChatGPT\ai-bots\Jobs\scripts\Indeed.py"
    )

    return {"status": "launched", "script": "Indeed.py"}


def run_scam_check():
    run_and_stream(
        "Scam Check",
        r"C:\ChatGPT\ai-bots\Scams\scripts\IsitScam.py"
    )

    return {"status": "launched", "script": "IsitScam.py"}


def run_verify_company():
    run_and_stream(
        "Verify Company",
        r"C:\ChatGPT\ai-bots\Information\Scripts\Company.py"
    )

    return {"status": "launched", "script": "Company.py"}


def run_jason_configuration():
    run_and_stream(
        "Jason Configuration",
        r"C:\ChatGPT\ai-bots\config-editor\scripts\config_editor.py"
    )

    return {"status": "launched", "script": "config_editor.py"}


def run_facility_check():
    run_and_stream(
        "Facility Check",
        r"C:\ChatGPT\ai-bots\Security\scripts\SiteCheck.py"
    )

    return {"status": "launched", "script": "SiteCheck.py"}


def run_targeted_resume():
    run_and_stream(
        "Targeted Resume",
        r"C:\ChatGPT\ai-bots\Resume\scripts\Resume.py"
    )

    return {"status": "launched", "script": "Resume.py"}
