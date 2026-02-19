from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import Config
from .errors import LeadGenError
from .firecrawl_client import FirecrawlClient
from .google_sheets import GoogleSheetsClient
from .hsst_log import HSSTLogger
from .openai_client import OpenAIClient
from .parser import parse_and_validate_ai_json
from .prompts import build_prompt_context, normalize_row
from .status_log import indent_context, log_event, log_raw_line, request_context, track_status
from textwrap import shorten


@dataclass
class PipelineResult:
    ok: bool
    row_number: int
    status: str
    request_id: str
    updated_ranges: list[str]
    ignored_keys: list[str]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shorten(text: str, width: int = 160) -> str:
    return shorten(text.replace("\n", " "), width=width, placeholder="...")


def _format_log_value(value: Any) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=True)
    except TypeError:
        rendered = str(value)
    return rendered


def _log_json_pairs(source: str, payload: Any) -> None:
    if not isinstance(payload, dict):
        log_raw_line(_format_log_value(payload), source=source)
        return
    for key, value in payload.items():
        log_raw_line(f"{key}={_format_log_value(value)}", source=source)


class LeadVettingPipeline:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = HSSTLogger(config.log_file)
        self.sheets = GoogleSheetsClient(
            credentials_file=config.google_credentials_file,
            spreadsheet_id=config.google_sheet_id,
            sheet_name=config.google_sheet_tab,
        )
        self.openai = OpenAIClient(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model=config.openai_model,
        )
        self.firecrawl = FirecrawlClient(
            api_key=config.firecrawl_api_key,
            base_url=config.firecrawl_base_url,
        )

    def _compose_success_update(self, context: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        status = "MANUAL_REVIEW" if decision["manual_review"] else "COMPLETE"
        return {
            "status": status,
            "eligibility": decision["eligibility"],
            "icp_classification": decision["icp_classification"],
            "tier": decision["tier"],
            "confidence_score": decision["confidence_score"],
            "reasoning": decision["reasoning"],
            "enriched_website": context.get("final_website", ""),
            "manual_review": "Yes" if decision["manual_review"] else "No",
            "manual_review_reason": decision["manual_review_reason"],
            "error_code": "",
            "processed_at_utc": _now_utc(),
            "request_id": context["request_id"],
        }

    def _compose_error_update(self, request_id: str, code: str, message: str, final_website: str = "") -> dict[str, Any]:
        return {
            "status": "ERROR",
            "eligibility": "",
            "icp_classification": "",
            "tier": "",
            "confidence_score": "",
            "reasoning": "",
            "enriched_website": final_website,
            "manual_review": "Yes",
            "manual_review_reason": message,
            "error_code": code,
            "processed_at_utc": _now_utc(),
            "request_id": request_id,
        }

    @track_status("Function LeadVettingPipeline.run_single_row")
    def run_single_row(self, row_number: int, request_id: str | None = None) -> PipelineResult:
        if row_number < 2:
            raise LeadGenError("E01_MALFORMED_PAYLOAD", "row_number must be integer >= 2")

        raw_request_id = request_id if request_id is not None else ""
        if not isinstance(raw_request_id, str):
            raw_request_id = str(raw_request_id)
        normalized_request_id = raw_request_id.strip()
        effective_request_id = normalized_request_id if normalized_request_id else str(uuid4())
        with request_context(effective_request_id):
            self.logger.event("run_started", row_number=row_number, request_id=effective_request_id)
            log_event("LeadVettingPipeline.run_single_row", "info", f"row {row_number}")

            with indent_context():
                raw_row = self.sheets.read_row(row_number)
                self.logger.event("sheet_row_read", row_number=row_number, request_id=effective_request_id)
                log_event("LeadVettingPipeline.sheet", "ok", "row read")
                with indent_context():
                    log_event(
                        "LeadVettingPipeline.raw_row",
                        "info",
                        f"company={raw_row.get('company','')[:30]} country={raw_row.get('country','')}",
                    )

            try:
                normalized = normalize_row(
                    raw=raw_row,
                    row_number=row_number,
                    request_id=effective_request_id,
                    sheet_id=self.config.google_sheet_id,
                    sheet_tab=self.config.google_sheet_tab,
                )
            except ValueError as exc:
                code = str(exc).split(":")[0].strip() if ":" in str(exc) else "E03_MISSING_REQUIRED_LEAD_FIELDS"
                raise LeadGenError(code, str(exc)) from exc

            context: dict[str, Any] = dict(normalized)
            context["final_website"] = normalized["website"]
            context["website_source"] = "sheet" if normalized["website"] else "unknown"
            with indent_context():
                log_event(
                    "LeadVettingPipeline.normalized",
                    "info",
                    f"company={normalized['company_name'][:30]} website={normalized['website'] or 'none'}",
                )

            try:
                with indent_context():
                    if not context["final_website"]:
                        with indent_context():
                            log_event("LeadVettingPipeline.openai", "start", "discover_website")
                            discovered = self.openai.discover_website(
                                company=normalized["company_name"],
                                industry=normalized["industry"],
                                country=normalized["country"],
                            )
                            log_event(
                                "LeadVettingPipeline.openai",
                                "ok",
                                f"discover={_shorten(discovered, 120)}",
                            )
                            if not discovered:
                                raise LeadGenError("E04_WEBSITE_DISCOVERY_FAILED", "Missing website after AI discovery")
                            context["final_website"] = discovered
                            context["website_source"] = "ai_discovered"
                            self.logger.event(
                                "website_discovered",
                                row_number=row_number,
                                request_id=effective_request_id,
                                final_website=discovered,
                            )
                            log_event(
                                "LeadVettingPipeline.website",
                                "ok",
                                f"ai_discovered {discovered}",
                            )
                            log_event(
                                "LeadVettingPipeline.openai_discovery_payload",
                                "info",
                                f"discovered={_format_log_value(discovered)}",
                            )
                    else:
                        with indent_context():
                            self.logger.event(
                                "website_present",
                                row_number=row_number,
                                request_id=effective_request_id,
                                final_website=context["final_website"],
                            )
                            log_event(
                                "LeadVettingPipeline.website",
                                "ok",
                                f"from_sheet {context['final_website']}",
                            )

                    with indent_context():
                        scraped = self.firecrawl.scrape_markdown(context["final_website"])
                        self.logger.event(
                            "website_scraped",
                            row_number=row_number,
                            request_id=effective_request_id,
                            scraped_chars=len(scraped),
                        )
                        log_event(
                            "LeadVettingPipeline.website_scraped",
                            "ok",
                            f"chars={len(scraped)}",
                        )
                        log_event(
                            "LeadVettingPipeline.scrape_preview",
                            "info",
                            f"{scraped[:60].replace('\\n',' ')}",
                        )

                    with indent_context():
                        log_event("LeadVettingPipeline.openai", "start", "build_prompt")
                        prompt = build_prompt_context(
                            company_name=normalized["company_name"],
                            final_website=context["final_website"],
                            industry=normalized["industry"],
                            country=normalized["country"],
                            notes=normalized["notes"],
                            scraped_text=scraped,
                            manual_review_threshold=self.config.manual_review_threshold,
                        )
                        log_event(
                            "LeadVettingPipeline.prompt",
                            "ok",
                            f"system_len={len(prompt['prompt_system'])} user_len={len(prompt['prompt_user'])}",
                        )
                        log_event("LeadVettingPipeline.openai", "start", "evaluate")
                        ai_response = self.openai.evaluate(
                            prompt_system=prompt["prompt_system"],
                            prompt_user=prompt["prompt_user"],
                        )
                        response_text = ai_response if isinstance(ai_response, str) else json.dumps(ai_response)
                        log_event(
                            "LeadVettingPipeline.openai",
                            "ok",
                            f"evaluate len={len(response_text.strip())}",
                        )
                        if isinstance(ai_response, dict):
                            _log_json_pairs("LeadVettingPipeline.ai_response_payload", ai_response)
                        else:
                            log_event("LeadVettingPipeline.ai_response_payload", "info", _format_log_value(ai_response))
                        self.logger.event("lead_evaluated", row_number=row_number, request_id=effective_request_id)
                        log_event("LeadVettingPipeline.lead_evaluated", "ok", "ai response parsed")
                        log_event(
                            "LeadVettingPipeline.ai_response",
                            "info",
                            f"len={len(response_text.strip())}",
                        )

                        decision = parse_and_validate_ai_json(
                            openai_response=ai_response,
                            manual_review_threshold=self.config.manual_review_threshold,
                            website_source=context["website_source"],
                        )
                        log_event(
                            "LeadVettingPipeline.decision",
                            "info",
                            f"manual_review={decision['manual_review']}",
                        )
                        update_payload = self._compose_success_update(context, decision)
                        _log_json_pairs("LeadVettingPipeline.sheet_update_payload", update_payload)
                        update_result = self.sheets.update_row_columns(row_number, update_payload)
                        _log_json_pairs("LeadVettingPipeline.sheet_update_result", update_result)

                    with indent_context():
                        self.logger.event(
                            "sheet_updated_success",
                            row_number=row_number,
                            request_id=effective_request_id,
                            status=update_payload["status"],
                            updated_ranges=update_result["updated_keys"],
                            ignored_keys=update_result["ignored_keys"],
                        )
                        log_event(
                            "LeadVettingPipeline.sheet_updated_success",
                            "ok",
                            f"status={update_payload['status']}",
                        )
                    return PipelineResult(
                        ok=True,
                        row_number=row_number,
                        status=update_payload["status"],
                        request_id=effective_request_id,
                        updated_ranges=update_result["updated_keys"],
                        ignored_keys=update_result["ignored_keys"],
                    )
            except LeadGenError as exc:
                with indent_context():
                    error_payload = self._compose_error_update(
                        request_id=effective_request_id,
                        code=exc.code,
                        message=exc.message,
                        final_website=context.get("final_website", ""),
                    )
                    _log_json_pairs("LeadVettingPipeline.sheet_update_payload", error_payload)
                    update_result = self.sheets.update_row_columns(row_number, error_payload)
                    _log_json_pairs("LeadVettingPipeline.sheet_update_result", update_result)
                    self.logger.event(
                        "sheet_updated_error",
                        row_number=row_number,
                        request_id=effective_request_id,
                        error_code=exc.code,
                        error_message=exc.message,
                        updated_ranges=update_result["updated_keys"],
                        ignored_keys=update_result["ignored_keys"],
                    )
                    log_event(
                        "LeadVettingPipeline.sheet_updated_error",
                        "error",
                        f"{exc.code} {exc.message}",
                    )
                    return PipelineResult(
                        ok=False,
                        row_number=row_number,
                        status="ERROR",
                        request_id=effective_request_id,
                        updated_ranges=update_result["updated_keys"],
                        ignored_keys=update_result["ignored_keys"],
                    )

