from __future__ import annotations

import json
from typing import Any


def build_prompt_context(
    *,
    company_name: str,
    final_website: str,
    industry: str,
    country: str,
    notes: str,
    scraped_text: str,
    manual_review_threshold: int,
) -> dict[str, str]:
    bounded = scraped_text[:12000]

    prompt_system = (
        "You are a B2B lead qualification engine. "
        "Return strict JSON only. "
        "No markdown, no code fences, no prose."
    )

    icp_rules = [
        "Disqualify if no valid website and insufficient company signals.",
        "Prefer B2B service or SaaS companies.",
        "Exclude consumer-only retail unless explicitly allowed.",
        "Flag ambiguous industry classification for manual review.",
        "Require country match if ICP is geo-restricted.",
        (
            "Do not mark industry as ambiguous when evidence clearly indicates "
            "automotive wholesale/distribution for professional service centers."
        ),
    ]

    prompt_user = json.dumps(
        {
            "companyName": company_name,
            "website": final_website,
            "industry": industry,
            "country": country,
            "notes": notes,
            "manual_review_threshold": manual_review_threshold,
            "criteria": {
                "required_fields": [
                    "eligibility",
                    "icp_classification",
                    "tier",
                    "confidence_score",
                    "reasoning",
                    "manual_review",
                    "manual_review_reason",
                    "website_source",
                    "evidence",
                ],
                "eligibility_values": ["Yes", "No"],
                "tier_values": ["Tier 1", "Tier 2", "N/A"],
                "icp_rules": icp_rules,
            },
            "scraped_text": bounded,
        },
        ensure_ascii=True,
    )

    return {"prompt_system": prompt_system, "prompt_user": prompt_user}


def normalize_row(raw: dict[str, Any], row_number: int, request_id: str, sheet_id: str, sheet_tab: str) -> dict[str, Any]:
    company_name = str(raw.get("company") or raw.get("companyName") or raw.get("Company") or "").strip()
    if not company_name:
        raise ValueError("E03_MISSING_REQUIRED_LEAD_FIELDS: company is required")

    website = str(raw.get("website") or raw.get("Website") or "").strip()
    industry = str(raw.get("industry") or raw.get("Industry") or "").strip()
    country = str(raw.get("country") or raw.get("Country") or "").strip()
    notes = str(raw.get("notes") or raw.get("Notes") or "").strip()
    idempotency_key = f"{sheet_id}:{sheet_tab}:{row_number}"

    return {
        "row_number": row_number,
        "request_id": request_id,
        "company_name": company_name,
        "website": website,
        "industry": industry,
        "country": country,
        "notes": notes,
        "idempotency_key": idempotency_key,
    }
