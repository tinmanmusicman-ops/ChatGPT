import subprocess
import sys
import threading
import time
import os
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, jsonify
from pathlib import Path

# Import stub modules
from modules import (
    job_pipeline,
    fax_engine,
    thermostat,
    security_notify,
    config_manager,
    logger,
    task_scheduler,
)

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"
IMAGES_DIR = BASE_DIR.parent / "Images"
DEFAULT_RESUME_OUTPUT_DIR = Path(r"C:\!!!!!!!!!!!!!!!!!!!!!!!!!Stuff")
BASE_OUTPUT_DIR = Path(os.environ.get("HSST_RESUME_OUTPUT_DIR", str(DEFAULT_RESUME_OUTPUT_DIR)))
BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
AI_BOTS_ROOT = BASE_DIR.parent / "ai-bots"
DASHBOARD_SCRIPT_PATH = AI_BOTS_ROOT / "Thermostats" / "scripts" / "Dashboard.py"


# -------------------------
# Serve the Control Tower UI
# -------------------------
@app.route("/tower")
def tower_ui():
    return send_from_directory(UI_DIR, "index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


# -------------------------
# Serve static files (CSS/JS)
# -------------------------
@app.route("/tower/<path:filename>")
def tower_static(filename):
    return send_from_directory(UI_DIR, filename)


@app.route("/tower/read-log")
def read_log():
    try:
        with open(job_pipeline.LOG_FILE_PATH, encoding="utf-8") as f:
            return jsonify({"text": f.read()})
    except FileNotFoundError:
        return jsonify({"text": ""})


@app.route("/tower/clear-log", methods=["POST"])
def clear_log():
    job_pipeline.LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    job_pipeline.LOG_FILE_PATH.write_text("", encoding="utf-8")
    return jsonify({"status": "cleared"})


@app.route("/Images/<path:filename>")
def shared_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


@app.route("/view/<path:filename>")
def view_file(filename):
    return send_from_directory(BASE_OUTPUT_DIR, filename, mimetype="application/pdf")


# -------------------------
# BUTTON ENDPOINTS (STUB ONLY)
# Each returns a simple JSON message
# -------------------------

@app.route("/tower/import-job")
def import_job():
    job_pipeline.run_import_job()
    return jsonify({"status": "launched"})


@app.route("/tower/scam-check")
def scam_check():
    job_pipeline.run_scam_check()
    return jsonify({"status": "launched"})


@app.route("/tower/verify-company")
def verify_company():
    job_pipeline.run_verify_company()
    return jsonify({"status": "launched"})


@app.route("/tower/jason-configuration")
def jason_configuration():
    job_pipeline.run_jason_configuration()
    return jsonify({"status": "launched"})


@app.route("/tower/facility-check")
def facility_check():
    job_pipeline.run_facility_check()
    return jsonify({"status": "launched"})


@app.route("/tower/enrich-company")
def enrich_company():
    job_pipeline.stub()
    return jsonify({"status": "ok", "action": "enrich_company stub called"})


@app.route("/tower/targeted-resume")
def targeted_resume():
    job_pipeline.run_targeted_resume()
    return jsonify({"status": "launched"})


@app.route("/tower/targeted-resume/variant/<int:variant>")
def targeted_resume_variant_route(variant):
    try:
        job_pipeline.run_targeted_resume_variant(variant)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    return jsonify({"status": "launched", "variant": variant})


@app.route("/tower/yahoo-forwarder")
def yahoo_forwarder():
    job_pipeline.run_yahoo_forwarder()
    return jsonify({"status": "launched"})


@app.route("/tower/craigslist-forwarder")
def craigslist_forwarder():
    # Backward-compatible alias for the renamed YahooForwarder project.
    job_pipeline.run_yahoo_forwarder()
    return jsonify({"status": "launched"})


@app.route("/tower/push-ss")
def push_ss():
    job_pipeline.stub()
    return jsonify({"status": "ok", "action": "push_ss stub called"})


@app.route("/tower/read-thermostat")
def read_thermostat():
    thermostat.stub()
    return jsonify({"status": "ok", "action": "read_thermostat stub called"})


@app.route("/tower/open-dashboard")
def open_dashboard():
    thermostat.stub()
    return jsonify({"status": "ok", "action": "open_dashboard stub called"})


@app.route("/tower/weather-sync")
def weather_sync():
    thermostat.stub()
    return jsonify({"status": "ok", "action": "weather_sync stub called"})


@app.route("/tower/fax-queue")
def fax_queue():
    fax_engine.stub()
    return jsonify({"status": "ok", "action": "fax_queue stub called"})


@app.route("/tower/fax-retry")
def fax_retry():
    fax_engine.stub()
    return jsonify({"status": "ok", "action": "fax_retry stub called"})


@app.route("/tower/fax-log")
def fax_log():
    fax_engine.stub()
    return jsonify({"status": "ok", "action": "fax_log stub called"})


@app.route("/tower/security-notify")
def security_notify_route():
    security_notify.stub()
    return jsonify({"status": "ok", "action": "security_notify stub called"})


@app.route("/tower/security-log")
def security_log():
    security_notify.stub()
    return jsonify({"status": "ok", "action": "security_log stub called"})


@app.route("/tower/config-load")
def config_load():
    config_manager.stub()
    return jsonify({"status": "ok", "action": "config_load stub called"})


@app.route("/tower/config-edit")
def config_edit():
    config_manager.stub()
    return jsonify({"status": "ok", "action": "config_edit stub called"})


@app.route("/tower/config-refresh")
def config_refresh():
    config_manager.stub()
    return jsonify({"status": "ok", "action": "config_refresh stub called"})


@app.route("/tower/stinky-bath")
def stinky_bath():
    logger.stub()
    return jsonify({"status": "ok", "action": "stinky_bath stub called"})


@app.route("/tower/scheduled-tasks")
def scheduled_tasks():
    try:
        return jsonify({"status": "ok", "tasks": task_scheduler.list_hsst_tasks_payload()})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc), "tasks": []}), 500


# -------------------------
# RUN SERVER
# -------------------------
def _seconds_until_next_snapshot() -> float:
    now = datetime.now()
    next_run = now.replace(hour=0, minute=1, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def run_dashboard_snapshot() -> None:
    label = "Nightly Dashboard Snapshot"
    job_pipeline.append_log(f"=== {label} STARTED ===\n")
    try:
        result = subprocess.run(
            [sys.executable, str(DASHBOARD_SCRIPT_PATH)],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            job_pipeline.append_log(result.stdout)
        if result.stderr:
            job_pipeline.append_log(f"[stderr] {result.stderr}")
        if result.returncode != 0:
            raise RuntimeError(
                f"{DASHBOARD_SCRIPT_PATH} exited with {result.returncode}"
            )
    except Exception as exc:
        job_pipeline.append_log(f"=== {label} FAILED ===\n{exc}\n")
    finally:
        job_pipeline.append_log(f"=== {label} FINISHED ===\n")


def schedule_dashboard_snapshot() -> None:
    def worker() -> None:
        while True:
            wait_seconds = _seconds_until_next_snapshot()
            time.sleep(wait_seconds)
            run_dashboard_snapshot()

    threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    schedule_dashboard_snapshot()
    print("HSST Control Tower Flask Server Running (Skeleton Mode)")
    app.run(host="0.0.0.0", port=5000, debug=True)
