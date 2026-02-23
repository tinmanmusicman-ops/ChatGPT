from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from openai import OpenAI

from ai_eval import AIError, evaluate_job, load_prompt_template
from config import AppConfig, ConfigError, load_config
from extractor import extract_job_email
from logging_json import log_event, setup_logger
from mail_imap import ImapError, ImapMailbox
from sheets import SheetsClient, SheetsError


@contextmanager
def run_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        lock_file.seek(0)
        if lock_file.tell() == 0:
            lock_file.write("0")
            lock_file.flush()
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another run is active. Lock file: {lock_path}") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upwork email -> AI -> Google Sheets workflow runner",
    )
    parser.add_argument(
        "--config",
        default=r"C:\ChatGPT\shared\Global.json",
        help="Path to Global.json file",
    )
    return parser.parse_args()


def _preload_log_dir(config_path: Path) -> Path:
    base_dir = config_path.parent.resolve()
    return (base_dir.parent / "upworks" / "logs").resolve()


def _build_sheet_row(
    timestamp_utc: str,
    message_id: str,
    job_url: str,
    job_description: str,
    job_description_note: str,
    price: str,
    price_note: str,
    do_bid: str,
    score: str,
) -> dict[str, str]:
    return {
        "timestamp": timestamp_utc,
        "message_id": message_id,
        "job_url": job_url,
        "job_description": job_description,
        "job_description_note": job_description_note,
        "price": price,
        "price_note": price_note,
        "ai_decision": do_bid,
        "score": score,
        "source": "upworks-python",
    }


def _extract_sheet_fields(description_text: str, fallback_url: str) -> tuple[str, str, str]:
    text = (description_text or "").strip()
    job_description = text
    job_url = fallback_url
    price = ""

    try:
        right = text.split("---------- ", 1)[1]
        job_description = right.split("... more:", 1)[0].strip() or text
    except Exception:
        job_description = text

    try:
        more_right = text.split("... more:", 1)[1].strip()
        parts = more_right.split(" ")
        if len(parts) > 1 and parts[1].strip():
            job_url = parts[1].strip()
    except Exception:
        pass

    try:
        more_right = text.split("... more:", 1)[1].strip()
        price = " ".join(more_right.split(" ")[1:]).split("http", 1)[0].strip()
    except Exception:
        match = re.search(r"\$\s?\d[\d,]*(?:\s*-\s*\$\s?\d[\d,]*)?", job_description)
        if match:
            price = match.group(0).strip()

    # Guardrail: keep URL a real URL, otherwise fall back.
    parsed = urlparse(job_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        job_url = fallback_url

    # Guardrail: keep useful description, otherwise fall back.
    if len(job_description.strip()) < 20:
        job_description = text

    return job_description, job_url, price


def _format_score(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def run(config: AppConfig) -> int:
    logger = setup_logger(config.log_dir)
    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "run_id": run_id,
        "emails_found": 0,
        "emails_processed": 0,
        "duplicates_skipped": 0,
        "extraction_skipped": 0,
        "ai_advisory_true": 0,
        "ai_advisory_false": 0,
        "ai_advisory_errors": 0,
        "rows_staged": 0,
        "rows_written": 0,
        "errors": 0,
    }

    log_event(logger, logging.INFO, "run_start", run_id=run_id)
    prompt_template = load_prompt_template(config.prompt_file)

    with run_lock(config.run_lock_file):
        sheets_client = SheetsClient(
            service_account_info=config.service_account_info,
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.jobs_worksheet_name,
            message_id_column=config.google_message_id_column,
        )
        existing_message_ids = sheets_client.get_existing_message_ids()
        run_seen_ids: set[str] = set()
        rows_to_append: list[dict[str, str]] = []
        accepted_uid_by_message_id: dict[str, str] = {}
        ai_client = OpenAI(api_key=config.openai_api_key, timeout=config.openai_timeout_seconds)

        with ImapMailbox(
            host="imap.gmail.com",
            port=993,
            user=config.gmail_user,
            password=config.gmail_app_password,
            mailbox="INBOX",
        ) as mailbox:
            if config.mark_email_as_read:
                mailbox.ensure_label_exists(config.jobs_done_label_name)
            try:
                log_event(logger, logging.INFO, "imap_search_start", query=config.jobs_raw_query)
                uids = mailbox.search_uids(
                    search_criteria=config.jobs_raw_query,
                    max_results=config.jobs_max_emails_per_run,
                )
            except ImapError as exc:
                summary["errors"] += 1
                log_event(
                    logger,
                    logging.ERROR,
                    "imap_search_failed",
                    query=config.jobs_raw_query,
                    error=str(exc),
                )
                log_event(logger, logging.INFO, "run_end", **summary)
                return 1
            summary["emails_found"] = len(uids)
            log_event(logger, logging.INFO, "emails_found", count=summary["emails_found"])

            if not uids:
                log_event(logger, logging.INFO, "no_unread_upwork_emails", detail="No unread Upwork emails")
                log_event(logger, logging.INFO, "run_end", **summary)
                return 0

            for record_index, uid in enumerate(uids, start=1):
                summary["emails_processed"] += 1
                try:
                    log_event(logger, logging.INFO, "imap_fetch_start", uid=uid)
                    message = mailbox.fetch_message(uid)
                except ImapError as exc:
                    summary["errors"] += 1
                    log_event(logger, logging.ERROR, "imap_fetch_failed", uid=uid, error=str(exc))
                    continue
                log_event(logger, logging.INFO, "imap_fetch_ok", uid=uid)
                log_event(
                    logger,
                    logging.INFO,
                    "extract_record_index",
                    uid=uid,
                    index=record_index,
                    total=len(uids),
                )

                extracted, extract_error = extract_job_email(
                    imap_uid=uid,
                    message=message,
                    allowed_sender_domain=config.jobs_allowed_sender_domain,
                    detail_noise_phrase=config.jobs_detail_noise_phrase,
                )
                if extracted is None:
                    summary["extraction_skipped"] += 1
                    log_event(
                        logger,
                        logging.WARNING,
                        "extraction_skipped",
                        uid=uid,
                        reason=extract_error,
                    )
                    continue
                log_event(
                    logger,
                    logging.INFO,
                    "extract_ok",
                    uid=uid,
                    message_id=extracted.message_id,
                )

                try:
                    is_duplicate = extracted.message_id in existing_message_ids or extracted.message_id in run_seen_ids
                except Exception as exc:
                    summary["errors"] += 1
                    log_event(
                        logger,
                        logging.ERROR,
                        "dedupe_failed",
                        uid=uid,
                        message_id=getattr(extracted, "message_id", ""),
                        error=str(exc),
                    )
                    continue

                if is_duplicate:
                    summary["duplicates_skipped"] += 1
                    log_event(
                        logger,
                        logging.INFO,
                        "duplicate_skipped",
                        uid=uid,
                        message_id=extracted.message_id,
                        detail="Duplicate - already processed",
                    )
                    if config.mark_email_as_read:
                        try:
                            mailbox.add_label(uid, config.jobs_done_label_name)
                            mailbox.remove_inbox_label(uid)
                            mailbox.mark_as_read(uid)
                        except ImapError as exc:
                            summary["errors"] += 1
                            log_event(
                                logger,
                                logging.ERROR,
                                "move_email_failed",
                                uid=uid,
                                message_id=extracted.message_id,
                                error=str(exc),
                            )
                    continue
                log_event(
                    logger,
                    logging.INFO,
                    "dedupe_new",
                    uid=uid,
                    message_id=extracted.message_id,
                )

                parsed_desc, parsed_url, parsed_price = _extract_sheet_fields(
                    description_text=extracted.job_description,
                    fallback_url=extracted.job_url,
                )

                do_bid = "REVIEW"
                score = ""
                try:
                    decision = evaluate_job(
                        client=ai_client,
                        prompt_template=prompt_template,
                        model=config.openai_model,
                        temperature=config.openai_temperature,
                        timeout_seconds=config.openai_timeout_seconds,
                        max_tokens=config.openai_max_tokens,
                        job_email=extracted,
                    )
                    do_bid = "TRUE" if decision.should_pursue else "FALSE"
                    score = _format_score(decision.total_score)
                    if decision.should_pursue:
                        summary["ai_advisory_true"] += 1
                        log_event(
                            logger,
                            logging.INFO,
                            "ai_accepted",
                            uid=uid,
                            message_id=extracted.message_id,
                        )
                    else:
                        summary["ai_advisory_false"] += 1
                        log_event(
                            logger,
                            logging.INFO,
                            "ai_rejected",
                            uid=uid,
                            message_id=extracted.message_id,
                        )
                except AIError as exc:
                    summary["ai_advisory_errors"] += 1
                    summary["errors"] += 1
                    log_event(
                        logger,
                        logging.ERROR,
                        "ai_advisory_failed",
                        uid=uid,
                        message_id=extracted.message_id,
                        error=str(exc),
                    )
                    log_event(logger, logging.INFO, "run_end", **summary)
                    return 1

                try:
                    row = _build_sheet_row(
                        timestamp_utc=extracted.timestamp_utc,
                        message_id=extracted.message_id,
                        job_url=parsed_url,
                        job_description=parsed_desc,
                        job_description_note=extracted.job_description,
                        price=parsed_price,
                        price_note=parsed_price,
                        do_bid=do_bid,
                        score=score,
                    )
                except Exception as exc:
                    summary["errors"] += 1
                    log_event(
                        logger,
                        logging.ERROR,
                        "stage_row_failed",
                        uid=uid,
                        message_id=extracted.message_id,
                        error=str(exc),
                    )
                    continue
                rows_to_append.append(row)
                run_seen_ids.add(extracted.message_id)
                accepted_uid_by_message_id[extracted.message_id] = uid
                summary["rows_staged"] += 1

                log_event(
                    logger,
                    logging.INFO,
                    "staged_for_sheet",
                    uid=uid,
                    message_id=extracted.message_id,
                )

            if rows_to_append:
                sheets_client.append_rows(rows_to_append)
                summary["rows_written"] = len(rows_to_append)
                if config.mark_email_as_read:
                    for row in rows_to_append:
                        row_message_id = row["message_id"]
                        uid = accepted_uid_by_message_id.get(row_message_id)
                        if not uid:
                            raise RuntimeError(f"Accepted row missing uid for message id {row_message_id}")
                        try:
                            mailbox.add_label(uid, config.jobs_done_label_name)
                            mailbox.remove_inbox_label(uid)
                            mailbox.mark_as_read(uid)
                        except ImapError as exc:
                            summary["errors"] += 1
                            log_event(
                                logger,
                                logging.ERROR,
                                "move_email_failed",
                                uid=uid,
                                message_id=row_message_id,
                                error=str(exc),
                            )
            else:
                log_event(logger, logging.INFO, "no_new_jobs_to_write")

    log_event(logger, logging.INFO, "run_end", **summary)
    return 0


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    try:
        config = load_config(config_path)
        return run(config)
    except ConfigError as exc:
        logger = setup_logger(_preload_log_dir(config_path))
        log_event(
            logger,
            logging.ERROR,
            "config_load_failed",
            config_path=str(config_path),
            error=str(exc),
        )
        print(f"FAIL-FAST: {exc}", file=sys.stderr)
        return 1
    except ImapError as exc:
        logger = setup_logger(_preload_log_dir(config_path))
        log_event(
            logger,
            logging.ERROR,
            "imap_connect_failed",
            error=str(exc),
        )
        print(f"FAIL-FAST: {exc}", file=sys.stderr)
        return 1
    except (SheetsError, RuntimeError) as exc:
        print(f"FAIL-FAST: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
