#!/usr/bin/env python3
"""
Deterministic Upwork capture evaluator.

Input:
- upwork_capture_*.json from capture_visible_upwork_jobs.py

Output:
- upwork_evaluation_YYYYMMDD_HHMMSS.json
- upwork_evaluation_YYYYMMDD_HHMMSS.md
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_PATH = PROJECT_DIR / "upwork_fit_profile.json"


class FailFastError(RuntimeError):
    pass


def fail(message: str, code: int = 1) -> int:
    print(f"FAIL-FAST: {message}")
    return code


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def read_required_json(path: Path, label: str) -> Any:
    if not path.exists():
        raise FailFastError(f"Missing required {label}: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FailFastError(f"Unable to read {label}: {path} ({exc})") from exc
    if not raw.strip():
        raise FailFastError(f"{label} is empty: {path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FailFastError(f"Invalid JSON in {label}: {path} ({exc})") from exc
    return data


def find_latest_capture_json(search_dir: Path) -> Path:
    candidates = [
        p
        for p in search_dir.glob("upwork_capture_*.json")
        if p.is_file() and not p.name.startswith("upwork_evaluation_")
    ]
    if not candidates:
        raise FailFastError(f"No upwork_capture_*.json files found in: {search_dir}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def require_profile_schema(profile: dict[str, Any]) -> None:
    required_top = {"thresholds", "rate", "description", "signals"}
    missing_top = sorted(required_top - set(profile.keys()))
    if missing_top:
        raise FailFastError(f"Profile missing required sections: {', '.join(missing_top)}")

    thresholds = profile["thresholds"]
    rate = profile["rate"]
    description = profile["description"]
    signals = profile["signals"]
    if not isinstance(thresholds, dict) or not isinstance(rate, dict):
        raise FailFastError("Profile sections 'thresholds' and 'rate' must be JSON objects.")
    if not isinstance(description, dict) or not isinstance(signals, dict):
        raise FailFastError("Profile sections 'description' and 'signals' must be JSON objects.")

    required_thresholds = {"bid", "maybe"}
    missing_thresholds = sorted(required_thresholds - set(thresholds.keys()))
    if missing_thresholds:
        raise FailFastError(f"Profile thresholds missing keys: {', '.join(missing_thresholds)}")

    required_rate = {
        "min_hourly",
        "preferred_hourly",
        "max_reasonable_hourly",
        "min_fixed",
        "preferred_fixed",
        "max_reasonable_fixed",
    }
    missing_rate = sorted(required_rate - set(rate.keys()))
    if missing_rate:
        raise FailFastError(f"Profile rate section missing keys: {', '.join(missing_rate)}")

    required_description = {"min_length", "low_signal_phrases"}
    missing_description = sorted(required_description - set(description.keys()))
    if missing_description:
        raise FailFastError(
            f"Profile description section missing keys: {', '.join(missing_description)}"
        )

    required_signals = {
        "strong_keywords",
        "medium_keywords",
        "negative_keywords",
        "hard_stop_keywords",
        "scope_keywords",
        "deliverable_keywords",
    }
    missing_signals = sorted(required_signals - set(signals.keys()))
    if missing_signals:
        raise FailFastError(f"Profile signals section missing keys: {', '.join(missing_signals)}")


def parse_money_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"\$\s*(\d[\d,]*(?:\.\d+)?)([Kk]?)", text or ""):
        number_text = match.group(1).replace(",", "")
        suffix = match.group(2).lower()
        try:
            amount = float(number_text)
        except ValueError:
            continue
        if suffix == "k":
            amount *= 1000.0
        values.append(amount)
    return values


def parse_rate(rate_text: str, job_type: str) -> dict[str, Any]:
    raw = clean_text(rate_text)
    type_text = clean_text(job_type).lower()
    lower = raw.lower()

    values = parse_money_values(raw)
    is_hourly = "/hr" in lower or "hourly" in lower or type_text == "hourly"
    parsed_amount: float | None = None
    if values:
        if is_hourly and len(values) >= 2:
            parsed_amount = (values[0] + values[1]) / 2.0
        elif is_hourly:
            parsed_amount = values[0]
        else:
            parsed_amount = max(values)

    return {
        "raw": raw,
        "is_hourly": is_hourly,
        "values": values,
        "amount": parsed_amount,
    }


def keyword_hits(text_lower: str, phrases: list[str]) -> list[str]:
    hits: list[str] = []
    for phrase in phrases:
        phrase_clean = clean_text(phrase).lower()
        if not phrase_clean:
            continue
        if phrase_clean in text_lower:
            hits.append(phrase_clean)
    return sorted(set(hits))


def has_low_signal_description(description: str, low_signal_phrases: list[str]) -> bool:
    desc = clean_text(description).lower()
    if not desc:
        return True
    for phrase in low_signal_phrases:
        if clean_text(phrase).lower() == desc:
            return True
    return False


def clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def recommendation_from_score(score: int, thresholds: dict[str, Any]) -> str:
    bid_threshold = int(thresholds["bid"])
    maybe_threshold = int(thresholds["maybe"])
    if score >= bid_threshold:
        return "BID"
    if score >= maybe_threshold:
        return "MAYBE"
    return "SKIP"


def evaluate_job(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    thresholds = profile["thresholds"]
    rate_cfg = profile["rate"]
    desc_cfg = profile["description"]
    signals = profile["signals"]

    title = clean_text(job.get("title"))
    company = clean_text(job.get("company"))
    rate = clean_text(job.get("rate"))
    job_type = clean_text(job.get("type"))
    description = clean_text(job.get("description"))
    posted = clean_text(job.get("posted"))
    url = clean_text(job.get("url"))
    tags = [clean_text(t) for t in (job.get("tags") or []) if clean_text(t)]

    text_blob = " ".join([title, company, rate, description, " ".join(tags)]).lower()

    positives: list[str] = []
    risks: list[str] = []
    hard_stops: list[str] = []

    if not title:
        hard_stops.append("Missing title")
    if not url:
        hard_stops.append("Missing job URL")

    min_description_length = int(desc_cfg["min_length"])
    if has_low_signal_description(description, desc_cfg["low_signal_phrases"]):
        hard_stops.append("Low-signal or placeholder description")
    elif len(description) < min_description_length:
        risks.append(f"Short description ({len(description)} chars)")

    hard_stop_hits = keyword_hits(text_blob, list(signals["hard_stop_keywords"]))
    if hard_stop_hits:
        hard_stops.append("Hard-stop keyword(s): " + ", ".join(hard_stop_hits))

    strong_hits = keyword_hits(text_blob, list(signals["strong_keywords"]))
    medium_hits = keyword_hits(text_blob, list(signals["medium_keywords"]))
    negative_hits = keyword_hits(text_blob, list(signals["negative_keywords"]))
    scope_hits = keyword_hits(text_blob, list(signals["scope_keywords"]))
    deliverable_hits = keyword_hits(text_blob, list(signals["deliverable_keywords"]))

    skill_score = min(45, len(strong_hits) * 8 + len(medium_hits) * 4)
    if strong_hits or medium_hits:
        hit_preview = ", ".join((strong_hits + medium_hits)[:6])
        positives.append(f"Skill alignment keywords: {hit_preview}")
    else:
        risks.append("No direct match with target skill keywords")

    parsed_rate = parse_rate(rate, job_type)
    rate_score = 8
    if parsed_rate["amount"] is not None:
        amount = float(parsed_rate["amount"])
        if parsed_rate["is_hourly"]:
            min_hourly = float(rate_cfg["min_hourly"])
            preferred_hourly = float(rate_cfg["preferred_hourly"])
            max_reasonable_hourly = float(rate_cfg["max_reasonable_hourly"])
            if amount < min_hourly:
                hard_stops.append(
                    f"Hourly rate below floor (${amount:.2f} < ${min_hourly:.2f})"
                )
            elif amount >= preferred_hourly:
                rate_score = 20
            else:
                denom = max(1.0, preferred_hourly - min_hourly)
                rate_score = int(round(10 + ((amount - min_hourly) / denom) * 10))
            if amount > max_reasonable_hourly:
                risks.append(f"Rate appears outlier-high (${amount:.2f}/hr), verify listing quality")
                rate_score = max(0, rate_score - 4)
            positives.append(f"Parsed hourly rate: ${amount:.2f}/hr")
        else:
            min_fixed = float(rate_cfg["min_fixed"])
            preferred_fixed = float(rate_cfg["preferred_fixed"])
            max_reasonable_fixed = float(rate_cfg["max_reasonable_fixed"])
            if amount < min_fixed:
                hard_stops.append(
                    f"Fixed budget below floor (${amount:.2f} < ${min_fixed:.2f})"
                )
            elif amount >= preferred_fixed:
                rate_score = 20
            else:
                denom = max(1.0, preferred_fixed - min_fixed)
                rate_score = int(round(10 + ((amount - min_fixed) / denom) * 10))
            if amount > max_reasonable_fixed:
                risks.append(f"Budget appears outlier-high (${amount:.2f}), verify listing quality")
                rate_score = max(0, rate_score - 4)
            positives.append(f"Parsed fixed budget: ${amount:.2f}")
    else:
        risks.append("Rate not parseable from listing")
        rate_score = 6

    desc_length = len(description)
    if desc_length >= 400:
        quality_score = 15
    elif desc_length >= 250:
        quality_score = 13
    elif desc_length >= 140:
        quality_score = 10
    elif desc_length >= min_description_length:
        quality_score = 7
    else:
        quality_score = 3
    positives.append("Description captured and scored for quality")

    scope_score = 0
    if scope_hits:
        scope_score += 4
        positives.append("Scope keywords: " + ", ".join(scope_hits[:4]))
    if deliverable_hits:
        scope_score += 3
        positives.append("Deliverable language present")
    if parsed_rate["amount"] is not None:
        scope_score += 3
    scope_score = min(10, scope_score)

    penalty = 0
    if negative_hits:
        penalty += min(24, len(negative_hits) * 6)
        risks.append("Negative keyword(s): " + ", ".join(negative_hits[:5]))
    if desc_length < min_description_length:
        penalty += 8
    if parsed_rate["amount"] is None:
        penalty += 4

    raw_score = skill_score + rate_score + quality_score + scope_score - penalty
    fit_score = clamp_score(raw_score)

    hard_stop = len(hard_stops) > 0
    if hard_stop and fit_score > 49:
        fit_score = 49

    recommendation = "SKIP" if hard_stop else recommendation_from_score(fit_score, thresholds)

    evidence_count = len(strong_hits) + len(medium_hits)
    if hard_stop:
        confidence = "high"
    elif evidence_count >= 4 and desc_length >= min_description_length and parsed_rate["amount"] is not None:
        confidence = "high"
    elif evidence_count >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "title": title,
        "company": company,
        "rate": rate,
        "type": job_type,
        "posted": posted,
        "url": url,
        "description": description,
        "tags": tags,
        "fit_score": fit_score,
        "recommendation": recommendation,
        "confidence": confidence,
        "hard_stop": hard_stop,
        "hard_stop_reasons": hard_stops,
        "positives": positives[:6],
        "risks": risks[:6],
        "matched_keywords": {
            "strong": strong_hits,
            "medium": medium_hits,
            "negative": negative_hits,
            "hard_stop": hard_stop_hits,
        },
        "parsed_rate": parsed_rate,
    }


def summarize_results(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total_jobs": len(items),
        "bid_count": 0,
        "maybe_count": 0,
        "skip_count": 0,
        "hard_stop_count": 0,
    }
    for item in items:
        rec = item["recommendation"]
        if rec == "BID":
            summary["bid_count"] += 1
        elif rec == "MAYBE":
            summary["maybe_count"] += 1
        else:
            summary["skip_count"] += 1
        if item["hard_stop"]:
            summary["hard_stop_count"] += 1
    return summary


def sort_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"BID": 0, "MAYBE": 1, "SKIP": 2}
    return sorted(items, key=lambda x: (order.get(x["recommendation"], 9), -x["fit_score"], x["title"]))


def render_markdown(
    *,
    timestamp: str,
    source_capture_path: Path,
    profile_path: Path,
    thresholds: dict[str, Any],
    summary: dict[str, Any],
    items: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"## Upwork Evaluation - {timestamp}")
    lines.append("")
    lines.append(f"SourceCapture: {source_capture_path}")
    lines.append(f"Profile: {profile_path}")
    lines.append(
        f"Thresholds: BID >= {int(thresholds['bid'])}, MAYBE >= {int(thresholds['maybe'])}, else SKIP"
    )
    lines.append("")
    lines.append("### Summary")
    lines.append(f"Total Jobs: {summary['total_jobs']}")
    lines.append(f"BID: {summary['bid_count']}")
    lines.append(f"MAYBE: {summary['maybe_count']}")
    lines.append(f"SKIP: {summary['skip_count']}")
    lines.append(f"Hard Stops: {summary['hard_stop_count']}")
    lines.append("")

    lines.append("### Top Recommendations")
    top = [item for item in items if item["recommendation"] != "SKIP"][:15]
    if not top:
        lines.append("No BID or MAYBE jobs in this run.")
    else:
        rank = 1
        for item in top:
            lines.append(f"{rank}. [{item['recommendation']} {item['fit_score']}] {item['title']}")
            lines.append(f"URL: {item['url']}")
            lines.append(f"Why: {item['positives'][0] if item['positives'] else 'No positive signals found'}")
            if item["risks"]:
                lines.append(f"Risk: {item['risks'][0]}")
            lines.append("")
            rank += 1

    lines.append("### Full Results")
    lines.append("")
    for item in items:
        lines.append("#### JOB")
        lines.append(f"Title: {item['title']}")
        lines.append(f"Recommendation: {item['recommendation']}")
        lines.append(f"FitScore: {item['fit_score']}")
        lines.append(f"Confidence: {item['confidence']}")
        lines.append(f"HardStop: {'yes' if item['hard_stop'] else 'no'}")
        lines.append(f"HardStopReasons: {', '.join(item['hard_stop_reasons'])}")
        lines.append(f"Positives: {' | '.join(item['positives'])}")
        lines.append(f"Risks: {' | '.join(item['risks'])}")
        lines.append(f"Rate: {item['rate']}")
        lines.append(f"Type: {item['type']}")
        lines.append(f"Posted: {item['posted']}")
        lines.append(f"URL: {item['url']}")
        lines.append(f"Description: {item['description']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic evaluator for Upwork capture JSON.")
    parser.add_argument(
        "--input",
        dest="input_path",
        default="",
        help="Path to upwork_capture_*.json. If omitted, newest file in project dir is used.",
    )
    parser.add_argument(
        "--profile",
        dest="profile_path",
        default=str(DEFAULT_PROFILE_PATH),
        help="Path to evaluator profile JSON.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=str(PROJECT_DIR),
        help="Directory for upwork_evaluation_*.json/.md outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    profile_path = Path(args.profile_path).expanduser().resolve()
    input_path = (
        Path(args.input_path).expanduser().resolve()
        if clean_text(args.input_path)
        else find_latest_capture_json(PROJECT_DIR)
    )

    try:
        profile_raw = read_required_json(profile_path, "profile JSON")
        if not isinstance(profile_raw, dict):
            raise FailFastError(f"Profile must be a JSON object: {profile_path}")
        require_profile_schema(profile_raw)

        capture_raw = read_required_json(input_path, "capture JSON")
        if not isinstance(capture_raw, list):
            raise FailFastError(f"Capture JSON must be a list of jobs: {input_path}")
        if not capture_raw:
            raise FailFastError(f"Capture JSON contains zero jobs: {input_path}")

        evaluated: list[dict[str, Any]] = []
        for index, item in enumerate(capture_raw):
            if not isinstance(item, dict):
                raise FailFastError(f"Capture job at index {index} is not a JSON object.")
            evaluated.append(evaluate_job(item, profile_raw))

        sorted_items = sort_results(evaluated)
        summary = summarize_results(sorted_items)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"upwork_evaluation_{timestamp}.json"
        md_path = output_dir / f"upwork_evaluation_{timestamp}.md"

        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_capture": str(input_path),
            "profile": str(profile_path),
            "thresholds": {
                "bid": int(profile_raw["thresholds"]["bid"]),
                "maybe": int(profile_raw["thresholds"]["maybe"]),
            },
            "summary": summary,
            "jobs": sorted_items,
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        md_path.write_text(
            render_markdown(
                timestamp=timestamp,
                source_capture_path=input_path,
                profile_path=profile_path,
                thresholds=profile_raw["thresholds"],
                summary=summary,
                items=sorted_items,
            ),
            encoding="utf-8",
        )

        print(str(json_path))
        print(str(md_path))
        return 0
    except FailFastError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"Evaluator crashed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
