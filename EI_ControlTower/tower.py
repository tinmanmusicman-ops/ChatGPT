from flask import Flask, send_from_directory, jsonify
from pathlib import Path

# Import stub modules
from modules import (
    job_pipeline,
    fax_engine,
    thermostat,
    security_notify,
    config_manager,
    logger
)

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "ui"


# -------------------------
# Serve the Control Tower UI
# -------------------------
@app.route("/tower")
def tower_ui():
    return send_from_directory(UI_DIR, "index.html")


# -------------------------
# Serve static files (CSS/JS)
# -------------------------
@app.route("/tower/<path:filename>")
def tower_static(filename):
    return send_from_directory(UI_DIR, filename)


# -------------------------
# BUTTON ENDPOINTS (STUB ONLY)
# Each returns a simple JSON message
# -------------------------

@app.route("/tower/import-job")
def import_job():
    result = job_pipeline.run_import_job()
    return jsonify({
        "status": "ok",
        "action": "import_job executed",
        "result": result
    })


@app.route("/tower/scam-check")
def scam_check():
    result = job_pipeline.run_scam_check()
    return jsonify({
        "status": "ok",
        "action": "scam_check executed",
        "result": result
    })


@app.route("/tower/verify-company")
def verify_company():
    result = job_pipeline.run_verify_company()
    return jsonify({
        "status": "ok",
        "action": "verify_company executed",
        "result": result
    })


@app.route("/tower/enrich-company")
def enrich_company():
    job_pipeline.stub()
    return jsonify({"status": "ok", "action": "enrich_company stub called"})


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


# -------------------------
# RUN SERVER
# -------------------------
if __name__ == "__main__":
    print("HSST Control Tower Flask Server Running (Skeleton Mode)")
    app.run(host="0.0.0.0", port=5000, debug=True)
