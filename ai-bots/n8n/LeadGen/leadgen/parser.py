from __future__ import annotations

import json
import re
from typing import Any

from .errors import LeadGenError


def extract_output_text(openai_response: dict[str, Any]) -> str:
    output_text = str(openai_response.get("output_text") or "").strip()
    if output_text:
        return output_text

    output = openai_response.get("output")
    if isinstance(output, list) and output:
        content = output[0].get("content", [])
        if isinstance(content, list) and content:
            text = str(content[0].get("text") or "").strip()
            if text:
                return text
    return ""


def extract_website_from_text(text: str) -> str:
    match = re.search(r"https?://[^\s\"']+", text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).strip().rstrip(".,;)")


def _strip_code_fences(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^\s*```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*```\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _is_ambiguous_classification(classification: str) -> bool:
    normalized = classification.strip().lower()
    if not normalized:
        return True
    markers = {"ambiguous", "unknown", "unclear", "n/a", "other"}
    return normalized in markers


def _contains_automotive_distribution_signal(text: str) -> bool:
    hay = text.lower()
    has_auto = "automotive" in hay
    has_distribution = ("wholesale" in hay) or ("distributor" in hay) or ("distribution" in hay)
    has_b2b_target = ("professional" in hay) or ("service center" in hay) or ("repair shop" in hay)
    return has_auto and has_distribution and has_b2b_target


def parse_and_validate_ai_json(
    *,
    openai_response: dict[str, Any],
    manual_review_threshold: int,
    website_source: str,
) -> dict[str, Any]:
    raw_text = extract_output_text(openai_response)
    if not raw_text:
        raise LeadGenError("E07_INVALID_AI_JSON", "OpenAI response text is empty")

    normalized = _strip_code_fences(raw_text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise LeadGenError("E07_INVALID_AI_JSON", "Unable to parse model output as JSON") from exc

    eligibility = str(parsed.get("eligibility", "")).strip()
    tier = str(parsed.get("tier", "")).strip()
    icp_classification = str(parsed.get("icp_classification", "")).strip()
    reasoning = str(parsed.get("reasoning", "")).strip()

    if eligibility not in {"Yes", "No"}:
        raise LeadGenError("E07_INVALID_AI_JSON", "eligibility must be Yes or No")
    if tier not in {"Tier 1", "Tier 2", "N/A"}:
        raise LeadGenError("E07_INVALID_AI_JSON", "tier must be Tier 1, Tier 2, or N/A")
    if not icp_classification:
        raise LeadGenError("E07_INVALID_AI_JSON", "icp_classification is required")
    if not reasoning:
        raise LeadGenError("E07_INVALID_AI_JSON", "reasoning is required")

    try:
        confidence = int(round(float(parsed.get("confidence_score", 0))))
    except (TypeError, ValueError) as exc:
        raise LeadGenError("E07_INVALID_AI_JSON", "confidence_score must be numeric") from exc
    confidence = max(0, min(100, confidence))

    manual_review_ai = bool(parsed.get("manual_review", False))
    manual_review_reason = str(parsed.get("manual_review_reason", "")).strip()
    low_confidence = confidence < manual_review_threshold

    if low_confidence:
        extra = f"confidence below threshold ({manual_review_threshold})"
        manual_review_reason = f"{manual_review_reason}; {extra}".strip("; ").strip() if manual_review_reason else extra

    evidence = parsed.get("evidence")
    evidence_text = ""
    if isinstance(evidence, str):
        evidence_text = evidence
    elif isinstance(evidence, list):
        evidence_text = " ".join(str(x) for x in evidence)
    elif isinstance(evidence, dict):
        evidence_text = json.dumps(evidence, ensure_ascii=True)

    signal_blob = " ".join([reasoning, evidence_text, icp_classification])
    if _is_ambiguous_classification(icp_classification) and _contains_automotive_distribution_signal(signal_blob):
        icp_classification = "Automotive Parts Wholesale Distribution"

    return {
        "eligibility": eligibility,
        "icp_classification": icp_classification,
        "tier": tier,
        "confidence_score": confidence,
        "reasoning": reasoning,
        "manual_review": manual_review_ai or low_confidence,
        "manual_review_reason": manual_review_reason,
        "website_source": str(parsed.get("website_source") or website_source or "unknown"),
    }
