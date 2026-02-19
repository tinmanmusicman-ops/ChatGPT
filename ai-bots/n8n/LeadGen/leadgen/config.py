from __future__ import annotations

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    google_sheet_id: str
    google_sheet_tab: str
    google_credentials_file: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    firecrawl_api_key: str
    firecrawl_base_url: str
    manual_review_threshold: int
    log_file: str

    @staticmethod
    def from_env() -> "Config":
        threshold_raw = _require("LEADGEN_MANUAL_REVIEW_THRESHOLD")
        try:
            threshold = int(threshold_raw)
        except ValueError as exc:
            raise RuntimeError(
                "LEADGEN_MANUAL_REVIEW_THRESHOLD must be an integer between 0 and 100"
            ) from exc
        if threshold < 0 or threshold > 100:
            raise RuntimeError(
                "LEADGEN_MANUAL_REVIEW_THRESHOLD must be an integer between 0 and 100"
            )

        return Config(
            google_sheet_id=_require("LEADGEN_GOOGLE_SHEET_ID"),
            google_sheet_tab=_require("LEADGEN_GOOGLE_SHEET_TAB"),
            google_credentials_file=_require("LEADGEN_GOOGLE_CREDENTIALS_FILE"),
            openai_api_key=_require("OPENAI_API_KEY"),
            openai_model=_require("LEADGEN_OPENAI_MODEL"),
            openai_base_url=_require("LEADGEN_OPENAI_BASE_URL").rstrip("/"),
            firecrawl_api_key=_require("FIRECRAWL_API_KEY"),
            firecrawl_base_url=_require("LEADGEN_FIRECRAWL_BASE_URL").rstrip("/"),
            manual_review_threshold=threshold,
            log_file=_require("LEADGEN_LOG_FILE"),
        )
