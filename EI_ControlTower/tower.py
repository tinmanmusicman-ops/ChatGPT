import subprocess
import sys
import threading
import time
import os
import json
import re
import smtplib
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, jsonify, request, redirect
import requests
from pathlib import Path
from email.message import EmailMessage
from email.utils import formatdate
from typing import Optional

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
FIT_SITE_DIR = BASE_DIR.parent / "AI-Fit-Site"
DEFAULT_RESUME_OUTPUT_DIR = Path(r"C:\!!!!!!!!!!!!!!!!!!!!!!!!!Stuff")
BASE_OUTPUT_DIR = Path(os.environ.get("HSST_RESUME_OUTPUT_DIR", str(DEFAULT_RESUME_OUTPUT_DIR)))
BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
AI_BOTS_ROOT = BASE_DIR.parent / "ai-bots"
DASHBOARD_SCRIPT_PATH = AI_BOTS_ROOT / "Thermostats" / "scripts" / "Dashboard.py"
THERMOSTATS_WEB_DIR = AI_BOTS_ROOT / "Thermostats" / "Web"
GLOBAL_CONFIG_PATH = Path(
    os.environ.get("HSST_GLOBAL_CONFIG", str(AI_BOTS_ROOT / "shared" / "Global.json"))
)

DEFAULT_CORS_ORIGINS = {
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:80",
    "http://127.0.0.1:80",
}


def _allowed_origins():
    allowed = set(DEFAULT_CORS_ORIGINS)
    extra = os.environ.get("HSST_TOWER_ALLOWED_ORIGINS", "")
    for item in extra.split(","):
        item = item.strip()
        if item:
            allowed.add(item)
    return allowed


def _with_cors(resp):
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return resp

    allowed = _allowed_origins()
    if origin in allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def _append_cores_log(message: str):
    CORES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    entry = f"{timestamp} {message}\n"
    try:
        with open(CORES_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(entry)
    except Exception:
        pass

CORES_DIR = BASE_DIR.parent / "CORES"
CORES_LOG_PATH = CORES_DIR / "cores.log"


# -------------------------
# Serve the Control Tower UI
# -------------------------
@app.route("/", strict_slashes=False)
def root():
    _maybe_notify_fit_site_visit(page="/")
    return redirect("/tower", code=302)


@app.route("/tower", strict_slashes=False)
def tower_ui():
    _maybe_notify_fit_site_visit(page="/tower")
    return send_from_directory(UI_DIR, "index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


_global_config_cache = None
_global_config_mtime = None


def _load_global_config() -> dict:
    global _global_config_cache, _global_config_mtime

    try:
        stat = GLOBAL_CONFIG_PATH.stat()
    except FileNotFoundError:
        return {}

    if _global_config_cache is not None and _global_config_mtime == stat.st_mtime:
        return _global_config_cache or {}

    try:
        data = json.loads(GLOBAL_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    _global_config_cache = data or {}
    _global_config_mtime = stat.st_mtime
    return _global_config_cache


def _send_gmail_message(*, to_address: str, subject: str, body: str, reply_to: Optional[str] = None) -> None:
    cfg = _load_global_config()
    gmail_user = (os.environ.get("GMAIL_USER") or cfg.get("gmail_user") or "").strip()
    gmail_app_password = (os.environ.get("GMAIL_APP_PASSWORD") or cfg.get("gmail_app_password") or "").strip()

    if not gmail_user or not gmail_app_password:
        raise RuntimeError("Missing Gmail credentials (GMAIL_USER/GMAIL_APP_PASSWORD or Global.json keys)")

    safe_subject = re.sub(r"[\r\n]+", " ", subject or "").strip()[:220] or "Contact request"

    msg = EmailMessage()
    msg["From"] = gmail_user
    msg["To"] = to_address
    msg["Subject"] = safe_subject
    msg["Date"] = formatdate(localtime=True)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body or "")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(gmail_user, gmail_app_password)
        smtp.send_message(msg)


def _looks_like_email(value: str) -> bool:
    s = (value or "").strip()
    if not s or len(s) > 254:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s))


_contact_last_sent_at = {}
_visit_last_notified_at = {}


# -------------------------
# Serve the AI-Fit-Site static page(s)
# -------------------------
@app.route("/AI-Fit-Site", strict_slashes=False)
def fit_site_index():
    _maybe_notify_fit_site_visit(page="Job.html")
    return send_from_directory(FIT_SITE_DIR, "Job.html")


@app.route("/AI-Fit-Site/<path:filename>")
def fit_site_static(filename):
    if str(filename or "").strip().lower() == "job.html":
        _maybe_notify_fit_site_visit(page="Job.html")
    return send_from_directory(FIT_SITE_DIR, filename)


def _is_obvious_bot_user_agent(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return False
    bot_markers = (
        "bot",
        "spider",
        "crawler",
        "slurp",
        "headless",
        "preview",
        "pingdom",
        "uptimerobot",
        "httpclient",
        "python-requests",
        "curl",
        "wget",
    )
    return any(marker in ua for marker in bot_markers)


def _maybe_notify_fit_site_visit(*, page: str) -> None:
    enabled = os.environ.get("HSST_VISIT_NOTIFY", "1").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        return

    ip = (request.remote_addr or "").strip() or "unknown"
    ua = (request.headers.get("User-Agent", "") or "").strip()
    if _is_obvious_bot_user_agent(ua):
        return

    now = time.time()
    last = _visit_last_notified_at.get(ip)
    if last is not None and now - last < 6 * 60 * 60:
        return

    # Set before sending to avoid races on parallel requests.
    _visit_last_notified_at[ip] = now

    to_address = os.environ.get("HSST_VISIT_NOTIFY_TO", "timinman2024@gmail.com").strip()
    subject = f"AI-Fit-Site visit: {page}"
    referer = (request.headers.get("Referer", "") or "").strip()
    origin = (request.headers.get("Origin", "") or "").strip()
    path = (request.full_path or request.path or "").strip()

    body = (
        "AI-Fit-Site visit detected\n\n"
        f"Time: {datetime.now().isoformat(timespec='seconds')}\n"
        f"Page: {page}\n"
        f"Path: {path}\n"
        f"Remote: {ip}\n"
        f"Origin: {origin}\n"
        f"Referer: {referer}\n"
        f"User-Agent: {ua}\n"
    )

    if os.environ.get("HSST_VISIT_NOTIFY_DRY_RUN", "").strip() == "1":
        return

    def worker() -> None:
        try:
            _send_gmail_message(to_address=to_address, subject=subject, body=body)
            try:
                job_pipeline.append_log(
                    "=== VISIT NOTIFY SENT ===\n"
                    f"time: {datetime.now().isoformat(timespec='seconds')}\n"
                    f"page: {page}\n"
                    f"remote: {ip}\n"
                )
            except Exception:
                pass
        except Exception as exc:
            # Don't break page load if email fails.
            try:
                job_pipeline.append_log(
                    "=== VISIT NOTIFY FAILED ===\n"
                    f"time: {datetime.now().isoformat(timespec='seconds')}\n"
                    f"page: {page}\n"
                    f"remote: {ip}\n"
                    f"error: {exc}\n"
                )
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()

# -------------------------
# Serve selected ai-bots web assets
# -------------------------
@app.route("/ai-bots/Thermostats/Web/dashboard_public.html", strict_slashes=False)
def thermostat_dashboard_public():
    return send_from_directory(THERMOSTATS_WEB_DIR, "dashboard_public.html")


@app.route("/ai-bots/Thermostats/Web/<path:filename>")
def thermostats_web_assets(filename):
    return send_from_directory(THERMOSTATS_WEB_DIR, filename)


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


def _build_prompt(
    question: str,
    history: str,
    job_description: str = "",
    skills: str = "",
    supplemental_context: str = "",
    mode: str = "summary",
) -> str:
    job_description = (job_description or "").strip()
    history = (history or "").strip()
    skills = (skills or "").strip()
    supplemental_context = (supplemental_context or "").strip()
    question = (question or "").strip()
    mode = (mode or "summary").strip().lower()

    skills_block = f"\n\nSelf-rated skills:\n{skills}\n" if skills else ""
    supplemental_block = (
        f"\n\nSupplemental context (candidate-provided):\n{supplemental_context}\n"
        if supplemental_context
        else ""
    )

    detail_instruction = ""
    if mode == "deep":
        detail_instruction = (
            "\n\nDepth mode: DEEP\n"
            "- Provide a thorough, multi-angle analysis.\n"
            "- Use more bullets, more specifics, and more evidence.\n"
            "- Prefer concrete examples (projects, metrics, tools, workflows).\n"
        )

    if job_description:
        return (
            "You are a candid, skeptical career evaluator. Do not be flattering.\n"
            "Rules:\n"
            "- Only claim skills/experience that are supported by the work history OR explicitly listed in the self-rated skills OR described in the supplemental context.\n"
            "- If a skill is only in the self-rated skills (not in work history), label it as self-rated.\n"
            "- If a claim is only supported by the supplemental context (not work history), label it as candidate-provided.\n"
            "- If the job is unrelated to the work history, say so plainly.\n"
            "- Prefer \"No\" or \"Maybe\" over a false \"Yes\".\n"
            "- Tie every positive claim to explicit evidence from the work history when possible.\n\n"
            "Important:\n"
            "- Before writing the answer, scan the supplemental context for any lines that look like project headers (e.g., starting with \"Project:\").\n"
            "- Use those project names verbatim when relevant (example: \"TileAir / DocOrigin Replacement Initiative\").\n\n"
            "Task:\n"
            "Evaluate whether the candidate is a good fit for the job description below.\n"
            "Return Markdown with this exact structure:\n"
            "## Fit Verdict\n"
            "- Verdict: Yes/Maybe/No\n"
            "- Confidence: 0-100\n"
            "## Evidence From Work History\n"
            "- (3-8 bullets) Each bullet must reference something from the work history.\n"
            "## Relevant Projects\n"
            "- (5-12 bullets) Include specific projects/initiatives; prefer exact names from the supplemental context when available.\n"
            "- Each bullet must end with a support tag: (work history) or (candidate-provided) or (self-rated).\n"
            "## Gaps / Risks\n"
            "- (3-8 bullets)\n"
            "## Interview Positioning\n"
            "- (3-8 bullets)\n\n"
            f"{detail_instruction}\n"
            "Job description:\n"
            f"{job_description}\n\n"
            "Work history:\n"
            f"{history}{skills_block}{supplemental_block}\n"
            f"Question: {question}"
        )

    return (
        "You are a helpful but honest career advisor.\n"
        "Rules:\n"
        "- Only claim skills/experience that are supported by the work history OR explicitly listed in the self-rated skills OR described in the supplemental context.\n"
        "- If a skill is only in the self-rated skills (not in work history), label it as self-rated.\n"
        "- If a claim is only supported by the supplemental context (not work history), label it as candidate-provided.\n"
        "- If you don't know, say so.\n\n"
        "Use the work history, self-rated skills, and supplemental context below to answer the user's question. "
        "Focus on automation, reliability, and human-led systems.\n"
        "If the user explicitly requests a single sentence, comply.\n"
        "Otherwise, provide at least three supporting points.\n\n"
        f"{detail_instruction}\n"
        "Work history:\n"
        f"{history}{skills_block}{supplemental_block}\n"
        f"Question: {question}"
    )


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/tower/contact", methods=["OPTIONS", "POST"])
def tower_contact():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(force=True, silent=True) or {}
    website = (payload.get("website") or "").strip()
    name = (payload.get("name") or "").strip()
    contact = (payload.get("contact") or "").strip()
    message = (payload.get("message") or "").strip()
    page_url = (payload.get("pageUrl") or "").strip()

    # Honeypot for bots (humans won't see/fill this).
    if website:
        return jsonify({"status": "ok"})

    ip = (request.remote_addr or "").strip() or "unknown"
    now = time.time()
    last = _contact_last_sent_at.get(ip)
    if last is not None and now - last < 30:
        return jsonify({"error": "Too many requests. Try again shortly."}), 429

    if not contact:
        return jsonify({"error": "Contact info is required"}), 400

    if len(name) > 120:
        name = name[:120]
    if len(contact) > 220:
        contact = contact[:220]
    if len(message) > 5000:
        message = message[:5000]
    if len(page_url) > 1000:
        page_url = page_url[:1000]

    to_address = os.environ.get("HSST_CONTACT_TO", "timinman2024@gmail.com").strip()
    reply_to = contact if _looks_like_email(contact) else None

    subject_hint = name or contact
    subject = f"AI-Fit-Site contact: {subject_hint}".strip()

    body_lines = [
        "New contact request from AI-Fit-Site",
        "",
        f"Time: {datetime.now().isoformat(timespec='seconds')}",
        f"From (provided): {name or '(no name)'}",
        f"Contact (provided): {contact}",
        f"Page: {page_url}" if page_url else "",
        "",
        "Message:",
        message or "(no message)",
        "",
        f"Remote: {request.remote_addr}",
        f"Origin: {request.headers.get('Origin', '').strip()}",
        f"User-Agent: {request.headers.get('User-Agent', '').strip()}",
    ]
    body = "\n".join(body_lines).strip() + "\n"

    if os.environ.get("HSST_CONTACT_DRY_RUN", "").strip() == "1":
        _contact_last_sent_at[ip] = now
        return jsonify({"status": "ok", "dryRun": True})

    try:
        _send_gmail_message(to_address=to_address, subject=subject, body=body, reply_to=reply_to)
    except Exception as exc:
        return jsonify({"error": "Failed to send email", "details": str(exc)}), 500

    _contact_last_sent_at[ip] = now
    return jsonify({"status": "ok"})


@app.route("/tower/ask-ai", methods=["OPTIONS", "POST"])
def ask_ai():
    if request.method == "OPTIONS":
        resp = app.make_response(("", 204))
        return _with_cors(resp)

    payload = request.get_json(force=True, silent=True) or {}
    question = (payload.get("question") or "").strip()
    mode = (payload.get("mode") or "summary").strip().lower()
    history = payload.get("history", "").strip()
    skills = payload.get("skills", "").strip()
    supplemental_context = payload.get("supplementalContext", "").strip()
    job_description = (payload.get("jobDescription") or "").strip()

    if mode not in {"summary", "deep"}:
        mode = "summary"

    job_pipeline.append_log(
        "=== Ask AI REQUEST ===\n"
        f"time: {datetime.now().isoformat(timespec='seconds')}\n"
        f"remote: {request.remote_addr}\n"
        f"origin: {request.headers.get('Origin', '')}\n"
        f"ua: {request.headers.get('User-Agent', '')}\n"
        f"mode: {mode}\n"
        f"question_preview: {question[:160].replace(chr(10), ' ')!r}\n"
        f"history_chars: {len(history)}\n"
        f"skills_chars: {len(skills)}\n"
        f"supplemental_chars: {len(supplemental_context)}\n"
        f"job_desc_chars: {len(job_description)}\n"
    )
    if not question:
        job_pipeline.append_log("=== Ask AI ERROR ===\nerror: missing question\n")
        return _with_cors(app.make_response((jsonify({"error": "Question is required"}), 400)))

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        job_pipeline.append_log("=== Ask AI ERROR ===\nerror: OPENAI_API_KEY missing\n")
        return _with_cors(
            app.make_response(
                (
                    jsonify(
                        {
                            "error": "OPENAI_API_KEY is missing. Set it in the environment before running tower.",
                        }
                    ),
                    500,
                )
            )
        )

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    prompt = _build_prompt(question, history, job_description, skills, supplemental_context, mode)
    max_tokens = 950 if mode == "summary" else 1600
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai_key}",
            },
            json={
                "model": model,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a career advisor who must be honest, specific, and evidence-based. "
                            "Do not overstate fit or invent experience."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        if response.status_code >= 400:
            job_pipeline.append_log(
                "=== Ask AI ERROR ===\n"
                f"error: OpenAI request failed ({response.status_code})\n"
                f"details_preview: {response.text[:600]!r}\n"
            )
            return _with_cors(
                app.make_response(
                    (
                        jsonify(
                            {
                                "error": "OpenAI request failed",
                                "details": response.text,
                            }
                        ),
                        response.status_code,
                    )
                )
            )

        data = response.json()
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        job_pipeline.append_log(
            "=== Ask AI RESPONSE ===\n"
            f"answer_chars: {len(answer)}\n"
        )
        return _with_cors(app.make_response(jsonify({"answer": answer or "OpenAI returned an empty response."})))
    except requests.RequestException as exc:
        job_pipeline.append_log(
            "=== Ask AI ERROR ===\n"
            f"error: Proxy request failed\n"
            f"details: {str(exc)!r}\n"
        )
        return _with_cors(
            app.make_response((jsonify({"error": "Proxy request failed", "details": str(exc)}), 503))
        )


@app.route("/cores/log", methods=["OPTIONS", "POST"])
def cores_log():
    if request.method == "OPTIONS":
        resp = app.make_response(("", 204))
        return _with_cors(resp)

    payload = request.get_json(force=True, silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return _with_cors(
            app.make_response(
                (
                    jsonify({"error": "Message is required"}),
                    400,
                )
            )
        )

    _append_cores_log(message)
    return _with_cors(jsonify({"status": "ok"}))

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
