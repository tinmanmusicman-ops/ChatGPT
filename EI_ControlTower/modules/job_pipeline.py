"""
Job Pipeline Module, Phase C
Streams Python script output for Control Tower job actions directly into the
shared dashboard log instead of relying on batch files.
"""

import subprocess
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_BOTS_ROOT = REPO_ROOT / "ai-bots"
LOG_FILE_PATH = REPO_ROOT / "ai-bots" / "Logs" / "dashboard_log.txt"


def append_log(text: str):
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(text)


def run_and_stream(label: str, script_path: str, args: list[str] | None = None):
    append_log(f"=== {label} STARTED ===\n")

    try:
        command = [sys.executable, "-u", script_path]
        if args:
            command.extend(args)
        process = subprocess.Popen(
            command,
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
        str(AI_BOTS_ROOT / "Jobs" / "scripts" / "Indeed.py")
    )

    return {"status": "launched", "script": "Indeed.py"}


def run_scam_check():
    run_and_stream(
        "Scam Check",
        str(AI_BOTS_ROOT / "Scams" / "scripts" / "IsitScam.py")
    )

    return {"status": "launched", "script": "IsitScam.py"}


def run_verify_company():
    run_and_stream(
        "Verify Company",
        str(AI_BOTS_ROOT / "Information" / "Scripts" / "Company.py")
    )

    return {"status": "launched", "script": "Company.py"}


def run_jason_configuration():
    run_and_stream(
        "Jason Configuration",
        str(AI_BOTS_ROOT / "config-editor" / "scripts" / "config_editor.py")
    )

    return {"status": "launched", "script": "config_editor.py"}


def run_facility_check():
    run_and_stream(
        "Facility Check",
        str(AI_BOTS_ROOT / "Security" / "scripts" / "SiteCheck.py")
    )

    return {"status": "launched", "script": "SiteCheck.py"}


def _launch_tailor_pipeline(label: str, extra_args: list[str] | None = None):
    script_path = str(AI_BOTS_ROOT / "Resume" / "scripts" / "tailor_md_pipeline.py")
    run_and_stream(label, script_path, args=extra_args)
    response = {"status": "launched", "script": "tailor_md_pipeline.py"}
    if extra_args:
        response["args"] = extra_args
    return response


def run_targeted_resume():
    return _launch_tailor_pipeline("Targeted Resume")


def run_targeted_resume_variant(variant: int):
    if variant not in range(1, 6):
        raise ValueError("Resume variant must be between 1 and 5.")
    response = _launch_tailor_pipeline(
        f"Targeted Resume (Variant {variant})",
        extra_args=["--variant", str(variant)],
    )
    response["variant"] = variant
    return response


def run_yahoo_forwarder():
    run_and_stream(
        "Yahoo Forwarder",
        str(AI_BOTS_ROOT / "YahooForwarder" / "scripts" / "yahoo_forwarder.py")
    )

    return {"status": "launched", "script": "yahoo_forwarder.py"}


def run_craigslist_forwarder():
    # Backward-compatible alias for the renamed YahooForwarder project.
    return run_yahoo_forwarder()
