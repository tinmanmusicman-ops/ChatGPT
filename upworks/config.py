from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppConfig:
    gmail_user: str
    gmail_app_password: str
    jobs_raw_query: str
    jobs_allowed_sender_domain: str
    jobs_max_emails_per_run: int
    openai_api_key: str
    openai_model: str
    openai_temperature: float
    openai_timeout_seconds: int
    openai_max_tokens: int
    spreadsheet_id: str
    jobs_worksheet_name: str
    google_message_id_column: str
    service_account_info: dict[str, str]
    prompt_file: Path
    run_lock_file: Path
    log_dir: Path
    mark_email_as_read: bool
    jobs_detail_noise_phrase: str
    jobs_done_label_name: str


def _require_keys(data: dict[str, Any], keys: list[str]) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ConfigError(f"Missing required config keys: {', '.join(missing)}")


def _expect_type(name: str, value: Any, expected: type | tuple[type, ...]) -> None:
    if isinstance(expected, tuple):
        expected_names = ", ".join(t.__name__ for t in expected)
    else:
        expected_names = expected.__name__
    if not isinstance(value, expected):
        raise ConfigError(f"Config key '{name}' must be type {expected_names}")


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config JSON is invalid: {exc}") from exc

    required_keys = [
        "gmail_user",
        "gmail_app_password",
        "openai_api_key",
        "LEADGEN_OPENAI_MODEL",
        "spreadsheet_id",
        "type",
        "project_id",
        "private_key_id",
        "private_key",
        "client_email",
        "client_id",
        "auth_uri",
        "token_uri",
        "auth_provider_x509_cert_url",
        "client_x509_cert_url",
    ]
    _require_keys(data, required_keys)

    _expect_type("gmail_user", data["gmail_user"], str)
    _expect_type("gmail_app_password", data["gmail_app_password"], str)
    _expect_type("openai_api_key", data["openai_api_key"], str)
    if "jobs_ai_model" in data:
        _expect_type("jobs_ai_model", data["jobs_ai_model"], str)
    if "openai_model" in data:
        _expect_type("openai_model", data["openai_model"], str)
    _expect_type("LEADGEN_OPENAI_MODEL", data["LEADGEN_OPENAI_MODEL"], str)
    _expect_type("spreadsheet_id", data["spreadsheet_id"], str)
    _expect_type("type", data["type"], str)
    _expect_type("project_id", data["project_id"], str)
    _expect_type("private_key_id", data["private_key_id"], str)
    _expect_type("private_key", data["private_key"], str)
    _expect_type("client_email", data["client_email"], str)
    _expect_type("client_id", data["client_id"], str)
    _expect_type("auth_uri", data["auth_uri"], str)
    _expect_type("token_uri", data["token_uri"], str)
    _expect_type("auth_provider_x509_cert_url", data["auth_provider_x509_cert_url"], str)
    _expect_type("client_x509_cert_url", data["client_x509_cert_url"], str)

    base_dir = config_path.parent.resolve()
    prompt_file = (base_dir.parent / "upworks" / "prompts" / "upwork_eval_prompt.txt").resolve()
    run_lock_file = (base_dir.parent / "upworks" / "run.lock").resolve()
    log_dir = (base_dir.parent / "upworks" / "logs").resolve()
    if not prompt_file.exists():
        raise ConfigError(f"prompt_file not found: {prompt_file}")

    service_account_info = {
        "type": data["type"].strip(),
        "project_id": data["project_id"].strip(),
        "private_key_id": data["private_key_id"].strip(),
        "private_key": data["private_key"],
        "client_email": data["client_email"].strip(),
        "client_id": data["client_id"].strip(),
        "auth_uri": data["auth_uri"].strip(),
        "token_uri": data["token_uri"].strip(),
        "auth_provider_x509_cert_url": data["auth_provider_x509_cert_url"].strip(),
        "client_x509_cert_url": data["client_x509_cert_url"].strip(),
        "universe_domain": str(data.get("universe_domain", "googleapis.com")).strip(),
    }

    jobs_raw_query = str(
        data.get("jobs_raw_query", "category:primary from:upwork.com is:unread")
    ).strip()
    jobs_allowed_sender_domain = str(data.get("jobs_allowed_sender_domain", "upwork.com")).strip().lower()
    jobs_max_emails_per_run = int(data.get("jobs_max_emails_per_run", 50))
    jobs_done_label_name = str(data.get("jobs_done_label_name", "Upwork")).strip()
    if jobs_max_emails_per_run <= 0:
        raise ConfigError("jobs_max_emails_per_run must be greater than 0")
    if not jobs_done_label_name:
        raise ConfigError("jobs_done_label_name cannot be empty")

    openai_model = str(
        data.get("jobs_ai_model")
        or data.get("openai_model")
        or data.get("LEADGEN_OPENAI_MODEL")
        or "gpt-4o-mini"
    ).strip()
    openai_temperature = float(data.get("jobs_ai_temperature", data.get("openai_temperature", 0.1)))
    openai_timeout_ms = int(data.get("openai_timeout_ms", 45000))
    openai_max_tokens = int(data.get("jobs_ai_max_tokens", data.get("openai_max_tokens", 1200)))
    if not 0 <= openai_temperature <= 2:
        raise ConfigError("openai_temperature/jobs_ai_temperature must be between 0 and 2")
    if openai_timeout_ms <= 0:
        raise ConfigError("openai_timeout_ms must be greater than 0")
    if openai_max_tokens <= 0:
        raise ConfigError("jobs_ai_max_tokens/openai_max_tokens must be greater than 0")

    return AppConfig(
        gmail_user=data["gmail_user"].strip(),
        gmail_app_password=data["gmail_app_password"],
        jobs_raw_query=jobs_raw_query,
        jobs_allowed_sender_domain=jobs_allowed_sender_domain,
        jobs_max_emails_per_run=jobs_max_emails_per_run,
        openai_api_key=data["openai_api_key"].strip(),
        openai_model=openai_model,
        openai_temperature=openai_temperature,
        openai_timeout_seconds=max(1, openai_timeout_ms // 1000),
        openai_max_tokens=openai_max_tokens,
        spreadsheet_id=data["spreadsheet_id"].strip(),
        jobs_worksheet_name=str(data.get("jobs_worksheet_name", "Inbox")).strip(),
        google_message_id_column=str(data.get("jobs_message_id_column", "MessageID")).strip(),
        service_account_info=service_account_info,
        prompt_file=prompt_file,
        run_lock_file=run_lock_file,
        log_dir=log_dir,
        mark_email_as_read=True,
        jobs_detail_noise_phrase=str(
            data.get(
                "jobs_detail_noise_phrase",
                "Check it out, and be one of the first to submit a proposal!",
            )
        ).strip(),
        jobs_done_label_name=jobs_done_label_name,
    )
