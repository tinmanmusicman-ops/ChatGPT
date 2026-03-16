#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import importlib.util
import inspect
import json
import logging
import os
import re
import sqlite3
import smtplib
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, parsedate_to_datetime
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from lxml import etree

TRACE_BREAKPOINTS = False
AI_ALLOWED_EVENT_TYPES = {
    "funding_round",
    "m_and_a_transaction",
    "consumer_industry_news",
    "irrelevant",
}
AI_ALLOWED_CATEGORIES = {
    "consumer_brands",
    "consumer_technology",
    "commerce_and_retail_tech",
}
AI_WEEKLY_REQUIRED_HEADERS = [
    "## 👋 Intro 👋",
    "## 📊 Weekly Snapshot 📊",
    "## 💡 Key Themes 💡",
    "## 💰 Notable Funding 💰",
    "## 🤝 Notable M&A 🤝",
    # Consumer News split into 4 optional sections (only appear if data exists):
    # - Distribution & Expansion
    # - Product Launches
    # - Retail, Commerce Tech & Supply Chain
    # - Other Notable News
    "## 🙏 Closing 🙏",
]
AI_WEEKLY_NEWS_LIMIT = 25
RAW_SNAPSHOT_BASE_DIR = Path(
    os.environ.get("CONSUMER_VC_RUNS_DIR", "/opt/consumervc/data/runs")
).expanduser()
MONITOR_NODE_ERROR_PREFIX = "__MONITOR_NODE_ERROR__"
FLOW_LOG_DIR = Path(__file__).resolve().parent / "Logs"
FLOW_LOG_FILE = FLOW_LOG_DIR / "flow.log"
FLOW_LOG_DIR.mkdir(parents=True, exist_ok=True)
_FLOW_LOG_LOCK = threading.Lock()
_FLOW_TRACE_STATE = threading.local()
TRACE_ERROR_NODE_MAP = {
    "load_config": "load_config",
    "load_live_source_items": "ingest_source",
    "classify_and_extract": "classify",
    "upsert_event": "airtable_events",
    "create_event_without_dedupe": "airtable_events",
    "build_daily_summary": "summary_daily",
    "build_weekly_summary": "summary_weekly",
    "build_weekly_substack_draft": "ai_weekly_draft",
    "AirtableStore.validate_required_schema": "schema_audit",
    "AirtableStore.load_prompts": "load_prompts",
    "AirtableStore.load_runtime_controls": "runtime_controls",
    "AirtableStore.load_sources": "load_sources",
    "AirtableStore.append_revision": "revision_log",
    "EmailNotifier.send_daily_summary": "email_notify",
    "SlackNotifier.post_run_summary": "slack_post",
}
FLOW_TRACE_TARGETS = {
    "main",
    "parse_args",
    "load_config",
    "load_live_source_items",
    "classify_and_extract",
    "upsert_event",
    "create_event_without_dedupe",
    "build_daily_summary",
    "build_weekly_summary",
    "build_weekly_substack_draft",
    "run_daily",
    "run_weekly_summary_only",
    "AirtableStore.validate_required_schema",
    "AirtableStore.load_prompts",
    "AirtableStore.load_runtime_controls",
    "AirtableStore.load_sources",
    "AirtableStore.append_revision",
    "EmailNotifier.send_daily_summary",
    "SlackNotifier.post_run_summary",
}

class AIServiceError(RuntimeError):
    pass


class AIValidationError(RuntimeError):
    pass


def _flow_safe_text(value: Any) -> str:
    text = str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def _flow_write_separator() -> None:
    with _FLOW_LOG_LOCK:
        with FLOW_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write("\n")


def _flow_write_line(line: str) -> None:
    if getattr(_FLOW_TRACE_STATE, "writing", False):
        return
    _FLOW_TRACE_STATE.writing = True
    try:
        FLOW_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _FLOW_LOG_LOCK:
            with FLOW_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    finally:
        _FLOW_TRACE_STATE.writing = False


def _flow_should_log(func: Any) -> bool:
    qualname = str(getattr(func, "__qualname__", "")).strip()
    name = str(getattr(func, "__name__", "")).strip()
    return qualname in FLOW_TRACE_TARGETS or name in FLOW_TRACE_TARGETS


def _emit_monitor_node_error(func: Any, exc: Exception) -> None:
    qualname = str(getattr(func, "__qualname__", "")).strip()
    name = str(getattr(func, "__name__", "")).strip()
    node_id = TRACE_ERROR_NODE_MAP.get(qualname) or TRACE_ERROR_NODE_MAP.get(name)
    if not node_id:
        return
    exc_id = id(exc)
    last_exc_id = getattr(_FLOW_TRACE_STATE, "last_emitted_exc_id", None)
    if last_exc_id == exc_id:
        return
    _FLOW_TRACE_STATE.last_emitted_exc_id = exc_id
    payload = {
        "node_id": node_id,
        "function": qualname or name,
        "message": f"{exc.__class__.__name__}: {_flow_safe_text(exc)}",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }
    print(f"{MONITOR_NODE_ERROR_PREFIX}{json.dumps(payload, ensure_ascii=True)}", flush=True)


def traceable(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        should_log = _flow_should_log(func)
        if not should_log:
            if TRACE_BREAKPOINTS:
                print(f"[TRACE] entering {func.__name__}")
                breakpoint()
            return func(*args, **kwargs)
        started_at = datetime.now(timezone.utc)
        depth = int(getattr(_FLOW_TRACE_STATE, "depth", 0))
        call_id = int(getattr(_FLOW_TRACE_STATE, "call_id", 0)) + 1
        _FLOW_TRACE_STATE.call_id = call_id
        _flow_write_line(
            f"ENTER | depth={depth} | call={call_id} | {func.__qualname__}"
        )
        _FLOW_TRACE_STATE.depth = depth + 1
        if TRACE_BREAKPOINTS:
            print(f"[TRACE] entering {func.__name__}")
            breakpoint()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _FLOW_TRACE_STATE.depth = depth
            elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
            _flow_write_line(
                f"RAISE | depth={depth} | call={call_id} | "
                f"{func.__qualname__} |\nelapsed={elapsed_seconds:.3f}s | "
                f"{exc.__class__.__name__}: {_flow_safe_text(exc)}"
            )
            _emit_monitor_node_error(func, exc)
            _flow_write_separator()
            raise
        _FLOW_TRACE_STATE.depth = depth
        elapsed_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
        _flow_write_line(
            f"RETURN | depth={depth} | call={call_id} | {func.__qualname__} |"
        )
        _flow_write_line(
            f"elapsed={elapsed_seconds:.3f}s | result_type={type(result).__name__}"
        )
        _flow_write_separator()
        return result

    wrapper.__flow_traced__ = True
    return wrapper


def _instrument_class_methods(cls: type) -> None:
    for name, attr in list(vars(cls).items()):
        if name in {"__class__", "__dict__", "__weakref__", "__module__", "__doc__"}:
            continue
        if isinstance(attr, staticmethod):
            fn = attr.__func__
            if getattr(fn, "__module__", "") == __name__ and not getattr(fn, "__flow_traced__", False):
                setattr(cls, name, staticmethod(traceable(fn)))
        elif isinstance(attr, classmethod):
            fn = attr.__func__
            if getattr(fn, "__module__", "") == __name__ and not getattr(fn, "__flow_traced__", False):
                setattr(cls, name, classmethod(traceable(fn)))
        elif inspect.isfunction(attr):
            if getattr(attr, "__module__", "") == __name__ and not getattr(attr, "__flow_traced__", False):
                setattr(cls, name, traceable(attr))


def _enable_flow_tracing() -> None:
    skip_names = {
        "_flow_safe_text",
        "_flow_write_line",
        "_flow_should_log",
        "traceable",
        "_instrument_class_methods",
        "_enable_flow_tracing",
    }
    for name, obj in list(globals().items()):
        if name in skip_names:
            continue
        if inspect.isfunction(obj):
            if getattr(obj, "__module__", "") == __name__ and not getattr(obj, "__flow_traced__", False):
                globals()[name] = traceable(obj)
        elif inspect.isclass(obj) and getattr(obj, "__module__", "") == __name__:
            _instrument_class_methods(obj)


def init_trace_mode(config_path: Path) -> None:
    global TRACE_BREAKPOINTS
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        runtime_cfg = data.get("runtime", {})
        TRACE_BREAKPOINTS = bool(runtime_cfg.get("enable_breakpoints", False))
    except Exception:
        TRACE_BREAKPOINTS = False


@traceable
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@traceable
def parse_iso(value: str) -> datetime:
    txt = str(value).strip()
    if not txt:
        raise RuntimeError("empty datetime value")
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(txt)
    except ValueError as exc:
        raise RuntimeError(f"invalid datetime format: {value}") from exc


def parse_iso_date(value: str, *, field_name: str = "date") -> datetime.date:
    txt = str(value).strip()
    if not txt:
        raise RuntimeError(f"{field_name} is empty")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", txt):
        raise RuntimeError(f"{field_name} must be YYYY-MM-DD: {value}")
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as exc:
        raise RuntimeError(f"{field_name} has invalid date value: {value}") from exc
    parsed = dt.date()
    if parsed.isoformat() != txt:
        raise RuntimeError(f"{field_name} has invalid date value: {value}")
    return parsed


def _runtime_now(cfg: dict[str, Any]) -> datetime:
    tz_name = str(cfg.get("timezone", "")).strip() or "UTC"
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        logging.warning("invalid timezone in config (%s); falling back to UTC", tz_name)
        return datetime.now(timezone.utc)



def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip().lower()



RENDER_MISSING_VALUES = {"", "not disclosed", "undisclosed", "n/a", "na", "none", "null"}


def _is_missing_render_value(value: Any) -> bool:
    return normalize_text(value) in RENDER_MISSING_VALUES


def _clean_optional_render_text(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if _is_missing_render_value(text) else text


def _format_compact_currency(amount: float) -> str:
    if amount <= 0:
        return ""
    suffix = ""
    scaled = amount
    if amount >= 1_000_000_000:
        suffix = "B"
        scaled = amount / 1_000_000_000
    elif amount >= 1_000_000:
        suffix = "M"
        scaled = amount / 1_000_000
    elif amount >= 1_000:
        suffix = "K"
        scaled = amount / 1_000
    number = f"{scaled:.2f}".rstrip("0").rstrip(".")
    return f"${number}{suffix}"


def _parse_amount_numeric_and_currency(text: Any) -> tuple[int | None, str]:
    """Parse a raw amount string (e.g. '$2 billion', '€500M', 'C$120M') into
    (integer_amount_or_None, iso_currency_code).  Returns (None, '') if the
    text cannot be parsed.  Currency is inferred from leading symbol/code;
    defaults to 'USD' when a bare $ is present."""
    raw = str(text if text is not None else "").strip()
    if not raw:
        return None, ""
    lowered = raw.lower().replace(",", "")
    # --- currency detection (order matters: longer prefixes first) ---
    currency = ""
    if re.search(r"\bc\$", lowered) or re.search(r"\bcad\b", lowered):
        currency = "CAD"
    elif re.search(r"\ba\$", lowered) or re.search(r"\baud\b", lowered):
        currency = "AUD"
    elif re.search(r"\bnz\$", lowered) or re.search(r"\bnzd\b", lowered):
        currency = "NZD"
    elif re.search(r"\bhk\$", lowered) or re.search(r"\bhkd\b", lowered):
        currency = "HKD"
    elif re.search(r"\bs\$", lowered) or re.search(r"\bsgd\b", lowered):
        currency = "SGD"
    elif "£" in raw or re.search(r"\bgbp\b", lowered):
        currency = "GBP"
    elif "€" in raw or re.search(r"\beur\b", lowered):
        currency = "EUR"
    elif "¥" in raw or re.search(r"\bjpy\b|\bcny\b|\bcnh\b", lowered):
        currency = "JPY"
    elif "₹" in raw or re.search(r"\binr\b", lowered):
        currency = "INR"
    elif "$" in raw or re.search(r"\busd\b|\bus\$", lowered):
        currency = "USD"
    # strip all currency symbols/codes so regex can find the number
    cleaned = re.sub(r"[£€¥₹]", " ", lowered)
    cleaned = re.sub(r"\b(?:usd|eur|gbp|jpy|inr|cad|aud|nzd|hkd|sgd|cny|cnh)\b", " ", cleaned)
    cleaned = re.sub(r"[a-z]{1,2}\$", " ", cleaned)  # c$, a$, nz$, hk$, s$
    cleaned = cleaned.replace("$", " ").replace(",", "")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(billion|million|thousand|bn|mm|m|b|k)?\b", cleaned)
    if not match:
        return None, currency or ""
    amount = float(match.group(1))
    unit = str(match.group(2) or "").strip()
    if unit in {"billion", "bn", "b"}:
        amount *= 1_000_000_000
    elif unit in {"million", "mm", "m"}:
        amount *= 1_000_000
    elif unit in {"thousand", "k"}:
        amount *= 1_000
    return round(int(round(amount))), currency or "USD"


def _normalize_amount_text(value: Any) -> str:
    text = _clean_optional_render_text(value)
    if not text:
        return ""
    lowered = text.lower().replace(",", "")
    cleaned = re.sub(r"\b(?:usd|us\$)\b", "", lowered).replace("$", " ").strip()
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(billion|million|thousand|bn|mm|m|b|k)?\b", cleaned)
    if not match:
        return ""
    amount = float(match.group(1))
    unit = str(match.group(2) or "").strip()
    if unit in {"billion", "bn", "b"}:
        amount *= 1_000_000_000
    elif unit in {"million", "mm", "m"}:
        amount *= 1_000_000
    elif unit in {"thousand", "k"}:
        amount *= 1_000
    return _format_compact_currency(amount)


def _extract_entity_candidates(segment: str) -> list[str]:
    pieces = re.split(r",|;|\band\b", segment, flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for raw_piece in pieces:
        piece = re.sub(r"\([^)]*\)", "", raw_piece).strip(" ,.;:")
        piece = re.sub(
            r"^(?:the|a|an|existing investors?|new investors?|investors?|participant[s]?|participation from|led by|backed by)\s+",
            "",
            piece,
            flags=re.IGNORECASE,
        )
        piece = re.split(
            r"\b(?:that|which|who|for|to|after|before|as|bringing|with|on|in)\b",
            piece,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ,.;:")
        match = re.search(
            r"(?:[A-Z][A-Za-z0-9&'.-]*|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z0-9&'.-]*|[A-Z]{2,}|of|the|&))*",
            piece,
        )
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(0)).strip(" ,.;:")
        normalized = normalize_text(candidate)
        if not candidate or normalized in seen:
            continue
        seen.add(normalized)
        out.append(candidate)
    return out


ORG_ENTITY_MARKERS = {
    "capital",
    "ventures",
    "venture",
    "partners",
    "partner",
    "fund",
    "funds",
    "management",
    "holdings",
    "group",
    "labs",
    "lab",
    "technologies",
    "technology",
    "tech",
    "brands",
    "brand",
    "company",
    "co",
    "corp",
    "corporation",
    "inc",
    "llc",
    "plc",
    "studio",
    "studios",
    "systems",
    "solutions",
    "collective",
}
NON_ENTITY_SINGLE_TOKENS = {"a", "an", "the", "aside", "we", "it", "they", "he", "she", "cpms"}
INVESTOR_PHRASE_MARKERS = [
    "led by",
    "backed by",
    "investors include",
    "participation from",
]
_EXTERNAL_FEED_NORMALIZER_MODULE: Any | None = None
_EXTERNAL_FEED_NORMALIZER_PATH: Path | None = None
_EXTERNAL_FEED_NORMALIZER_MTIME_NS: int | None = None
FUNDING_SENTENCE_PHRASES = [
    "announced it raised",
    "raised",
    "secured",
    "closed",
]
MA_SENTENCE_PHRASES = [
    "merging with",
    "to acquire",
    "acquired",
    "acquires",
    "buying",
]


def _classify_entity_type(name: str) -> str:
    cleaned = _clean_optional_render_text(name)
    if not cleaned:
        return ""
    tokens = [token.strip(" ,.;:") for token in re.findall(r"[A-Za-z0-9&'.-]+", cleaned) if token.strip(" ,.;:")]
    if not tokens:
        return ""
    lower_tokens = {normalize_text(token) for token in tokens}
    if any(token in ORG_ENTITY_MARKERS for token in lower_tokens):
        return "ORGANIZATION"
    if any(re.fullmatch(r"[A-Z]{2,}", token) for token in tokens):
        return "ORGANIZATION"
    if len(tokens) >= 2 and all(re.fullmatch(r"[A-Z][A-Za-z'.-]*", token) for token in tokens):
        return "PERSON"
    return "ORGANIZATION"


def _extract_typed_entities(text: str) -> list[dict[str, Any]]:
    snippet = str(text or "")
    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9&'.-]*|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z0-9&'.-]*|[A-Z]{2,}|&)){0,4}\b"
    )
    for match in pattern.finditer(snippet):
        candidate = re.sub(r"\s+", " ", match.group(0)).strip(" ,.;:")
        if not candidate:
            continue
        candidate_tokens = [normalize_text(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", candidate)]
        if len(candidate_tokens) == 1 and candidate_tokens[0] in NON_ENTITY_SINGLE_TOKENS:
            continue
        entity_type = _classify_entity_type(candidate)
        if not entity_type:
            continue
        key = (normalize_text(candidate), match.start())
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "text": candidate,
                "type": entity_type,
                "start": match.start(),
                "end": match.end(),
            }
        )
    return entities


def _split_sentences(text: str) -> list[str]:
    snippet = str(text or "").strip()
    if not snippet:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", snippet) if part.strip()]


def _find_funding_anchor_index(sentences: list[str]) -> int:
    for idx, sentence in enumerate(sentences):
        haystack = normalize_text(sentence)
        if any(phrase in haystack for phrase in FUNDING_SENTENCE_PHRASES):
            return idx
    return -1


def _build_funding_context(article_text: str, summary: str, title: str) -> dict[str, Any]:
    for source_name, raw_text in (("article_text", article_text), ("summary", summary), ("title", title)):
        sentences = _split_sentences(raw_text)
        if not sentences:
            continue
        anchor_idx = _find_funding_anchor_index(sentences)
        if anchor_idx < 0:
            continue
        start = max(0, anchor_idx - 1)
        end = min(len(sentences), anchor_idx + 2)
        context_sentences = []
        for idx in range(start, end):
            context_sentences.append(
                {
                    "text": sentences[idx],
                    "distance": abs(idx - anchor_idx),
                    "is_anchor": idx == anchor_idx,
                    "relative": idx - anchor_idx,
                }
            )
        return {
            "source": source_name,
            "anchor_sentence": sentences[anchor_idx],
            "sentences": context_sentences,
        }
    return {"source": "", "anchor_sentence": "", "sentences": []}


def _find_m_and_a_anchor_index(sentences: list[str]) -> int:
    for idx, sentence in enumerate(sentences):
        haystack = normalize_text(sentence)
        if any(phrase in haystack for phrase in MA_SENTENCE_PHRASES):
            return idx
    return -1


def _build_m_and_a_context(article_text: str, summary: str, title: str) -> dict[str, Any]:
    for source_name, raw_text in (("article_text", article_text), ("summary", summary), ("title", title)):
        sentences = _split_sentences(raw_text)
        if not sentences:
            continue
        anchor_idx = _find_m_and_a_anchor_index(sentences)
        if anchor_idx < 0:
            continue
        return {
            "source": source_name,
            "anchor_sentence": sentences[anchor_idx],
        }
    return {"source": "", "anchor_sentence": ""}


def _find_anchor_phrase(sentence_text: str, phrases: list[str]) -> tuple[str, int]:
    text = str(sentence_text or "")
    lowered = text.lower()
    best_phrase = ""
    best_idx = -1
    for phrase in phrases:
        idx = lowered.find(phrase)
        if idx < 0:
            continue
        if best_idx < 0 or idx < best_idx or (idx == best_idx and len(phrase) > len(best_phrase)):
            best_phrase = phrase
            best_idx = idx
    return best_phrase, best_idx


def _extract_m_and_a_parties(item: dict[str, Any]) -> tuple[str, str]:
    context = _build_m_and_a_context(
        str(item.get("article_text", "")),
        str(item.get("summary", "")),
        str(item.get("title", "")),
    )
    anchor_sentence = str(context.get("anchor_sentence", "")).strip()
    if not anchor_sentence:
        return "", ""
    anchor_phrase, anchor_idx = _find_anchor_phrase(anchor_sentence, MA_SENTENCE_PHRASES)
    if not anchor_phrase or anchor_idx < 0:
        return "", ""
    phrase_end = anchor_idx + len(anchor_phrase)
    org_entities = [
        entity
        for entity in _extract_typed_entities(anchor_sentence)
        if str(entity.get("type", "")) == "ORGANIZATION"
    ]
    if not org_entities:
        return "", ""
    acquirer_entity: dict[str, Any] | None = None
    target_entity: dict[str, Any] | None = None
    for entity in org_entities:
        entity_end = int(entity.get("end", 0))
        if entity_end <= anchor_idx:
            acquirer_entity = entity
    for entity in org_entities:
        entity_start = int(entity.get("start", 0))
        if entity_start >= phrase_end:
            target_entity = entity
            break
    acquirer = str(acquirer_entity.get("text", "")).strip() if isinstance(acquirer_entity, dict) else ""
    target = str(target_entity.get("text", "")).strip() if isinstance(target_entity, dict) else ""
    if not acquirer or not target:
        return "", ""
    if normalize_text(acquirer) == normalize_text(target):
        return "", ""
    return acquirer, target


def _looks_like_person_fragment(candidate: str, context: dict[str, Any]) -> bool:
    target = normalize_text(candidate)
    if not target:
        return False
    candidate_tokens = [normalize_text(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", str(candidate or ""))]
    if len(candidate_tokens) != 1:
        return False
    all_text = " ".join(
        str(sentence_meta.get("text", "")).strip()
        for sentence_meta in context.get("sentences", [])
        if str(sentence_meta.get("text", "")).strip()
    )
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", all_text):
        full_tokens = [normalize_text(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", match.group(1))]
        if target in full_tokens:
            return True
    for sentence_meta in context.get("sentences", []):
        sentence_text = str(sentence_meta.get("text", "")).strip()
        for entity in _extract_typed_entities(sentence_text):
            if str(entity.get("type", "")) != "PERSON":
                continue
            entity_tokens = [normalize_text(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", str(entity.get("text", "")))]
            if len(entity_tokens) < 2:
                continue
            if target in entity_tokens:
                return True
    return False


def _looks_like_person_fragment_in_text(candidate: str, text: str) -> bool:
    target = normalize_text(candidate)
    if not target:
        return False
    candidate_tokens = [normalize_text(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", str(candidate or ""))]
    if len(candidate_tokens) != 1:
        return False
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", str(text or "")):
        full_tokens = [normalize_text(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", match.group(1))]
        if target in full_tokens:
            return True
    return False


def _trim_investor_clause(sentence_text: str) -> str:
    text = str(sentence_text or "")
    lowered = text.lower()
    cut_at = -1
    for marker in INVESTOR_PHRASE_MARKERS:
        idx = lowered.find(marker)
        if idx >= 0 and (cut_at < 0 or idx < cut_at):
            cut_at = idx
    if cut_at >= 0:
        return text[:cut_at].strip(" ,.;:")
    return text


def _org_entities_for_sentence(sentence_text: str, context: dict[str, Any], *, trim_investor_clause: bool) -> list[dict[str, Any]]:
    text = _trim_investor_clause(sentence_text) if trim_investor_clause else str(sentence_text or "")
    out: list[dict[str, Any]] = []
    for entity in _extract_typed_entities(text):
        if str(entity.get("type", "")) != "ORGANIZATION":
            continue
        entity_text = str(entity.get("text", "")).strip()
        if _looks_like_person_fragment(entity_text, context):
            continue
        out.append(entity)
    return out


def _closest_funding_org_entity(context: dict[str, Any]) -> str:
    sentences = context.get("sentences", [])
    if not isinstance(sentences, list) or not sentences:
        return ""
    anchor_sentence = str(context.get("anchor_sentence", "")).strip()
    anchor_lower = anchor_sentence.lower()
    verb_index = len(anchor_sentence) // 2
    for phrase in FUNDING_SENTENCE_PHRASES:
        idx = anchor_lower.find(phrase)
        if idx >= 0:
            verb_index = idx
            break
    best_name = ""
    best_key: tuple[int, int] | None = None
    for sentence_meta in sentences:
        sentence_text = str(sentence_meta.get("text", "")).strip()
        distance_bucket = int(sentence_meta.get("distance", 1))
        is_anchor = bool(sentence_meta.get("is_anchor"))
        if not is_anchor:
            continue
        for entity in _org_entities_for_sentence(sentence_text, context, trim_investor_clause=True):
            entity_text = str(entity.get("text", "")).strip()
            if is_anchor:
                position_penalty = abs(int(entity.get("start", 0)) - verb_index)
            else:
                position_penalty = 10_000 + int(entity.get("start", 0))
            key = (distance_bucket, position_penalty)
            if best_key is None or key < best_key:
                best_key = key
                best_name = entity_text
    if best_name:
        return best_name
    anchor_sentence = str(context.get("anchor_sentence", "")).strip()
    anchor_lower = anchor_sentence.lower()
    if "the company" not in anchor_lower and " it raised" not in anchor_lower and not anchor_lower.startswith("it "):
        return ""
    previous_candidates: list[dict[str, Any]] = []
    next_candidates: list[dict[str, Any]] = []
    for sentence_meta in sentences:
        if bool(sentence_meta.get("is_anchor")):
            continue
        relative = int(sentence_meta.get("relative", 0))
        sentence_text = str(sentence_meta.get("text", "")).strip()
        candidates = _org_entities_for_sentence(sentence_text, context, trim_investor_clause=False)
        if relative < 0:
            previous_candidates.extend(candidates)
        elif relative > 0:
            next_candidates.extend(candidates)
    if previous_candidates:
        return str(previous_candidates[-1].get("text", "")).strip()
    if next_candidates:
        return str(next_candidates[0].get("text", "")).strip()
    return ""


def _entity_matches_person(candidate: str, context: dict[str, Any]) -> bool:
    target = normalize_text(candidate)
    if not target:
        return False
    for sentence_meta in context.get("sentences", []):
        sentence_text = str(sentence_meta.get("text", "")).strip()
        for entity in _extract_typed_entities(sentence_text):
            if str(entity.get("type", "")) != "PERSON":
                continue
            entity_text = str(entity.get("text", "")).strip()
            entity_norm = normalize_text(entity_text)
            if target == entity_norm or target in entity_norm or entity_norm in target:
                return True
    return False


def _enforce_funding_primary_entity(item: dict[str, Any], company: str, event_type: str, amount: str) -> tuple[str, str]:
    if event_type != "funding_round":
        return company, event_type
    normalized_amount = _normalize_amount_text(amount)
    if not normalized_amount:
        return company, event_type
    context = _build_funding_context(
        str(item.get("article_text", "")),
        str(item.get("summary", "")),
        str(item.get("title", "")),
    )
    closest_org = _closest_funding_org_entity(context)
    company_text = _clean_optional_render_text(company)
    company_type = _classify_entity_type(company_text)
    broader_text = " ".join(
        part for part in [
            str(item.get("title", "")).strip(),
            str(item.get("summary", "")).strip(),
            str(item.get("article_text", "")).strip(),
        ] if part
    )
    if not closest_org:
        item["_funding_entity_downgrade_reason"] = "funding entity downgraded: no valid organization passed funding validation"
        return company_text, "consumer_industry_news"
    if (
        _entity_matches_person(company_text, context)
        or _looks_like_person_fragment_in_text(company_text, broader_text)
        or company_type == "PERSON"
    ):
        return closest_org, event_type
    if not company_text or company_type != "ORGANIZATION":
        return closest_org, event_type
    return company_text, event_type


def _extract_investor_list(article_text: str) -> str:
    text = str(article_text or "").strip()
    if not text:
        return ""
    phrases = [
        "led by",
        "backed by",
        "investors include",
        "participation from",
    ]
    investors: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        for match in re.finditer(rf"{re.escape(phrase)}\s+([^.;\n]{{1,240}})", text, flags=re.IGNORECASE):
            segment = match.group(1).strip()
            segment = re.split(
                r"\b(?:to support|to accelerate|for the round|for this round|bringing|which|who)\b",
                segment,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" ,.;:")
            for entity in _extract_typed_entities(segment):
                if str(entity.get("type", "")) != "ORGANIZATION":
                    continue
                investor = str(entity.get("text", "")).strip()
                normalized = normalize_text(investor)
                if normalized in seen:
                    continue
                seen.add(normalized)
                investors.append(investor)
    return ", ".join(investors)


def _extract_new_company_candidate(text: str) -> str:
    snippet = str(text or "").strip()
    if not snippet:
        return ""
    lower_snippet = snippet.lower()
    verb_markers = [
        "called",
        "named",
        "launches",
        "launched",
        "announces",
        "announced",
        "unveils",
        "unveiled",
        "introduces",
        "introduced",
    ]
    name_pattern = r"([A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,4})"
    for marker in verb_markers:
        idx = lower_snippet.find(marker)
        if idx < 0:
            continue
        tail = snippet[idx + len(marker) :].lstrip(" ,:-")
        tail = re.split(r"[.!?;\n]", tail, maxsplit=1)[0].strip()
        match = re.search(name_pattern, tail)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:")
    return ""


def _resolve_founder_announcement_company(
    *,
    title: str,
    summary: str,
    article_text: str,
    current_company: str,
    current_event_type: str,
) -> tuple[str, str]:
    combined_text = " ".join(part for part in [article_text, title, summary] if str(part).strip())
    if not combined_text:
        return current_company, current_event_type
    existing_company = ""
    founder_of_match = re.search(
        r"(?:founder|co-founder|founder and ceo|ceo)\s+of\s+([A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,4})",
        combined_text,
    )
    if founder_of_match:
        existing_company = re.sub(r"\s+", " ", founder_of_match.group(1)).strip(" ,.;:")
    else:
        possessive_match = re.search(
            r"([A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,4})['\u2019]s\s+(?:[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){0,3})",
            title,
        )
        if possessive_match:
            existing_company = re.sub(r"\s+", " ", possessive_match.group(1)).strip(" ,.;:")
    if not existing_company:
        return current_company, current_event_type
    new_company = _extract_new_company_candidate(article_text) or _extract_new_company_candidate(title) or _extract_new_company_candidate(summary)
    if new_company and normalize_text(new_company) != normalize_text(existing_company):
        return new_company, current_event_type
    if normalize_text(current_company) == normalize_text(existing_company) and current_event_type in {"funding_round", "m_and_a_transaction"}:
        return current_company, "consumer_industry_news"
    return current_company, current_event_type


def _derive_news_company_label(*, title: str, summary: str, article_text: str) -> str:
    for raw_text in (summary, title, article_text):
        snippet = str(raw_text or "").strip()
        if not snippet:
            continue
        for entity in _extract_typed_entities(snippet):
            if str(entity.get("type", "")) != "ORGANIZATION":
                continue
            candidate = _clean_optional_render_text(entity.get("text", ""))
            if candidate:
                return candidate
    title_text = _clean_optional_render_text(title)
    if title_text:
        return re.sub(r"\s+", " ", title_text)[:160].rstrip(" ,.;:")
    summary_text = _clean_optional_render_text(summary)
    if summary_text:
        return re.sub(r"\s+", " ", summary_text)[:160].rstrip(" ,.;:")
    return ""


BAD_COMPANY_LABELS = {
    "in",
    "friday",
    "seed",
    "pre-seed",
    "million",
    "billion",
    "ai",
    "ai-powered",
    "ai-driven",
    "b2b",
}


def _company_value_appears_in_text(text: str, value: str) -> bool:
    snippet = str(text or "").strip()
    target = str(value or "").strip()
    if not snippet or not target:
        return False
    tokens = [re.escape(token) for token in re.findall(r"[A-Za-z0-9&'.-]+", target) if token]
    if not tokens:
        return False
    pattern = r"\b" + r"\s+".join(tokens) + r"\b"
    return re.search(pattern, snippet, flags=re.IGNORECASE) is not None


def _is_invalid_company_label(value: str) -> bool:
    text = _clean_optional_render_text(value)
    if not text:
        return True
    normalized = normalize_text(text)
    if normalized in BAD_COMPANY_LABELS:
        return True
    if normalized.endswith("-based"):
        return True
    if len(re.findall(r"[A-Za-z0-9&'.-]+", text)) <= 1 and normalized in {"wales", "cambridge"}:
        return True
    return False


def _derive_title_company_label(title: str) -> str:
    full_title = _clean_optional_render_text(title)
    if not full_title:
        return ""
    title_segment = full_title.split(":", 1)[-1].strip() if ":" in full_title else full_title
    new_announcement_match = re.match(
        r"^([A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,4})(?:['\u2019\?]s)?\s+New\b",
        title_segment,
    )
    if new_announcement_match:
        return re.sub(r"\s+", " ", new_announcement_match.group(1)).strip(" ,.;:")
    possessive_match = re.match(
        r"^([A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,4})['\u2019\?]s\b",
        title_segment,
    )
    if possessive_match:
        return re.sub(r"\s+", " ", possessive_match.group(1)).strip(" ,.;:")
    for pattern in [
        r"^(.+?)\s+Raises\b",
        r"^(.+?)\s+Raise\b",
        r"^(.+?)\s+Acquires\b",
        r"^(.+?)\s+Acquire\b",
        r"^(.+?)\s+Caps\b",
        r"^(.+?)\s+Closes\b",
        r"^(.+?)\s+Completes\b",
    ]:
        match = re.match(pattern, title_segment, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_optional_render_text(match.group(1))
        if candidate and not _is_invalid_company_label(candidate):
            return candidate
    for entity in _extract_typed_entities(title_segment):
        if str(entity.get("type", "")) != "ORGANIZATION":
            continue
        candidate = _clean_optional_render_text(entity.get("text", ""))
        if candidate and not re.search(r"\d", candidate) and not _is_invalid_company_label(candidate):
            return candidate
    return ""


def _render_required_text(event: dict[str, Any], field_name: str, *, event_type: str) -> str:
    text = _clean_optional_render_text(event.get(field_name, ""))
    if not text:
        raise RuntimeError(f"{event_type} missing required render field: {field_name}")
    return text


def _render_funding_line(event: dict[str, Any], *, source_value: str, require_source: bool) -> str:
    company = _render_required_text(event, "company", event_type="funding_round")
    amount = _normalize_amount_text(event.get("amount", ""))
    round_name = _clean_optional_render_text(event.get("round", ""))
    investors = _clean_optional_render_text(event.get("investors", ""))
    source_text = _clean_optional_render_text(source_value)
    if require_source and not source_text:
        raise RuntimeError("funding_round missing required render field: source")
    if amount:
        headline = f"{company} raised {amount}"
        if round_name:
            headline += f" in {round_name}"
    else:
        headline = f"{company} announced a funding round"
    headline += "."
    parts = [headline]
    if investors:
        parts.append(f"Investors: {investors}.")
    if source_text:
        parts.append(f"Source: {source_text}")
    return " ".join(parts)


def _render_ma_line(event: dict[str, Any], *, source_value: str, require_source: bool) -> str:
    company = _clean_optional_render_text(event.get("acquirer", "")) or _render_required_text(event, "company", event_type="m_and_a_transaction")
    target = _clean_optional_render_text(event.get("target", "")) or _clean_optional_render_text(event.get("counterparty", ""))
    source_text = _clean_optional_render_text(source_value)
    if require_source and not source_text:
        raise RuntimeError("m_and_a_transaction missing required render field: source")
    if target:
        headline = f"{company} acquired {target}."
    else:
        headline = f"{company} announced an M&A transaction."
    parts = [headline]
    if source_text:
        parts.append(f"Source: {source_text}")
    return " ".join(parts)


def _finalize_classified_event(item: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title", "")).strip()
    summary = str(item.get("summary", "")).strip()
    article_text = str(item.get("article_text", "")).strip()
    company, event_type = _resolve_founder_announcement_company(
        title=title,
        summary=summary,
        article_text=article_text,
        current_company=str(validated.get("company", "")).strip(),
        current_event_type=str(validated.get("event_type", "")).strip(),
    )
    company, event_type = _enforce_funding_primary_entity(
        item,
        company,
        event_type,
        str(validated.get("amount", "")),
    )
    investors = ""
    if event_type == "funding_round":
        investors = _extract_investor_list(article_text) or _clean_optional_render_text(validated.get("investors", ""))
    amount = _normalize_amount_text(validated.get("amount", ""))
    if event_type == "funding_round" and not amount:
        item["_funding_amount_downgrade_reason"] = "funding entity downgraded: funding_round missing required normalized amount"
        event_type = "consumer_industry_news"
    acquirer = ""
    target = ""
    if event_type == "m_and_a_transaction":
        acquirer, target = _extract_m_and_a_parties(item)
        if not acquirer or not target:
            event_type = "consumer_industry_news"
        else:
            company = acquirer
    title_company = _derive_title_company_label(title)
    if title_company and normalize_text(title_company) != normalize_text(company):
        if _is_invalid_company_label(company) or not _company_value_appears_in_text(title, company):
            company = title_company
    company = _clean_optional_render_text(company)
    if not company and event_type == "consumer_industry_news":
        company = _derive_news_company_label(
            title=title,
            summary=summary,
            article_text=article_text,
        )
    if not company:
        raise AIValidationError("classification resolved to missing usable company")
    finalized = dict(validated)
    finalized["company"] = company
    finalized["event_type"] = event_type
    finalized["amount"] = amount
    finalized["round"] = _clean_optional_render_text(validated.get("round", ""))
    finalized["investors"] = investors
    finalized["acquirer"] = acquirer if event_type == "m_and_a_transaction" else ""
    finalized["target"] = target if event_type == "m_and_a_transaction" else ""
    finalized["counterparty"] = target if event_type == "m_and_a_transaction" else ""
    if event_type == "consumer_industry_news":
        finalized["amount"] = ""
        finalized["round"] = ""
        finalized["investors"] = ""
        finalized["acquirer"] = ""
        finalized["target"] = ""
        finalized["counterparty"] = ""
        finalized["amount_usd"] = None
        finalized["amount_currency"] = ""
    else:
        _raw_amount = str(validated.get("amount", "")).strip()
        _num_val, _cur_code = _parse_amount_numeric_and_currency(_raw_amount)
        finalized["amount_usd"] = _num_val
        finalized["amount_currency"] = _cur_code
    return finalized


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


@traceable
def load_json_file(path: Path) -> Any:
    if not path.exists():
        raise RuntimeError(f"required file missing: {path}")
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise RuntimeError(f"required file is empty: {path}")
    return json.loads(text)



def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


@traceable
def required_obj(parent: dict, key: str) -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"required object missing: {key}")
    return value


@traceable
def required_text(parent: dict, key: str) -> str:
    value = str(parent.get(key, "")).strip()
    if not value:
        raise RuntimeError(f"required text missing: {key}")
    return value


@traceable
def required_list(parent: dict, key: str) -> list:
    value = parent.get(key)
    if not isinstance(value, list):
        raise RuntimeError(f"required list missing: {key}")
    return value


@traceable
def resolve_path(value: str, config_path: Path) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return (config_path.resolve().parent / p).resolve()


def _output_timestamp_label(now: datetime | None = None) -> str:
    current = now if now is not None else datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _timestamped_output_path(path: Path, timestamp_label: str) -> Path:
    suffix = path.suffix
    if suffix:
        return path.with_name(f"{path.stem}_{timestamp_label}{suffix}")
    return path.with_name(f"{path.name}_{timestamp_label}")


def _extract_title_for_filename(markdown_text: str) -> str:
    """Extract title from markdown and create filesystem-safe filename."""
    lines = markdown_text.strip().split('\n')
    if not lines:
        return None

    # Get first line (should be the title like "# Consumer VC Weekly — March 6–12, 2026")
    title_line = lines[0].strip()

    # Remove markdown heading markers
    title = title_line.lstrip('#').strip()

    # Replace em dash with regular dash
    title = title.replace('—', '-').replace('–', '-')

    # Remove or replace invalid filesystem characters
    # Windows invalid chars: < > : " / \ | ? *
    for char in '<>:"/\\|?*':
        title = title.replace(char, '')

    # Replace multiple spaces with single space
    title = ' '.join(title.split())

    return title if title else None


@dataclass
class RunMetrics:
    total_sources: int = 0
    active_sources: int = 0
    failed_sources: int = 0
    total_items_seen: int = 0
    new_items: int = 0
    duplicate_records: int = 0
    discarded_prequal: int = 0
    discarded_irrelevant: int = 0
    created_events: int = 0
    updated_events: int = 0
    revision_events: int = 0
    slack_posts: int = 0
    slack_alerts: int = 0
    email_summaries: int = 0


class RunStore:
    def __init__(self, db_path: Path, activity_log_path: Path) -> None:
        self.db_path = db_path
        self.activity_log_path = activity_log_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.activity_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._append_activity(
            run_id="-",
            level="info",
            stage="init",
            message=f"run store initialized db={self.db_path}",
        )
        with sqlite3.connect(str(self.db_path), timeout=30) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs(
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    record_key TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _append_activity(
        self,
        run_id: str,
        level: str,
        stage: str,
        message: str,
        source_id: str = "",
        record_key: str = "",
    ) -> None:
        safe_message = str(message).replace("\n", "\\n")
        prefix = "\n" if self.activity_log_path.exists() and self.activity_log_path.stat().st_size > 0 else ""
        line = (
            f"{prefix}"
            f"{utc_now_iso()} | run_id={run_id} | level={level} | stage={stage} "
            f"| source_id={source_id or '-'} | record_key={record_key or '-'} | message={safe_message}\n"
        )
        with self.activity_log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def start_run(self, mode: str) -> str:
        run_id = f"consumer_vc_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        with sqlite3.connect(str(self.db_path), timeout=30) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, mode, started_at, status) VALUES(?,?,?,?)",
                (run_id, mode, utc_now_iso(), "running"),
            )
            conn.commit()
        self._append_activity(run_id=run_id, level="info", stage="start_run", message=f"run started mode={mode}")
        return run_id

    def log(self, run_id: str, level: str, stage: str, message: str, source_id: str = "", record_key: str = "") -> None:
        with sqlite3.connect(str(self.db_path), timeout=30) as conn:
            conn.execute(
                """
                INSERT INTO run_events(run_id, ts, level, stage, source_id, record_key, message)
                VALUES(?,?,?,?,?,?,?)
                """,
                (run_id, utc_now_iso(), level, stage, source_id, record_key, message),
            )
            conn.commit()
        self._append_activity(
            run_id=run_id,
            level=level,
            stage=stage,
            message=message,
            source_id=source_id,
            record_key=record_key,
        )

    def finish(self, run_id: str, status: str, metrics: RunMetrics) -> None:
        with sqlite3.connect(str(self.db_path), timeout=30) as conn:
            conn.execute(
                """
                UPDATE runs
                SET ended_at=?, status=?, metrics_json=?
                WHERE run_id=?
                """,
                (utc_now_iso(), status, to_json(metrics.__dict__), run_id),
            )
            conn.commit()
        self._append_activity(
            run_id=run_id,
            level="info",
            stage="finish",
            message=f"run finished status={status} metrics={to_json(metrics.__dict__)}",
        )


def normalized_key(value: str) -> str:
    txt = str(value or "").strip().lower()
    txt = re.sub(r"\(primary\)", "", txt)
    return re.sub(r"[^a-z0-9]", "", txt)


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    txt = str(value if value is not None else "").strip().lower()
    return txt in {"1", "true", "yes", "y", "on"}


class AirtableStore:
    def __init__(self, cfg: dict) -> None:
        airtable = required_obj(cfg, "airtable")
        if bool(airtable.get("required")) is not True:
            raise RuntimeError("Airtable is mandatory: airtable.required must be true")
        self.api_key = required_text(airtable, "api_key")
        self.base_id = required_text(airtable, "base_id")
        tables = required_obj(airtable, "tables")
        self.table_sources = required_text(tables, "sources")
        self.table_prompts = required_text(tables, "prompts")
        self.table_runtime_controls = required_text(tables, "runtime_controls")
        self.table_events = required_text(tables, "events")
        self.table_news = str(tables.get("news", "")).strip()
        self.table_revisions = required_text(tables, "revisions")
        self.table_run_logs = required_text(tables, "run_logs")
        self.table_substack_prompt_library = str(tables.get("substack_prompt_library", "")).strip()
        self.table_categories = str(tables.get("categories", "")).strip()
        self.table_article_format = str(tables.get("article_format", "")).strip()
        runtime_cfg = required_obj(cfg, "runtime")
        self.timeout = int(runtime_cfg.get("request_timeout_seconds", 30))
        self._airtable_request_retries = max(1, int(runtime_cfg.get("airtable_request_retries", 3)))
        self._airtable_request_backoff_seconds = max(0.0, float(runtime_cfg.get("airtable_request_backoff_seconds", 0.5)))

        self._table_meta: dict[str, dict] = {}
        self._table_name_by_id: dict[str, str] = {}
        self._table_fields_by_normalized: dict[str, dict[str, str]] = {}
        self._table_field_meta_by_normalized: dict[str, dict[str, dict[str, Any]]] = {}
        self._linked_record_ids_by_table: dict[str, dict[str, str]] = {}
        self._linked_record_names_by_table: dict[str, dict[str, str]] = {}
        self._load_meta()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = 0
        last_error: str | None = None
        for attempt in range(1, self._airtable_request_retries + 1):
            attempts = attempt
            retryable = False
            try:
                resp = requests.request(
                    method=method,
                    url=f"https://api.airtable.com/v0{path}",
                    headers=self._headers(),
                    params=params,
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = f"Request exception for {path}: {exc}"
                retryable = True
            else:
                status = resp.status_code
                if status >= 500:
                    last_error = f"Airtable API error {status} on {path}: {resp.text[:500]}"
                    retryable = True
                elif status >= 300:
                    raise RuntimeError(f"Airtable API error {status} on {path}: {resp.text[:500]}")
                else:
                    text = resp.text or ""
                    if not text.strip():
                        return {}
                    data = resp.json()
                    if not isinstance(data, dict):
                        raise RuntimeError(f"Unexpected Airtable response type for {path}")
                    return data
            if not retryable or attempt == self._airtable_request_retries:
                break
            self._sleep_before_retry(attempt)
        raise RuntimeError(
            f"Airtable request failed after {attempts} attempt(s) on {path}: {last_error or 'unknown error'}"
        )

    def _sleep_before_retry(self, attempt: int) -> None:
        if self._airtable_request_backoff_seconds <= 0:
            return
        delay = self._airtable_request_backoff_seconds * (2 ** (attempt - 1))
        if delay > 0:
            time.sleep(delay)

    def _table_path(self, table_name: str) -> str:
        return f"/{self.base_id}/{quote(table_name, safe='')}"

    def _load_meta(self) -> None:
        data = self._request("GET", f"/meta/bases/{self.base_id}/tables")
        tables = data.get("tables", [])
        if not isinstance(tables, list):
            raise RuntimeError("Invalid Airtable metadata response: tables is not an array")
        by_name: dict[str, dict] = {}
        by_id: dict[str, str] = {}
        for table in tables:
            if not isinstance(table, dict):
                continue
            name = str(table.get("name", "")).strip()
            table_id = str(table.get("id", "")).strip()
            if name:
                by_name[name] = table
                if table_id:
                    by_id[table_id] = name
        for required_name in [
            self.table_sources,
            self.table_prompts,
            self.table_runtime_controls,
            self.table_events,
            self.table_revisions,
            self.table_run_logs,
        ]:
            if required_name not in by_name:
                raise RuntimeError(f"Required Airtable table missing: {required_name}")
        if self.table_news and self.table_news not in by_name:
            raise RuntimeError(f"Required Airtable table missing: {self.table_news}")
        if self.table_substack_prompt_library and self.table_substack_prompt_library not in by_name:
            raise RuntimeError(f"Required Airtable table missing: {self.table_substack_prompt_library}")
        if self.table_article_format and self.table_article_format not in by_name:
            raise RuntimeError(f"Required Airtable table missing: {self.table_article_format}")
        self._table_meta = by_name
        self._table_name_by_id = by_id
        self._table_fields_by_normalized = {}
        self._table_field_meta_by_normalized = {}
        self._linked_record_ids_by_table = {}
        self._linked_record_names_by_table = {}
        for name, table in by_name.items():
            fields = table.get("fields", [])
            field_map: dict[str, str] = {}
            field_meta_map: dict[str, dict[str, Any]] = {}
            if isinstance(fields, list):
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    fname = str(field.get("name", "")).strip()
                    if not fname:
                        continue
                    key = normalized_key(fname)
                    field_map[key] = fname
                    field_meta_map[key] = field
            self._table_fields_by_normalized[name] = field_map
            self._table_field_meta_by_normalized[name] = field_meta_map

    def _resolve_field(self, table_name: str, candidates: list[str], required: bool = False) -> str:
        field_map = self._table_fields_by_normalized.get(table_name, {})
        for candidate in candidates:
            found = field_map.get(normalized_key(candidate))
            if found:
                return found
        if required:
            raise RuntimeError(f"Missing required field in Airtable table {table_name}: one of {candidates}")
        return ""

    def _resolve_field_meta(self, table_name: str, candidates: list[str]) -> dict[str, Any] | None:
        field_meta_map = self._table_field_meta_by_normalized.get(table_name, {})
        for candidate in candidates:
            found = field_meta_map.get(normalized_key(candidate))
            if found:
                return found
        return None

    def _get_primary_field_name(self, table_name: str) -> str:
        table_meta = self._table_meta.get(table_name)
        if not isinstance(table_meta, dict):
            raise RuntimeError(f"Unknown Airtable table metadata: {table_name}")
        primary_field_id = str(table_meta.get("primaryFieldId", "")).strip()
        fields = table_meta.get("fields", [])
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                if str(field.get("id", "")).strip() != primary_field_id:
                    continue
                name = str(field.get("name", "")).strip()
                if name:
                    return name
        raise RuntimeError(f"Primary field metadata missing for Airtable table: {table_name}")

    def _ensure_linked_record_indexes(self, table_name: str) -> None:
        if table_name in self._linked_record_ids_by_table and table_name in self._linked_record_names_by_table:
            return
        primary_field_name = self._get_primary_field_name(table_name)
        ids_by_name: dict[str, str] = {}
        names_by_id: dict[str, str] = {}
        for row in self._list_records(table_name):
            if not isinstance(row, dict):
                continue
            record_id = str(row.get("id", "")).strip()
            fields = row.get("fields", {})
            if not record_id or not isinstance(fields, dict):
                continue
            primary_value = str(fields.get(primary_field_name, "")).strip()
            if not primary_value:
                continue
            ids_by_name[normalize_text(primary_value)] = record_id
            names_by_id[record_id] = primary_value
        self._linked_record_ids_by_table[table_name] = ids_by_name
        self._linked_record_names_by_table[table_name] = names_by_id

    def _resolve_linked_record_ids(self, field_meta: dict[str, Any], value: Any) -> list[str] | None:
        if isinstance(value, list):
            existing_ids = [str(item).strip() for item in value if str(item).strip()]
            if existing_ids and all(item.startswith("rec") for item in existing_ids):
                return existing_ids
            names = [str(item).strip() for item in value if str(item).strip()]
        else:
            text = str(value if value is not None else "").strip()
            if not text:
                return None
            names = [text]
        options = field_meta.get("options", {})
        if not isinstance(options, dict):
            return None
        linked_table_id = str(options.get("linkedTableId", "")).strip()
        linked_table_name = self._table_name_by_id.get(linked_table_id, "")
        if not linked_table_name:
            return None
        self._ensure_linked_record_indexes(linked_table_name)
        ids_by_name = self._linked_record_ids_by_table.get(linked_table_name, {})
        names_by_id = self._linked_record_names_by_table.get(linked_table_name, {})
        primary_field_name = self._get_primary_field_name(linked_table_name)
        resolved_ids: list[str] = []
        for name in names:
            lookup_key = normalize_text(name)
            record_id = ids_by_name.get(lookup_key, "")
            if not record_id:
                created = self._create_record(linked_table_name, {primary_field_name: name})
                record_id = str(created.get("id", "")).strip()
                if not record_id:
                    raise RuntimeError(f"Failed to create linked Airtable record in {linked_table_name} for '{name}'")
                ids_by_name[lookup_key] = record_id
                names_by_id[record_id] = name
            resolved_ids.append(record_id)
        return resolved_ids or None

    def _linked_record_display_value(self, field_meta: dict[str, Any], value: Any) -> str:
        if not isinstance(value, list):
            return str(value if value is not None else "").strip()
        options = field_meta.get("options", {})
        if not isinstance(options, dict):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        linked_table_id = str(options.get("linkedTableId", "")).strip()
        linked_table_name = self._table_name_by_id.get(linked_table_id, "")
        if not linked_table_name:
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        self._ensure_linked_record_indexes(linked_table_name)
        names_by_id = self._linked_record_names_by_table.get(linked_table_name, {})
        names = [names_by_id.get(str(item).strip(), str(item).strip()) for item in value if str(item).strip()]
        return ", ".join(name for name in names if name)

    def _event_type_choice_for_write(self, field_meta: dict[str, Any], value: Any) -> str | None:
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        options = field_meta.get("options", {})
        choices = options.get("choices", []) if isinstance(options, dict) else []
        choice_names = [str(choice.get("name", "")).strip() for choice in choices if isinstance(choice, dict)]
        for choice_name in choice_names:
            if normalized_key(choice_name) == normalized_key(text):
                return choice_name
        aliases = {
            "funding_round": ["Funding", "funding_round"],
            "funding": ["Funding", "funding_round"],
            "m_and_a_transaction": ["M&A", "m_and_a_transaction"],
            "acquisition": ["M&A", "m_and_a_transaction"],
            "merger": ["M&A", "m_and_a_transaction"],
            "consumer_industry_news": ["News", "consumer_industry_news"],
            "industry_news": ["News", "consumer_industry_news"],
            "news": ["News", "consumer_industry_news"],
            "irrelevant": ["Irrelevant", "irrelevant"],
        }
        for alias in aliases.get(text, []):
            for choice_name in choice_names:
                if normalized_key(choice_name) == normalized_key(alias):
                    return choice_name
        return None

    def _event_type_choice_for_read(self, value: Any) -> str:
        text = str(value if value is not None else "").strip()
        if not text:
            return ""
        by_choice = {
            "funding": "funding_round",
            "ma": "m_and_a_transaction",
            "news": "consumer_industry_news",
            "irrelevant": "irrelevant",
        }
        return by_choice.get(normalized_key(text), text)

    def _amount_value_for_write(self, value: Any) -> float | None:
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        lowered = text.lower().replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", lowered)
        if not match:
            return None
        amount = float(match.group(0))
        if "billion" in lowered or " bn" in lowered or lowered.endswith("bn"):
            amount *= 1_000_000_000
        elif "million" in lowered or " mm" in lowered or lowered.endswith("mm"):
            amount *= 1_000_000
        elif "thousand" in lowered or " k" in lowered or lowered.endswith("k"):
            amount *= 1_000
        return round(amount, 2)

    def _read_event_field(
        self,
        fields: dict[str, Any],
        key: str,
        candidates: list[str],
        table_name: str | None = None,
    ) -> str:
        target_table = table_name or self.table_events
        value = self._field_value(fields, candidates, target_table)
        if value is None:
            return ""
        field_meta = self._resolve_field_meta(target_table, candidates)
        field_type = str(field_meta.get("type", "")).strip() if isinstance(field_meta, dict) else ""
        if key == "company" and field_type == "multipleRecordLinks":
            return self._linked_record_display_value(field_meta, value)
        if key == "event_type" and field_type == "singleSelect":
            return self._event_type_choice_for_read(value)
        return str(value).strip()

    def _coerce_event_field_value(
        self,
        key: str,
        candidates: list[str],
        value: Any,
        table_name: str | None = None,
    ) -> Any:
        target_table = table_name or self.table_events
        field_meta = self._resolve_field_meta(target_table, candidates)
        if not isinstance(field_meta, dict):
            return value
        field_type = str(field_meta.get("type", "")).strip()
        if key == "company" and field_type == "multipleRecordLinks":
            return self._resolve_linked_record_ids(field_meta, value)
        if key == "event_type" and field_type == "singleSelect":
            return self._event_type_choice_for_write(field_meta, value)
        if key == "amount" and field_type == "currency":
            return self._amount_value_for_write(value)
        if key == "amount_usd" and field_type in {"number", "currency"}:
            if isinstance(value, (int, float)):
                return float(value)
            return None
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        return value

    def _require_fields(self, table_name: str, required_fields: dict[str, list[str]]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for logical_name, candidates in required_fields.items():
            resolved[logical_name] = self._resolve_field(table_name, candidates, required=True)
        return resolved

    def validate_required_schema(self) -> dict[str, dict[str, str]]:
        schema: dict[str, dict[str, str]] = {}
        schema[self.table_sources] = self._require_fields(
            self.table_sources,
            {
                "id": ["id", "source_id"],
                "name": ["name", "sourcename"],
                "type": ["type", "sourcetype"],
                "url": ["url"],
                "active": ["active"],
            },
        )
        schema[self.table_prompts] = self._require_fields(
            self.table_prompts,
            {
                "key": ["key", "promptname"],
                "text": ["text", "prompttext"],
                "active": ["active"],
            },
        )
        schema[self.table_runtime_controls] = self._require_fields(
            self.table_runtime_controls,
            {
                "key": ["key"],
                "enabled": ["enabled", "value_bool"],
                "active": ["active"],
            },
        )
        schema[self.table_events] = self._require_fields(
            self.table_events,
            {
                "event_id": ["event_id", "eventid"],
                "company": ["company"],
                "event_type": ["event_type", "eventtype"],
                "amount": ["amount"],
                "round": ["round"],
                "investors": ["investors"],
                "event_date": ["event_date", "date"],
                "source_link": ["source_link", "sourceurl"],
                "source_name": ["source_name", "sourcename"],
                "raw_summary": ["raw_summary", "summary"],
                "fingerprint": ["fingerprint"],
            },
        )
        for logical_name, candidates in {
            "acquirer": ["acquirer"],
            "target": ["target"],
        }.items():
            field_name = self._resolve_field(self.table_events, candidates, required=False)
            if field_name:
                schema[self.table_events][logical_name] = field_name
        schema[self.table_revisions] = self._require_fields(
            self.table_revisions,
            {
                "revision_id": ["revision_id", "revisionid"],
                "event_id": ["event_id", "eventid"],
                "old_amount": ["old_amount", "oldamount"],
                "new_amount": ["new_amount", "newamount"],
                "old_investors": ["old_investors", "oldinvestors"],
                "new_investors": ["new_investors", "newinvestors"],
                "changed_at": ["changed_at", "changedat"],
            },
        )
        schema[self.table_run_logs] = self._require_fields(
            self.table_run_logs,
            {
                "run_id": ["run_id", "runid"],
                "ts": ["ts"],
                "mode": ["mode"],
                "metrics": ["metrics"],
            },
        )
        if self.table_substack_prompt_library:
            schema[self.table_substack_prompt_library] = self._require_fields(
                self.table_substack_prompt_library,
                {
                    "name": ["name", "prompt_name", "promptname"],
                    "prompt_text": ["prompt_text", "text", "prompttext"],
                    "is_current": ["is_current", "current", "selected"],
                    "active": ["active"],
                },
            )
        return schema

    def _list_records(self, table_name: str) -> list[dict]:
        out: list[dict] = []
        offset: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if offset:
                params["offset"] = offset
            data = self._request("GET", self._table_path(table_name), params=params)
            rows = data.get("records", [])
            if not isinstance(rows, list):
                raise RuntimeError(f"Invalid records response for table {table_name}")
            for row in rows:
                if isinstance(row, dict):
                    out.append(row)
            next_offset = data.get("offset")
            if not isinstance(next_offset, str) or not next_offset.strip():
                break
            offset = next_offset
        return out

    def _create_record(self, table_name: str, fields: dict[str, Any]) -> dict:
        data = self._request("POST", self._table_path(table_name), payload={"fields": fields})
        return data

    def _update_record(self, table_name: str, record_id: str, fields: dict[str, Any]) -> dict:
        path = f"{self._table_path(table_name)}/{record_id}"
        data = self._request("PATCH", path, payload={"fields": fields})
        return data

    def _field_value(self, fields: dict, candidates: list[str], table_name: str) -> Any:
        fname = self._resolve_field(table_name, candidates, required=False)
        if not fname:
            return None
        return fields.get(fname)

    def load_sources(self) -> list[dict]:
        active_field = self._resolve_field(self.table_sources, ["active"], required=True)
        rows = self._list_records(self.table_sources)
        out: list[dict] = []
        for row in rows:
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(active_field)):
                continue
            source_id = str(self._field_value(fields, ["id", "source_id"], self.table_sources) or row.get("id", "")).strip()
            if not source_id:
                raise RuntimeError("Active source row missing id")
            source_name = str(self._field_value(fields, ["name", "sourcename"], self.table_sources) or source_id).strip()
            source_type = str(self._field_value(fields, ["type", "sourcetype"], self.table_sources) or "").strip()
            source_url = str(self._field_value(fields, ["url"], self.table_sources) or "").strip()
            out.append(
                {
                    "id": source_id,
                    "name": source_name,
                    "type": source_type,
                    "url": source_url,
                    "active": True,
                }
            )
        return out

    def load_prompts(self) -> dict[str, str]:
        active_field = self._resolve_field(self.table_prompts, ["active"], required=True)
        key_field = self._resolve_field(self.table_prompts, ["key", "promptname"], required=True)
        text_field = self._resolve_field(self.table_prompts, ["text", "prompttext"], required=True)
        rows = self._list_records(self.table_prompts)
        out: dict[str, str] = {}
        for row in rows:
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(active_field)):
                continue
            key = str(fields.get(key_field, "")).strip()
            text = str(fields.get(text_field, "")).strip()
            if key and text:
                out[key] = text
        return out

    def load_categories(self) -> list[str]:
        """Load company category names from the Categories table.

        Expects the table to have a field named 'name', 'category', or 'category name'.
        Optionally an 'active' field — if present, only active rows are returned.
        Returns an empty list if the table is not configured or unavailable.
        """
        if not self.table_categories:
            logging.warning("load_categories: table_categories not configured")
            return []
        try:
            name_field = self._resolve_field(
                self.table_categories,
                ["name", "category", "category name", "categoryname"],
                required=True,
            )
        except Exception as exc:
            logging.warning("load_categories: could not resolve name field in %s: %s", self.table_categories, exc)
            return []
        active_field = self._resolve_field(
            self.table_categories, ["active"], required=False
        )
        rows = self._list_records(self.table_categories)
        out: list[str] = []
        for row in rows:
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if active_field and not to_bool(fields.get(active_field, True)):
                continue
            name = str(fields.get(name_field, "")).strip()
            if name:
                out.append(name)
        return out

    def load_article_format(self) -> dict[str, Any]:
        """Load article format configuration and determine active content field.

        Returns dict with:
        - 'active_field': The field name to use for newsletter content
        - 'all_formats': List of all format configs (with fallback order)
        - 'active_format_name': Display name of active format
        """
        if not self.table_article_format:
            logging.warning("load_article_format: table_article_format not configured, using SlackContent as default")
            return {
                "active_field": "SlackContent",
                "active_format_name": "SlackContent (default)",
                "all_formats": [],
            }

        try:
            format_name_field = self._resolve_field(
                self.table_article_format,
                ["format_name", "name"],
                required=True,
            )
            field_name_field = self._resolve_field(
                self.table_article_format,
                ["field_name", "field"],
                required=True,
            )
            is_active_field = self._resolve_field(
                self.table_article_format,
                ["is_active", "active_checkbox"],
                required=False,
            )
            fallback_order_field = self._resolve_field(
                self.table_article_format,
                ["fallback_order", "order"],
                required=False,
            )
            active_field = self._resolve_field(
                self.table_article_format,
                ["active"],
                required=False,
            )
        except Exception as exc:
            logging.warning("load_article_format: could not resolve fields: %s", exc)
            return {
                "active_field": "SlackContent",
                "active_format_name": "SlackContent (error fallback)",
                "all_formats": [],
            }

        rows = self._list_records(self.table_article_format)
        formats: list[dict[str, Any]] = []
        active_field_name = "SlackContent"  # Default
        active_format_name = ""

        for row in rows:
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue

            # Skip inactive rows
            if active_field and not to_bool(fields.get(active_field, True)):
                continue

            format_name = str(fields.get(format_name_field, "")).strip()
            field_name = str(fields.get(field_name_field, "")).strip()
            fallback_order = int(fields.get(fallback_order_field, 999)) if fallback_order_field else 999

            if not field_name:
                continue

            is_active = to_bool(fields.get(is_active_field)) if is_active_field else False

            formats.append({
                "format_name": format_name,
                "field_name": field_name,
                "is_active": is_active,
                "fallback_order": fallback_order,
            })

            if is_active:
                active_field_name = field_name
                active_format_name = format_name

        # Sort by fallback order for fallback chain
        formats.sort(key=lambda x: (not x["is_active"], x["fallback_order"]))

        if not active_format_name:
            active_format_name = f"{active_field_name} (default)"

        return {
            "active_field": active_field_name,
            "active_format_name": active_format_name,
            "all_formats": formats,
        }

    def _article_format_field_names(self) -> list[str]:
        """Resolve article content field names from Article Format config."""
        config = self.load_article_format()
        names: list[str] = []

        active_field = str(config.get("active_field", "")).strip()
        if active_field:
            names.append(active_field)

        for fmt in config.get("all_formats", []):
            if not isinstance(fmt, dict):
                continue
            field_name = str(fmt.get("field_name", "")).strip()
            if field_name and field_name not in names:
                names.append(field_name)

        if "SlackContent" not in names:
            names.append("SlackContent")
        if "AIsummary" not in names:
            names.append("AIsummary")
        return names

    def sync_current_substack_prompt(self) -> dict[str, str]:
        if not self.table_substack_prompt_library:
            return {}

        name_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["name", "prompt_name", "promptname"],
            required=True,
        )
        prompt_text_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["prompt_text", "text", "prompttext"],
            required=True,
        )
        is_current_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["is_current", "current", "selected"],
            required=True,
        )
        active_field = self._resolve_field(self.table_substack_prompt_library, ["active"], required=True)

        selected_rows: list[dict[str, str]] = []
        for row in self._list_records(self.table_substack_prompt_library):
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(active_field)):
                continue
            if not to_bool(fields.get(is_current_field)):
                continue
            prompt_text = str(fields.get(prompt_text_field, "")).strip()
            if not prompt_text:
                raise RuntimeError("Current Substack Prompt Library row is missing prompt_text.")
            selected_rows.append(
                {
                    "record_id": str(row.get("id", "")).strip(),
                    "name": str(fields.get(name_field, "")).strip() or "Unnamed Substack prompt",
                    "prompt_text": prompt_text,
                }
            )

        if not selected_rows:
            raise RuntimeError(
                "Substack Prompt Library requires exactly one active row with is_current checked; found 0."
            )
        if len(selected_rows) != 1:
            raise RuntimeError(
                "Substack Prompt Library requires exactly one active row with is_current checked; "
                f"found {len(selected_rows)}."
            )

        selected = selected_rows[0]
        prompts_active_field = self._resolve_field(self.table_prompts, ["active"], required=True)
        prompts_key_field = self._resolve_field(self.table_prompts, ["key", "promptname"], required=True)
        prompts_text_field = self._resolve_field(self.table_prompts, ["text", "prompttext"], required=True)

        target_rows: list[dict[str, str]] = []
        for row in self._list_records(self.table_prompts):
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(prompts_active_field)):
                continue
            key = str(fields.get(prompts_key_field, "")).strip()
            if key != "ai_weekly_writer_prompt":
                continue
            target_rows.append(
                {
                    "record_id": str(row.get("id", "")).strip(),
                    "current_text": str(fields.get(prompts_text_field, "")).strip(),
                }
            )

        if not target_rows:
            raise RuntimeError("Active Prompts row with key 'ai_weekly_writer_prompt' is missing.")
        if len(target_rows) != 1:
            raise RuntimeError(
                "Prompts table requires exactly one active row with key 'ai_weekly_writer_prompt'; "
                f"found {len(target_rows)}."
            )

        target = target_rows[0]
        updated = "false"
        if target["current_text"] != selected["prompt_text"]:
            self._update_record(
                self.table_prompts,
                target["record_id"],
                {prompts_text_field: selected["prompt_text"]},
            )
            updated = "true"

        return {
            "selected_name": selected["name"],
            "updated_prompts_text": updated,
        }

    def list_substack_prompt_library(self) -> dict[str, Any]:
        if not self.table_substack_prompt_library:
            raise RuntimeError("Substack Prompt Library table is not configured.")
        name_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["name", "prompt_name", "promptname"],
            required=True,
        )
        prompt_text_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["prompt_text", "text", "prompttext"],
            required=True,
        )
        is_current_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["is_current", "current", "selected"],
            required=True,
        )
        active_field = self._resolve_field(self.table_substack_prompt_library, ["active"], required=True)
        options: list[dict[str, Any]] = []
        current_name = ""
        for row in self._list_records(self.table_substack_prompt_library):
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(active_field)):
                continue
            prompt_name = str(fields.get(name_field, "")).strip()
            prompt_text = str(fields.get(prompt_text_field, "")).strip()
            if not prompt_name:
                raise RuntimeError("Active Substack Prompt Library row missing name.")
            if not prompt_text:
                raise RuntimeError(f"Substack Prompt Library row '{prompt_name}' is missing prompt_text.")
            is_current = to_bool(fields.get(is_current_field))
            if is_current:
                if current_name:
                    raise RuntimeError("Substack Prompt Library requires exactly one current active row.")
                current_name = prompt_name
            options.append(
                {
                    "record_id": str(row.get("id", "")).strip(),
                    "name": prompt_name,
                    "is_current": is_current,
                }
            )
        if not options:
            raise RuntimeError("Substack Prompt Library has no active prompt rows.")
        if not current_name:
            raise RuntimeError("Substack Prompt Library requires exactly one active current row.")
        return {"current_name": current_name, "options": options}

    def resolve_substack_prompt_text(self, prompt_name: str) -> dict[str, str]:
        if not self.table_substack_prompt_library:
            raise RuntimeError("Substack Prompt Library table is not configured.")
        target_name = str(prompt_name or "").strip()
        if not target_name:
            raise RuntimeError("prompt_name is required")
        name_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["name", "prompt_name", "promptname"],
            required=True,
        )
        prompt_text_field = self._resolve_field(
            self.table_substack_prompt_library,
            ["prompt_text", "text", "prompttext"],
            required=True,
        )
        active_field = self._resolve_field(self.table_substack_prompt_library, ["active"], required=True)
        matches: list[dict[str, str]] = []
        for row in self._list_records(self.table_substack_prompt_library):
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(active_field)):
                continue
            candidate_name = str(fields.get(name_field, "")).strip()
            if candidate_name != target_name:
                continue
            prompt_text = str(fields.get(prompt_text_field, "")).strip()
            if not prompt_text:
                raise RuntimeError(f"Substack Prompt Library row '{target_name}' is missing prompt_text.")
            matches.append({"name": candidate_name, "prompt_text": prompt_text})
        if not matches:
            raise RuntimeError(f"Substack Prompt Library prompt not found: {target_name}")
        if len(matches) != 1:
            raise RuntimeError(f"Substack Prompt Library prompt name must be unique: {target_name}")
        return matches[0]

    def load_runtime_controls(self) -> dict[str, bool]:
        key_field = self._resolve_field(self.table_runtime_controls, ["key"], required=True)
        enabled_field = self._resolve_field(self.table_runtime_controls, ["enabled", "value_bool"], required=True)
        active_field = self._resolve_field(self.table_runtime_controls, ["active"], required=True)
        rows = self._list_records(self.table_runtime_controls)
        out: dict[str, bool] = {}
        for row in rows:
            fields = row.get("fields", {})
            if not isinstance(fields, dict):
                continue
            if not to_bool(fields.get(active_field)):
                continue
            key = str(fields.get(key_field, "")).strip()
            if not key:
                raise RuntimeError("Active runtime control row missing key")
            out[key] = to_bool(fields.get(enabled_field))
        return out

    @staticmethod
    def _infer_event_type_from_category(event_type: str, category: str, acquirer: str) -> str:
        if event_type:
            return event_type
        cat = normalized_key(category)
        if cat == "funding":
            return "funding_round"
        if cat in {"ma", "merger", "acquisition"}:
            return "m_and_a_transaction"
        if acquirer:
            return "m_and_a_transaction"
        if cat == "news":
            return "consumer_industry_news"
        return event_type

    def _canonical_event_from_record(
        self,
        row: dict,
        table_name: str | None = None,
        article_format_fields: list[str] | None = None,
    ) -> dict:
        fields = row.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}
        target_table = table_name or self.table_events
        target_key = "news" if self.table_news and target_table == self.table_news else "events"
        amount_value = self._read_event_field(fields, "amount", ["amount"], target_table)
        round_value = self._read_event_field(fields, "round", ["round"], target_table)
        investors_text = self._read_event_field(fields, "investors", ["investors"], target_table)
        company_value = self._read_event_field(fields, "company", ["company"], target_table)
        acquirer_value = self._read_event_field(fields, "acquirer", ["acquirer"], target_table)
        target_value = self._read_event_field(fields, "target", ["target"], target_table)
        event_date_value = self._read_event_field(fields, "event_date", ["event_date", "date"], target_table)
        source_link_value = self._read_event_field(fields, "source_link", ["source_link", "sourceurl"], target_table)
        source_name_value = self._read_event_field(fields, "source_name", ["source_name", "sourcename"], target_table)
        raw_title_value = self._read_event_field(fields, "raw_title", ["raw_title"], target_table)
        raw_summary_value = self._read_event_field(fields, "raw_summary", ["raw_summary", "summary"], target_table)
        slack_content_value = self._read_event_field(fields, "SlackContent", ["SlackContent", "slack_content", "slackcontent"], target_table)
        ai_summary_value = self._read_event_field(fields, "AIsummary", ["AIsummary", "aisummary", "ai_summary"], target_table)
        company_description_value = self._read_event_field(
            fields,
            "company_description",
            ["company_description", "companydescription", "Company Description"],
            target_table,
        )
        event_flag_value = "N" if target_key == "news" else "Y"
        investors_list = [item.strip() for item in investors_text.split(",") if item.strip()]
        raw_event_type = self._read_event_field(fields, "event_type", ["event_type", "eventtype"], target_table)
        category_value = self._read_event_field(fields, "category", ["category"], target_table)
        event_type_value = self._infer_event_type_from_category(raw_event_type, category_value, acquirer_value)
        canonical = {
            "__record_id": str(row.get("id", "")).strip(),
            "event_id": self._read_event_field(fields, "event_id", ["event_id", "eventid"], target_table),
            "company": company_value,
            "company_description": company_description_value,
            "acquirer": acquirer_value,
            "target": target_value,
            "event_type": event_type_value,
            "amount": amount_value,
            "round": round_value,
            "investors": investors_text,
            "event_date": event_date_value,
            "category": category_value,
            "source_link": source_link_value,
            "source_name": source_name_value,
            "raw_title": raw_title_value,
            "raw_summary": raw_summary_value,
            "SlackContent": slack_content_value,
            "AIsummary": ai_summary_value,
            "article": "",
            "funding": {
                "amount": amount_value,
                "round": round_value,
                "investors": investors_list,
            },
            "mna": {
                "acquirer": acquirer_value,
                "target": target_value,
                "amount": amount_value,
            },
            "Event Flag": event_flag_value,
            "event_flag": event_flag_value,
            "IsConsumerNews": fields.get("IsConsumerNews", False),
            "fingerprint": self._read_event_field(fields, "fingerprint", ["fingerprint"], target_table),
            "base_fingerprint": self._read_event_field(fields, "base_fingerprint", ["base_fingerprint"], target_table),
            "updated_at": self._read_event_field(fields, "updated_at", ["updated_at"], target_table),
            "created_at": self._read_event_field(fields, "created_at", ["created_at"], target_table),
            "airtable_target_table": target_key,
        }
        if article_format_fields:
            for field_name in article_format_fields:
                resolved_name = str(field_name or "").strip()
                if not resolved_name or resolved_name in canonical:
                    continue
                canonical[resolved_name] = self._read_event_field(
                    fields,
                    resolved_name,
                    [resolved_name],
                    target_table,
                )
        return canonical

    def load_events(self, table_name: str | None = None) -> list[dict]:
        target_table = table_name or self.table_events
        rows = self._list_records(target_table)
        article_format_fields = self._article_format_field_names()
        return [self._canonical_event_from_record(r, target_table, article_format_fields=article_format_fields) for r in rows]

    def load_news(self) -> list[dict]:
        if not self.table_news:
            return []
        return self.load_events(self.table_news)

    def _build_event_fields(
        self,
        row: dict,
        include_event_id: bool = False,
        table_name: str | None = None,
    ) -> dict[str, Any]:
        target_table = table_name or self.table_events
        external_airtable = row.get("airtable")
        if isinstance(external_airtable, dict) and external_airtable:
            out: dict[str, Any] = {}
            field_meta_list = self._table_meta.get(target_table, {}).get("fields", [])
            valid_names = {
                str(field.get("name", "")).strip()
                for field in field_meta_list
                if isinstance(field, dict) and str(field.get("name", "")).strip()
            }
            logical_key_map = {
                "company": "company",
                "eventtype": "event_type",
                "amount": "amount",
            }
            for field_name, value in external_airtable.items():
                actual_name = str(field_name).strip()
                if not actual_name or actual_name not in valid_names:
                    continue
                if value is None:
                    continue
                normalized_name = normalize_text(actual_name)
                logical_key = logical_key_map.get(normalized_name, normalized_name)
                coerced = self._coerce_event_field_value(logical_key, [actual_name], value, target_table)
                if coerced is None:
                    continue
                out[actual_name] = coerced
            # Ensure event_type from the top-level canonical field is written even if the
            # external airtable_payload carried a raw AI value that didn't resolve correctly.
            event_type_field = self._resolve_field(target_table, ["event_type", "eventtype"], required=False)
            if event_type_field and event_type_field not in out:
                raw_et = row.get("event_type")
                if raw_et:
                    coerced_et = self._coerce_event_field_value(
                        "event_type", ["event_type", "eventtype"], raw_et, target_table
                    )
                    if coerced_et is not None:
                        out[event_type_field] = coerced_et
            if include_event_id:
                event_id_field = self._resolve_field(target_table, ["event_id", "eventid"], required=False)
                event_id_value = str(row.get("event_id", "")).strip()
                if event_id_field and event_id_value:
                    out[event_id_field] = event_id_value
            # amount_usd and amount_currency are on the row dict (not in the pre-built
            # airtable payload), so they must be picked up explicitly here.
            for _key, _candidates in (
                ("amount_usd", ["amount_usd", "Amount As Number"]),
                ("amount_currency", ["amount_currency", "Amount Currency"]),
                ("AIsummary", ["AIsummary", "aisummary", "ai_summary"]),
                ("company_description", ["company_description", "companydescription", "Company Description"]),
                ("company_category", ["company_category", "Company Category"]),
                ("valuation", ["valuation", "Valuation"]),
                ("target_prior_raise", ["target_prior_raise", "Target Prior Raise"]),
                ("target_prior_valuation", ["target_prior_valuation", "Target Prior Valuation"]),
            ):
                _fname = self._resolve_field(target_table, _candidates, required=False)
                if not _fname:
                    continue
                _val = row.get(_key)
                if _val is None:
                    continue
                _coerced = self._coerce_event_field_value(_key, _candidates, _val, target_table)
                if _coerced is None:
                    continue
                out[_fname] = _coerced
            return out
        out: dict[str, Any] = {}
        mapping = {
            "company": ["company"],
            "acquirer": ["acquirer"],
            "target": ["target"],
            "event_type": ["event_type", "eventtype"],
            "amount": ["amount"],
            "round": ["round"],
            "investors": ["investors"],
            "event_date": ["event_date", "date"],
            "category": ["category"],
            "source_link": ["source_link", "sourceurl"],
            "source_name": ["source_name", "sourcename"],
            "raw_title": ["raw_title"],
            "raw_summary": ["raw_summary", "summary"],
            "SlackContent": ["SlackContent", "slack_content", "slackcontent"],
            "AIsummary": ["AIsummary", "aisummary", "ai_summary"],
            "company_description": ["company_description", "companydescription", "Company Description"],
            "amount_usd": ["amount_usd", "Amount As Number"],
            "amount_currency": ["amount_currency", "Amount Currency"],
            "company_category": ["company_category", "Company Category"],
            "valuation": ["valuation", "Valuation"],
            "target_prior_raise": ["target_prior_raise", "Target Prior Raise"],
            "target_prior_valuation": ["target_prior_valuation", "Target Prior Valuation"],
            "fingerprint": ["fingerprint"],
            "base_fingerprint": ["base_fingerprint"],
            "updated_at": ["updated_at"],
            "manual_override": ["manual_override"],
            "incorrect_flag": ["incorrect_flag"],
            "created_at": ["created_at"],
        }
        if include_event_id:
            mapping["event_id"] = ["event_id", "eventid"]
        for key, candidates in mapping.items():
            fname = self._resolve_field(target_table, candidates, required=False)
            if not fname:
                continue
            value = row.get(key)
            if value is None:
                continue
            coerced = self._coerce_event_field_value(key, candidates, value, target_table)
            if coerced is None:
                continue
            out[fname] = coerced
        return out

    def _resolve_event_target_table(self, row: dict) -> str:
        target_raw = str(row.get("airtable_target_table", "")).strip()
        if not target_raw:
            raise RuntimeError("event missing required field: airtable_target_table")
        target = normalized_key(target_raw)
        if target == "news":
            if not self.table_news:
                raise RuntimeError("Airtable news table is not configured")
            return self.table_news
        if target == "events":
            return self.table_events
        raise RuntimeError(f"invalid airtable_target_table value: {target_raw}")

    def create_event(self, row: dict) -> dict:
        target_table = self._resolve_event_target_table(row)
        fields = self._build_event_fields(row, include_event_id=True, table_name=target_table)
        created = self._create_record(target_table, fields=fields)
        return self._canonical_event_from_record(created, target_table)

    def update_event(self, row: dict) -> dict:
        record_id = str(row.get("__record_id", "")).strip()
        if not record_id:
            raise RuntimeError("Cannot update Airtable event row without __record_id")
        target_table = self._resolve_event_target_table(row)
        fields = self._build_event_fields(row, include_event_id=False, table_name=target_table)
        updated = self._update_record(target_table, record_id=record_id, fields=fields)
        return self._canonical_event_from_record(updated, target_table)

    def append_revision(self, revision: dict) -> None:
        fields: dict[str, Any] = {}
        for key, candidates in {
            "revision_id": ["revision_id", "revisionid"],
            "event_id": ["event_id", "eventid"],
            "old_amount": ["old_amount", "oldamount"],
            "new_amount": ["new_amount", "newamount"],
            "old_investors": ["old_investors", "oldinvestors"],
            "new_investors": ["new_investors", "newinvestors"],
            "changed_at": ["changed_at", "changedat"],
        }.items():
            fname = self._resolve_field(self.table_revisions, candidates, required=False)
            if fname and key in revision:
                fields[fname] = revision[key]
        self._create_record(self.table_revisions, fields=fields)

    def append_run_log(self, run_log: dict) -> None:
        fields: dict[str, Any] = {}
        for key, candidates in {
            "run_id": ["run_id", "runid"],
            "ts": ["ts"],
            "mode": ["mode"],
            "metrics": ["metrics"],
            "daily_summary_file": ["daily_summary_file", "dailysummaryfile"],
            "weekly_summary_file": ["weekly_summary_file", "weeklysummaryfile"],
            "weekly_substack_draft_file": ["weekly_substack_draft_file", "weeklysubstackdraftfile"],
            "runtime_controls": ["runtime_controls", "runtimecontrols"],
        }.items():
            fname = self._resolve_field(self.table_run_logs, candidates, required=False)
            if not fname or key not in run_log:
                continue
            value = run_log[key]
            if key in {"metrics", "runtime_controls"} and isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=True)
            fields[fname] = value
        self._create_record(self.table_run_logs, fields=fields)


def build_slack_run_digest(events: list[dict[str, Any]]) -> str:
    GROUP_ORDER = [
        ("funding_round",          ":money_with_wings: *Funding Rounds*"),
        ("m_and_a_transaction",    ":handshake: *M&A*"),
        ("consumer_industry_news", ":newspaper: *Consumer News*"),
    ]
    grouped: dict[str, list[str]] = {key: [] for key, _ in GROUP_ORDER}
    ungrouped: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        slack_content = str(event.get("SlackContent", "")).strip()
        if not slack_content:
            raise RuntimeError("slack digest missing SlackContent")
        event_type = str(event.get("event_type", "")).strip()
        if event_type in grouped:
            grouped[event_type].append(slack_content)
        else:
            ungrouped.append(slack_content)

    sections: list[str] = []
    for event_type, label in GROUP_ORDER:
        items = grouped[event_type]
        if items:
            sections.append(f"{label}\n\n" + "\n\n".join(items))
    if ungrouped:
        sections.append(":grey_question: *Other News*\n\n" + "\n\n".join(ungrouped))

    if not sections:
        return ""
    return "\n\n".join(sections)


def build_slack_run_blocks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build Slack Block Kit blocks grouped by event type."""
    GROUP_ORDER = [
        ("funding_round",          ":money_with_wings: Funding Rounds"),
        ("m_and_a_transaction",    ":handshake: M&A"),
        ("consumer_industry_news", ":newspaper: Consumer News"),
    ]
    grouped: dict[str, list[str]] = {key: [] for key, _ in GROUP_ORDER}
    ungrouped: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        slack_content = str(event.get("SlackContent", "")).strip()
        if not slack_content:
            continue
        event_type = str(event.get("event_type", "")).strip()
        if event_type in grouped:
            grouped[event_type].append(slack_content)
        else:
            ungrouped.append(slack_content)

    blocks: list[dict[str, Any]] = []
    first_group = True
    for event_type, label in GROUP_ORDER:
        items = grouped[event_type]
        if not items:
            continue
        if not first_group:
            blocks.append({"type": "divider"})
        first_group = False
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": label, "emoji": True}})
        for item in items:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": item[:3000]}})

    if ungrouped:
        if blocks:
            blocks.append({"type": "divider"})
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": ":grey_question: Other News", "emoji": True}})
        for item in ungrouped:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": item[:3000]}})

    # Slack hard limit: 50 blocks per message.
    # post_run_summary adds 1 summary section + 1 divider before these, so cap at 46
    # to leave room: 46 digest + 1 truncation notice + 1 summary + 1 divider = 49 total.
    if len(blocks) > 46:
        blocks = blocks[:46]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_...additional items truncated_"}})

    return blocks


def _slack_text_contains_malformed_tokens(text: str) -> bool:
    value = str(text or "")
    lower = value.lower()
    return "|[" in value or "](http://" in lower or "](https://" in lower


def _sanitize_slack_text(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    value = re.sub(r"<([^|>]+)\|\[([^>\]]+)>\]\([^)]+\)", r"<\1|\2>", value)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<\2|\1>", value, flags=re.IGNORECASE)
    value = value.replace("|[", "|")
    value = re.sub(r"\]\((https?://)", r" (\1", value, flags=re.IGNORECASE)
    return value


def _slack_plaintext_fallback(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    value = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2 (\1)", value)
    value = re.sub(r"<(https?://[^>]+)>", r"\1", value, flags=re.IGNORECASE)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", value, flags=re.IGNORECASE)
    value = value.replace("|[", "|")
    value = re.sub(r"\]\((https?://)", r" (\1", value, flags=re.IGNORECASE)
    return value


def _prepare_slack_digest_for_post(
    digest_text: str,
    *,
    run_store: "RunStore | None" = None,
    run_id: str = "",
) -> str:
    original = str(digest_text or "").strip()
    if not original:
        return ""

    original_malformed = _slack_text_contains_malformed_tokens(original)
    sanitized = _sanitize_slack_text(original).strip()
    if original_malformed and run_store is not None and run_id:
        run_store.log(
            run_id,
            "warn",
            "slack_post",
            "malformed Slack tokens detected in digest; applying sanitizer",
            source_id="slack",
        )
    if sanitized != original and run_store is not None and run_id:
        run_store.log(
            run_id,
            "warn",
            "slack_post",
            "Slack digest markup adjusted before posting",
            source_id="slack",
        )
    if _slack_text_contains_malformed_tokens(sanitized):
        fallback = _slack_plaintext_fallback(sanitized).strip()
        if run_store is not None and run_id:
            run_store.log(
                run_id,
                "warn",
                "slack_post",
                "Slack digest still malformed after sanitize; using plain-text fallback",
                source_id="slack",
            )
        if _slack_text_contains_malformed_tokens(fallback):
            fallback = fallback.replace("|[", "|")
            fallback = re.sub(r"\]\((https?://)", r" (\1", fallback, flags=re.IGNORECASE)
        return fallback
    return sanitized


def _format_source_failure_error(
    *,
    source_id: str,
    source_name: str,
    source_url: str,
    error_text: str,
    failing_url: str = "",
) -> str:
    parts = [
        f"Source ID: {str(source_id or '').strip()}",
        f"Source Name: {str(source_name or '').strip()}",
        f"Source URL: {str(source_url or '').strip()}",
    ]
    item_url = str(failing_url or "").strip()
    if item_url:
        parts.append(f"Item URL: {item_url}")
    parts.append(f"Reason: {str(error_text or '').strip()}")
    return "\n".join(parts)


class SlackNotifier:
    def __init__(self, cfg: dict, config_path: Path, run_store: RunStore | None = None, run_id: str | None = None) -> None:
        slack = required_obj(cfg, "slack")
        if bool(slack.get("required")) is not True:
            raise RuntimeError("Slack is mandatory for this frame: slack.required must be true")
        self.mode = required_text(slack, "mode").lower()
        self.webhook_url = str(slack.get("webhook_url", "")).strip()
        self.channel = required_text(slack, "default_channel")
        self.secondary_webhook_url = str(slack.get("secondary_webhook_url", "")).strip()
        self.secondary_channel = str(slack.get("secondary_channel", "")).strip()
        self.mock_log_file = resolve_path(required_text(slack, "mock_log_file"), config_path)
        self.timeout = int(required_obj(cfg, "runtime").get("request_timeout_seconds", 30))
        if self.mode not in {"mock", "webhook"}:
            raise RuntimeError("slack.mode must be mock or webhook")
        if self.mode == "webhook" and not self.webhook_url:
            raise RuntimeError("slack.webhook_url required when slack.mode=webhook")
        if bool(self.secondary_webhook_url) != bool(self.secondary_channel):
            raise RuntimeError(
                "slack.secondary_webhook_url and slack.secondary_channel must both be set together"
            )
        self.destinations: list[dict[str, str]] = [
            {
                "channel": self.channel,
                "webhook_url": self.webhook_url,
            }
        ]
        if self.secondary_webhook_url and self.secondary_channel:
            self.destinations.append(
                {
                    "channel": self.secondary_channel,
                    "webhook_url": self.secondary_webhook_url,
                }
            )
        self.run_store = run_store
        self.run_id = run_id or ""
        self.sent_payloads: list[dict[str, Any]] = []

    def _write_mock(self, payload: dict) -> None:
        self.mock_log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.mock_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _log_slack(self, stage: str, message: str) -> None:
        if self.run_store and self.run_id:
            self.run_store.log(self.run_id, "info", stage, message, source_id="slack", record_key="-")

    def post(self, text: str) -> None:
        for destination in self.destinations:
            payload = {
                "channel": destination["channel"],
                "text": text,
                "ts": utc_now_iso(),
                "unfurl_links": False,
                "unfurl_media": False,
            }
            self.sent_payloads.append(dict(payload))
            self._log_slack("slack_request", to_json(payload))
            if self.mode == "mock":
                self._write_mock(payload)
                self._log_slack("slack_response", f"mock write complete channel={destination['channel']}")
                continue
            resp = requests.post(destination["webhook_url"], json=payload, timeout=self.timeout)
            if resp.status_code >= 300:
                raise RuntimeError(
                    f"slack post failed for {destination['channel']} ({resp.status_code}): {resp.text[:200]}"
                )
            self._log_slack("slack_response", f"channel={destination['channel']} status={resp.status_code}")

    def post_blocks(self, blocks: list[dict[str, Any]], fallback_text: str = "") -> None:
        for destination in self.destinations:
            payload = {
                "channel": destination["channel"],
                "blocks": blocks,
                "text": fallback_text or "Consumer VC run summary",
                "unfurl_links": False,
                "unfurl_media": False,
            }
            self.sent_payloads.append(dict(payload))
            self._log_slack("slack_request", to_json(payload))
            if self.mode == "mock":
                self._write_mock(payload)
                self._log_slack("slack_response", f"mock write complete channel={destination['channel']}")
                continue
            resp = requests.post(destination["webhook_url"], json=payload, timeout=self.timeout)
            if resp.status_code >= 300:
                raise RuntimeError(
                    f"slack post failed for {destination['channel']} ({resp.status_code}): {resp.text[:200]}"
                )
            self._log_slack("slack_response", f"channel={destination['channel']} status={resp.status_code}")

    def snapshot_payloads(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.sent_payloads if isinstance(item, dict)]

    def post_event(self, event: dict) -> None:
        text = (
            f"*{event['company']}*\n"
            f"Type: {event['event_type']}\n"
            f"Amount: {event['amount']}\n"
            f"Link: {event['source_link']}"
        )
        self.post(text)

    def post_source_failure(self, source_name: str, err: str) -> None:
        self.post(f":warning: Source ingestion failed\nSource: {source_name}\nError: {err}")

    def post_run_summary(
        self,
        run_id: str,
        status: str,
        metrics: RunMetrics,
        digest_text: str = "",
        digest_blocks: "list[dict[str, Any]] | None" = None,
    ) -> None:
        summary_lines = [
            f"Run ID: {run_id}",
            f"Status: {status}",
            f"Sources processed: {metrics.active_sources}/{metrics.total_sources}",
            f"Created: {metrics.created_events}",
            f"Updated: {metrics.updated_events}",
            f"Duplicates skipped: {metrics.duplicate_records}",
            f"Prequal discarded: {metrics.discarded_prequal}",
            f"Irrelevant discarded: {metrics.discarded_irrelevant}",
            f"Errors: {metrics.failed_sources}",
        ]
        summary_block = "\n".join(summary_lines).strip()

        if digest_blocks is not None:
            # Block Kit path — structured, grouped layout
            all_blocks: list[dict[str, Any]] = []
            if summary_block:
                all_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary_block}})
            if digest_blocks:
                if all_blocks:
                    all_blocks.append({"type": "divider"})
                all_blocks.extend(digest_blocks)
            if all_blocks:
                self.post_blocks(all_blocks, fallback_text=f"Consumer VC — {status}")
            return

        # Plain text fallback (replay-node path or no blocks available)
        digest_block = str(digest_text or "").strip()
        if not summary_block and not digest_block:
            return
        if summary_block and digest_block:
            self.post(f"{summary_block}\n\n{digest_block}")
            return
        self.post(summary_block or digest_block)


def post_slack_error_alert(
    *,
    slack: SlackNotifier | None,
    run_store: RunStore | None,
    run_id: str,
    source_name: str,
    error_text: str,
) -> bool:
    if slack is None:
        return False
    try:
        slack.post_source_failure(source_name=source_name, err=error_text)
        if run_store is not None and run_id:
            run_store.log(
                run_id,
                "info",
                "slack_post",
                "posted error Slack alert",
                source_id=source_name,
            )
        return True
    except Exception as exc:
        if run_store is not None and run_id:
            run_store.log(
                run_id,
                "warn",
                "slack_post",
                f"error Slack alert failed: {exc}",
                source_id=source_name,
            )
        return False


class EmailNotifier:
    def __init__(self, cfg: dict, config_path: Path) -> None:
        email_cfg = required_obj(cfg, "email")
        if bool(email_cfg.get("required")) is not True:
            raise RuntimeError("Email is mandatory for this frame: email.required must be true")
        self.mode = required_text(email_cfg, "mode").lower()
        self.from_email = required_text(email_cfg, "from_email")
        raw_to = email_cfg.get("to_emails", [])
        if isinstance(raw_to, str):
            to_list = [v.strip() for v in raw_to.split(",") if v.strip()]
        elif isinstance(raw_to, list):
            to_list = [str(v).strip() for v in raw_to if str(v).strip()]
        else:
            to_list = []
        if not to_list:
            raise RuntimeError("email.to_emails must contain at least one address")
        self.to_emails = to_list
        self.subject_prefix = str(email_cfg.get("subject_prefix", "Consumer VC")).strip() or "Consumer VC"
        self.mock_log_file = resolve_path(required_text(email_cfg, "mock_log_file"), config_path)
        self.smtp_host = str(email_cfg.get("smtp_host", "")).strip()
        self.smtp_port = int(email_cfg.get("smtp_port", 587))
        self.smtp_username = str(email_cfg.get("smtp_username", "")).strip()
        self.smtp_password = str(email_cfg.get("smtp_password", "")).strip()
        self.gmail_oauth_file = str(email_cfg.get("gmail_oauth_file", "")).strip()
        self.gmail_client_id = str(email_cfg.get("gmail_client_id", "")).strip()
        self.gmail_client_secret = str(email_cfg.get("gmail_client_secret", "")).strip()
        self.gmail_refresh_token = str(email_cfg.get("gmail_refresh_token", "")).strip()
        global_client_id = str(cfg.get("client_id", "")).strip()
        global_client_secret = str(cfg.get("client_secret", "")).strip()
        global_refresh_token = str(cfg.get("refresh_token", "")).strip()
        if self.mode not in {"mock", "smtp", "gmail_api"}:
            raise RuntimeError("email.mode must be mock, smtp, or gmail_api")
        if self.mode == "smtp" and not self.smtp_host:
            raise RuntimeError("email.smtp_host required when email.mode=smtp")
        if self.mode == "gmail_api":
            if self.gmail_oauth_file:
                raise RuntimeError(
                    "email.gmail_oauth_file is not supported; set Gmail OAuth credentials in Global.json "
                    "(email.gmail_client_id/email.gmail_client_secret/email.gmail_refresh_token or "
                    "top-level client_id/client_secret/refresh_token)"
                )
            # Keep explicit email.* values authoritative; use top-level keys only as fallback.
            if not self.gmail_client_id and global_client_id:
                self.gmail_client_id = global_client_id
            if not self.gmail_client_secret and global_client_secret:
                self.gmail_client_secret = global_client_secret
            if not self.gmail_refresh_token and global_refresh_token:
                self.gmail_refresh_token = global_refresh_token
            missing: list[str] = []
            if not self.gmail_client_id:
                missing.append("email.gmail_client_id or client_id")
            if not self.gmail_client_secret:
                missing.append("email.gmail_client_secret or client_secret")
            if not self.gmail_refresh_token:
                missing.append("email.gmail_refresh_token or refresh_token")
            if missing:
                raise RuntimeError(f"Missing required Gmail API email settings: {', '.join(missing)}")

    def _write_mock(self, payload: dict) -> None:
        self.mock_log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.mock_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _email_plain_text(self, body: str) -> str:
        def repl(match: re.Match[str]) -> str:
            url = str(match.group(1) or "").strip()
            label = str(match.group(2) or "").strip()
            if not url:
                return label
            if not label:
                return url
            return f"{label} ({url})"

        return re.sub(r"<([^|>]+)\|([^>]+)>", repl, str(body or ""))

    def _email_html_text(self, body: str) -> str:
        text = str(body or "")
        pattern = re.compile(r"<([^|>]+)\|([^>]+)>")
        parts: list[str] = []
        cursor = 0
        for match in pattern.finditer(text):
            if match.start() > cursor:
                parts.append(html.escape(text[cursor:match.start()]))
            url = html.escape(str(match.group(1) or "").strip(), quote=True)
            label = html.escape(str(match.group(2) or "").strip())
            if url and label:
                parts.append(f'<a href="{url}">{label}</a>')
            elif label:
                parts.append(label)
            elif url:
                parts.append(url)
            cursor = match.end()
        if cursor < len(text):
            parts.append(html.escape(text[cursor:]))
        return "<html><body>" + "".join(parts).replace("\n", "<br>\n") + "</body></html>"

    def _compose_email_message(self, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.from_email
        msg["To"] = ", ".join(self.to_emails)
        msg["Date"] = formatdate(localtime=False)
        msg["Subject"] = subject
        msg.set_content(self._email_plain_text(body))
        msg.add_alternative(self._email_html_text(body), subtype="html")
        return msg

    def _send_smtp(self, subject: str, body: str) -> None:
        msg = self._compose_email_message(subject, body)
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as client:
            client.starttls()
            if self.smtp_username:
                client.login(self.smtp_username, self.smtp_password)
            client.send_message(msg)

    def _send_gmail_api(self, subject: str, body: str) -> None:
        msg = self._compose_email_message(subject, body)

        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.gmail_client_id,
                "client_secret": self.gmail_client_secret,
                "refresh_token": self.gmail_refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if token_response.status_code >= 300:
            raise RuntimeError(
                f"Gmail API token request failed {token_response.status_code}: {str(token_response.text or '')[:300]}"
            )
        token_payload = token_response.json()
        if not isinstance(token_payload, dict):
            raise RuntimeError("Gmail API token response must be an object")
        access_token = str(token_payload.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("Gmail API token response missing access_token")

        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        send_response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw_message},
            timeout=30,
        )
        if send_response.status_code >= 300:
            raise RuntimeError(
                f"Gmail API send failed {send_response.status_code}: {str(send_response.text or '')[:300]}"
            )

    def send_daily_summary(self, run_id: str, content_text: str, metrics: RunMetrics) -> None:
        subject = f"{self.subject_prefix} Daily Summary | {datetime.now(timezone.utc).date().isoformat()}"
        body = (
            f"Run ID: {run_id}\n"
            f"Status: completed\n"
            f"Sources processed: {metrics.active_sources}/{metrics.total_sources}\n"
            f"Created: {metrics.created_events}\n"
            f"Updated: {metrics.updated_events}\n"
            f"Duplicates skipped: {metrics.duplicate_records}\n"
            f"Prequal discarded: {metrics.discarded_prequal}\n"
            f"Irrelevant discarded: {metrics.discarded_irrelevant}\n"
            f"Errors: {metrics.failed_sources}\n\n"
            f"{content_text}"
        )
        payload = {
            "ts": utc_now_iso(),
            "subject": subject,
            "to": self.to_emails,
            "run_id": run_id,
        }
        if self.mode == "mock":
            payload["mode"] = "mock"
            payload["body"] = body
            self._write_mock(payload)
            return
        if self.mode == "smtp":
            self._send_smtp(subject, body)
            return
        if self.mode == "gmail_api":
            self._send_gmail_api(subject, body)
            return
        raise RuntimeError(f"Unsupported email mode: {self.mode}")


def load_config(config_path: Path) -> dict:
    cfg = load_json_file(config_path)
    if not isinstance(cfg, dict):
        raise RuntimeError("Global.json must be an object")
    required_obj(cfg, "runtime")
    required_obj(cfg, "airtable")
    required_obj(cfg, "slack")
    required_obj(cfg, "email")
    required_obj(cfg, "summary")
    required_obj(cfg, "prompts")
    return cfg


def enforce_live_execution_modes(cfg: dict) -> dict[str, str]:
    environment = required_text(cfg, "environment").lower()
    airtable_mode = required_text(required_obj(cfg, "airtable"), "mode").lower()
    slack_mode = required_text(required_obj(cfg, "slack"), "mode").lower()
    email_mode = required_text(required_obj(cfg, "email"), "mode").lower()

    if environment != "live":
        raise RuntimeError("Global.json environment must be 'live' for this run")
    if airtable_mode != "live":
        raise RuntimeError("Global.json airtable.mode must be 'live'")
    if slack_mode != "webhook":
        raise RuntimeError("Global.json slack.mode must be 'webhook'")
    if email_mode not in {"smtp", "gmail_api"}:
        raise RuntimeError("Global.json email.mode must be 'smtp' or 'gmail_api'")

    return {
        "environment": environment,
        "airtable_mode": airtable_mode,
        "slack_mode": slack_mode,
        "email_mode": email_mode,
    }


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"seen_urls_by_source": {}}
    data = load_json_file(state_path)
    if not isinstance(data, dict):
        raise RuntimeError("state file must be an object")
    if "seen_urls_by_source" not in data or not isinstance(data["seen_urls_by_source"], dict):
        data["seen_urls_by_source"] = {}
    return data


def save_state(state_path: Path, state: dict) -> None:
    write_json_file(state_path, state)


def _load_external_feed_normalizer_module() -> Any:
    global _EXTERNAL_FEED_NORMALIZER_MODULE
    global _EXTERNAL_FEED_NORMALIZER_PATH
    global _EXTERNAL_FEED_NORMALIZER_MTIME_NS
    module_path = Path(__file__).resolve().parent / "ParseFeedFile.py"
    if not module_path.exists() or not module_path.is_file():
        raise RuntimeError(f"External feed normalizer not found: {module_path}")
    module_mtime_ns = module_path.stat().st_mtime_ns
    if (
        _EXTERNAL_FEED_NORMALIZER_MODULE is not None
        and _EXTERNAL_FEED_NORMALIZER_PATH == module_path
        and _EXTERNAL_FEED_NORMALIZER_MTIME_NS == module_mtime_ns
    ):
        return _EXTERNAL_FEED_NORMALIZER_MODULE
    spec = importlib.util.spec_from_file_location("consumer_vc_external_feed_normalizer", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load external feed normalizer: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _EXTERNAL_FEED_NORMALIZER_MODULE = module
    _EXTERNAL_FEED_NORMALIZER_PATH = module_path
    _EXTERNAL_FEED_NORMALIZER_MTIME_NS = module_mtime_ns
    return module


def _external_normalizer_settings_from_logic(logic: dict, *, request_timeout_seconds: int) -> dict[str, Any]:
    api_key = str(logic.get("openai_api_key", "")).strip()
    model_name = str(logic.get("ai_model_name", "")).strip()
    if not api_key:
        raise AIValidationError("openai_api_key is empty")
    if not model_name:
        raise AIValidationError("ai_model_name is empty")
    try:
        temperature = float(logic.get("ai_temperature", 0.1))
    except Exception as exc:
        raise AIValidationError("ai_temperature is invalid") from exc
    return {
        "api_key": api_key,
        "model": model_name,
        "temperature": temperature,
        "timeout_ms": max(int(request_timeout_seconds) * 1000, 1000),
        "config_path": "runtime_logic",
        "company_categories": logic.get("company_categories", []),
    }


def _map_external_normalized_ai_to_event(
    *,
    normalized_ai: dict[str, Any],
    title: str,
    body: str,
    source_link: str,
    source_name: str,
    published_date_fallback: str,
) -> dict[str, Any]:
    external_event_type = str(normalized_ai.get("event_type", "")).strip()
    if external_event_type == "funding":
        event_type = "funding_round"
    elif external_event_type in {"acquisition", "merger"}:
        event_type = "m_and_a_transaction"
    else:
        event_type = "consumer_industry_news"

    funding = normalized_ai.get("funding", {})
    if not isinstance(funding, dict):
        funding = {}
    mna = normalized_ai.get("mna", {})
    if not isinstance(mna, dict):
        mna = {}
    investors = funding.get("investors", [])
    if not isinstance(investors, list):
        investors = []
    event_block = normalized_ai.get("event", {})
    if not isinstance(event_block, dict):
        event_block = {}
    event_summary = str(event_block.get("summary", "")).strip()
    event_date = str(event_block.get("published_date", "")).strip() or published_date_fallback
    airtable_payload = normalized_ai.get("airtable", {})
    if not isinstance(airtable_payload, dict):
        airtable_payload = {}
    slack_content = str(airtable_payload.get("SlackContent", "")).strip()
    if not slack_content:
        raise RuntimeError("normalized ai missing required field: airtable.SlackContent")
    airtable_target_table = normalized_key(str(normalized_ai.get("AirtableTargetTable", "")).strip())
    if airtable_target_table not in {"events", "news"}:
        raise RuntimeError("normalized ai missing required field: AirtableTargetTable")
    category_value = str(airtable_payload.get("category", "")).strip()
    article_text = str(normalized_ai.get("article", "")).strip()
    event_flag = str(normalized_ai.get("Event Flag", "")).strip()
    funding_amount = str(funding.get("amount", "")).strip()
    funding_valuation = str(funding.get("valuation", "")).strip()
    funding_round = str(funding.get("round", "")).strip()
    mna_acquirer = str(mna.get("acquirer", "")).strip()
    mna_target = str(mna.get("target", "")).strip()
    mna_amount = str(mna.get("amount", "")).strip()
    mna_target_prior_raise = str(mna.get("target_prior_raise", "")).strip()
    mna_target_prior_valuation = str(mna.get("target_prior_valuation", "")).strip()
    company_category = str(normalized_ai.get("company_category", "")).strip()
    _raw_amount_for_parse = mna_amount if event_type == "m_and_a_transaction" else funding_amount
    if event_type == "consumer_industry_news" or not _raw_amount_for_parse:
        _amount_usd: int | None = None
        _amount_currency: str = ""
    else:
        _amount_usd, _amount_currency = _parse_amount_numeric_and_currency(_raw_amount_for_parse)
    return {
        "company": str(normalized_ai.get("company", "")).strip(),
        "company_description": str(normalized_ai.get("company_description", "")).strip(),
        "acquirer": mna_acquirer,
        "target": mna_target,
        "event_type": event_type,
        "amount": funding_amount,
        "round": funding_round,
        "investors": ", ".join(str(item).strip() for item in investors if str(item).strip()),
        "counterparty": mna_target,
        "event_date": event_date,
        "category": category_value,
        "source_link": source_link,
        "source_name": source_name,
        "raw_title": title,
        "raw_summary": body,
        "summary": event_summary,
        "article": article_text,
        "funding": {
            "amount": funding_amount,
            "round": funding_round,
            "investors": [str(item).strip() for item in investors if str(item).strip()],
        },
        "mna": {
            "acquirer": mna_acquirer,
            "target": mna_target,
            "amount": mna_amount,
        },
        "SlackContent": slack_content,
        "AIsummary": str(normalized_ai.get("AIsummary") or normalized_ai.get("summary", "")).strip(),
        "Event Flag": event_flag,
        "event_flag": event_flag,
        "amount_usd": _amount_usd,
        "amount_currency": _amount_currency,
        "company_category": company_category,
        "valuation": funding_valuation if event_type != "consumer_industry_news" else "",
        "target_prior_raise": mna_target_prior_raise if event_type == "m_and_a_transaction" else "",
        "target_prior_valuation": mna_target_prior_valuation if event_type == "m_and_a_transaction" else "",
        "airtable_target_table": airtable_target_table,
        "airtable": dict(airtable_payload),
    }


def raw_snapshot_dir(run_id: str) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    return RAW_SNAPSHOT_BASE_DIR / safe_run_id


def raw_snapshot_file(run_id: str) -> Path:
    return raw_snapshot_dir(run_id) / "raw_sources.json"


def run_meta_file(run_id: str) -> Path:
    return raw_snapshot_dir(run_id) / "run_meta.json"


def write_raw_snapshot(run_id: str, payload: dict[str, Any]) -> Path:
    if not isinstance(payload, dict):
        raise RuntimeError("raw snapshot payload must be an object")
    path = raw_snapshot_file(run_id)
    write_json_file(path, payload)
    return path


def load_raw_snapshot(run_id: str) -> dict[str, Any]:
    path = raw_snapshot_file(run_id)
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"raw snapshot missing for run_id {run_id}: {path}")
    data = load_json_file(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"raw snapshot must be an object: {path}")
    return data


def write_run_meta(*, run_id: str, timestamp: str, mode: str, source_count: int, raw_snapshot_run_id: str) -> Path:
    raw_path = raw_snapshot_file(raw_snapshot_run_id)
    if not raw_path.exists() or not raw_path.is_file():
        raise RuntimeError(f"raw snapshot missing for run_id {raw_snapshot_run_id}: {raw_path}")
    payload = {
        "run_id": str(run_id),
        "timestamp": str(timestamp),
        "mode": str(mode),
        "source_count": int(source_count),
        "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    }
    path = run_meta_file(run_id)
    write_json_file(path, payload)
    return path


def checkpoint_root_for_config(config_path: Path) -> Path:
    return config_path.resolve().parent / "monitor" / "checkpoints"


def _safe_checkpoint_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())
    if not safe:
        raise RuntimeError("checkpoint id cannot be empty")
    return safe


def save_checkpoint(checkpoint_root: Path, run_id: str, node_id: str, payload: dict[str, Any]) -> Path:
    if not isinstance(payload, dict):
        raise RuntimeError("checkpoint payload must be an object")
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_node_id = _safe_checkpoint_id(node_id)
    checkpoint_path = checkpoint_root / safe_run_id / f"{safe_node_id}.json"
    body = {
        "run_id": safe_run_id,
        "node_id": safe_node_id,
        "saved_at": utc_now_iso(),
        "payload": payload,
    }
    write_json_file(checkpoint_path, body)
    return checkpoint_path


def save_raw_snapshot_checkpoint(checkpoint_root: Path, run_id: str, payload: dict[str, Any]) -> Path:
    if not isinstance(payload, dict):
        raise RuntimeError("raw snapshot checkpoint payload must be an object")
    safe_run_id = _safe_checkpoint_id(run_id)
    checkpoint_path = checkpoint_root / safe_run_id / "raw_sources.json"
    write_json_file(checkpoint_path, payload)
    return checkpoint_path


def _raw_source_extension(raw_format: str) -> str:
    fmt = str(raw_format or "").strip().lower()
    if fmt == "xml":
        return "xml"
    if fmt == "json":
        return "json"
    if fmt == "html":
        return "html"
    return "txt"


def save_raw_source_response_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
    raw_text: str,
    raw_format: str,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    ext = _raw_source_extension(raw_format)
    checkpoint_path = checkpoint_root / safe_run_id / f"!!{safe_source_id}_raw.{ext}"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(str(raw_text or ""), encoding="utf-8")
    return checkpoint_path


def manual_raw_source_response_path(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
    ext: str = "html",
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    normalized_ext = str(ext or "html").strip().lower() or "html"
    return checkpoint_root / safe_run_id / f"!!{safe_source_id}_manual_raw.{normalized_ext}"


def resolve_raw_source_response_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    run_dir = checkpoint_root / safe_run_id
    candidates = sorted(run_dir.glob(f"!!{safe_source_id}_raw.*"))
    if not candidates:
        expected_path = run_dir / f"!!{safe_source_id}_raw.xml"
        raise RuntimeError(f"Raw source file missing for source {source_id}: {expected_path}")
    if len(candidates) > 1:
        joined = ", ".join(str(path) for path in candidates)
        raise RuntimeError(f"Multiple raw source files found for source {source_id}: {joined}")
    return candidates[0]


def _hydrate_manual_source_snapshot_entry(
    *,
    checkpoint_root: Path,
    snapshot_run_id: str,
    source_entry: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(source_entry, dict):
        raise RuntimeError("source entry must be an object")
    source_id = str(source_entry.get("source_id", "")).strip()
    source_name = str(source_entry.get("source_name", source_id)).strip() or source_id
    source_url = str(source_entry.get("source_url", "")).strip()
    raw_items = source_entry.get("raw_items")
    if isinstance(raw_items, list) and raw_items:
        return source_entry
    manual_path = manual_raw_source_response_path(checkpoint_root, snapshot_run_id, source_id, "html")
    if not manual_path.exists() or not manual_path.is_file():
        return source_entry
    manual_html = manual_path.read_text(encoding="utf-8", errors="ignore")
    if not str(manual_html or "").strip():
        raise RuntimeError(f"manual raw source file is empty for source {source_id}: {manual_path}")
    parsed_items = _parse_source_html_items(
        html_text=manual_html,
        source_url=source_url,
        source_name=source_name,
    )
    if _should_transform_html_source_to_rss(source_name=source_name, source_url=source_url):
        canonical_text = _build_rss_xml_from_items(
            source_name=source_name or urlparse(source_url).netloc,
            source_url=source_url,
            items=parsed_items,
        )
        canonical_format = "xml"
    else:
        canonical_text = manual_html
        canonical_format = "html"
    save_raw_source_response_checkpoint(
        checkpoint_root,
        snapshot_run_id,
        source_id,
        canonical_text,
        canonical_format,
    )
    updated = dict(source_entry)
    updated["raw_response_format"] = canonical_format
    updated["raw_items"] = [dict(item) for item in parsed_items if isinstance(item, dict)]
    updated["error"] = ""
    updated["manual_source_file"] = str(manual_path)
    return updated


def save_source_normalized_batch_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
    payload: dict[str, Any],
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    checkpoint_path = checkpoint_root / safe_run_id / f"!!{safe_source_id}_normalized_batch.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(to_json(payload), encoding="utf-8")
    return checkpoint_path


def save_master_normalized_batch_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    payload: dict[str, Any],
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    checkpoint_path = checkpoint_root / safe_run_id / "!!master_normalized_batch.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(to_json(payload), encoding="utf-8")
    return checkpoint_path


def save_source_ecluded_from_run_xml_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
    xml_text: str,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    checkpoint_path = checkpoint_root / safe_run_id / f"!!{safe_source_id}_EcludedFromRun.xml"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(str(xml_text), encoding="utf-8")
    return checkpoint_path


def save_source_feedparser_xml_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
    xml_text: str,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    checkpoint_path = checkpoint_root / safe_run_id / f"!!{safe_source_id}_feedparser.xml"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(str(xml_text), encoding="utf-8")
    return checkpoint_path


def save_source_newspaper3k_xml_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    source_id: str,
    xml_text: str,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_source_id = _safe_checkpoint_id(source_id)
    checkpoint_path = checkpoint_root / safe_run_id / f"!!{safe_source_id}_newspaper3k.xml"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(str(xml_text), encoding="utf-8")
    return checkpoint_path


def save_run_level_library_xml_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    file_name: str,
    xml_text: str,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    if not isinstance(file_name, str) or not file_name.strip():
        raise RuntimeError("file_name is required for run-level library XML checkpoint")
    checkpoint_path = checkpoint_root / safe_run_id / file_name.strip()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(str(xml_text), encoding="utf-8")
    return checkpoint_path


def save_run_level_json_checkpoint(
    checkpoint_root: Path,
    run_id: str,
    file_name: str,
    payload: Any,
) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    if not isinstance(file_name, str) or not file_name.strip():
        raise RuntimeError("file_name is required for run-level JSON checkpoint")
    checkpoint_path = checkpoint_root / safe_run_id / file_name.strip()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return checkpoint_path


def _article_title_preview(value: Any, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    if max_chars is None:
        return text
    max_len = int(max_chars)
    if max_len <= 0:
        return text
    return text[:max_len]


def build_feed_article_summary_text(raw_sources: list[dict[str, Any]]) -> str:
    safe_sources = [entry for entry in raw_sources if isinstance(entry, dict)]
    total_articles = 0
    for source in safe_sources:
        raw_items = source.get("raw_items")
        if isinstance(raw_items, list):
            total_articles += len(raw_items)

    lines: list[str] = [
        "----------------------------------------",
        f"Total Feeds: {len(safe_sources)}",
        f"Total Articles: {total_articles}",
        "Breakdown of each Feed",
    ]

    for source in safe_sources:
        source_name = str(source.get("source_name") or source.get("source_id") or "").strip() or "(unknown source)"
        raw_items = source.get("raw_items")
        source_items = raw_items if isinstance(raw_items, list) else []
        lines.extend(
            [
                "----------------------------",
                f"Feed Name: {source_name}",
                f"Number of Articles: {len(source_items)}",
            ]
        )
        for item in source_items:
            if not isinstance(item, dict):
                continue
            title_preview = _article_title_preview(item.get("title", ""), None)
            article_url = str(item.get("url", "")).strip()
            lines.extend(
                [
                    "-----------------------",
                    f"Title: {title_preview}",
                    f"URL: {article_url}",
                ]
            )
    lines.append("-----------------------")
    return "\n".join(lines) + "\n"


def load_checkpoint(checkpoint_root: Path, run_id: str, node_id: str) -> dict[str, Any]:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_node_id = _safe_checkpoint_id(node_id)
    checkpoint_path = checkpoint_root / safe_run_id / f"{safe_node_id}.json"
    data = load_json_file(checkpoint_path)
    if not isinstance(data, dict):
        raise RuntimeError(f"checkpoint file must be an object: {checkpoint_path}")
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError(f"checkpoint payload missing: {checkpoint_path}")
    return payload


def _active_checkpoint_path(checkpoint_root: Path, run_id: str, node_id: str) -> Path:
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_node_id = _safe_checkpoint_id(node_id)
    return checkpoint_root / safe_run_id / "_active" / f"{safe_node_id}.json"


def save_active_checkpoint(checkpoint_root: Path, run_id: str, node_id: str, payload: dict[str, Any]) -> Path:
    if not isinstance(payload, dict):
        raise RuntimeError("checkpoint payload must be an object")
    safe_run_id = _safe_checkpoint_id(run_id)
    safe_node_id = _safe_checkpoint_id(node_id)
    checkpoint_path = _active_checkpoint_path(checkpoint_root, safe_run_id, safe_node_id)
    body = {
        "run_id": safe_run_id,
        "node_id": safe_node_id,
        "saved_at": utc_now_iso(),
        "scope": "active_branch",
        "payload": payload,
    }
    write_json_file(checkpoint_path, body)
    return checkpoint_path


def cleanup_active_checkpoints(checkpoint_root: Path, run_id: str) -> None:
    safe_run_id = _safe_checkpoint_id(run_id)
    active_dir = checkpoint_root / safe_run_id / "_active"
    if active_dir.exists() and active_dir.is_dir():
        shutil.rmtree(active_dir)


def load_effective_checkpoint(checkpoint_root: Path, run_id: str, node_id: str) -> dict[str, Any]:
    checkpoint_path = _active_checkpoint_path(checkpoint_root, run_id, node_id)
    if checkpoint_path.exists() and checkpoint_path.is_file():
        data = load_json_file(checkpoint_path)
        if not isinstance(data, dict):
            raise RuntimeError(f"checkpoint file must be an object: {checkpoint_path}")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError(f"checkpoint payload missing: {checkpoint_path}")
        return payload
    return load_checkpoint(checkpoint_root, run_id, node_id)


def parse_feed_datetime(value: str) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    try:
        return parse_iso(txt).isoformat()
    except RuntimeError:
        pass
    try:
        dt = parsedate_to_datetime(txt)
    except (TypeError, ValueError):
        return txt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _find_child_text(elem: ET.Element, candidates: list[str]) -> str:
    for child in list(elem):
        tag = str(child.tag).lower()
        for candidate in candidates:
            if tag == candidate or tag.endswith(candidate):
                text = str(child.text or "").strip()
                if text:
                    return text
    return ""


def _parse_rss_atom_items(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"source response is not valid XML feed: {exc}") from exc

    out: list[dict] = []
    item_nodes = root.findall("./channel/item")
    if not item_nodes:
        item_nodes = root.findall(".//{*}entry")
    for item in item_nodes:
        title = _find_child_text(item, ["title"])
        summary = _find_child_text(item, ["description", "summary", "content", "encoded"])
        link = _find_child_text(item, ["link", "id", "guid"])
        if not link:
            for child in list(item):
                tag = str(child.tag).lower()
                if tag == "link" or tag.endswith("link"):
                    href = str(child.attrib.get("href", "")).strip()
                    if href:
                        link = href
                        break
        published = _find_child_text(item, ["pubdate", "published", "updated", "dc:date", "date"])
        out.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": parse_feed_datetime(published),
            }
        )
    return out


def _parse_json_items(payload: Any) -> list[dict]:
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            rows = payload["items"]
        elif isinstance(payload.get("entries"), list):
            rows = payload["entries"]
        else:
            raise RuntimeError("json source must contain array at root, items, or entries")
    else:
        raise RuntimeError("json source response must be an object or array")

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        summary = str(row.get("summary") or row.get("description") or row.get("content") or "").strip()
        link = str(row.get("url") or row.get("link") or row.get("id") or "").strip()
        published = str(row.get("published_at") or row.get("published") or row.get("updated") or row.get("date") or "").strip()
        out.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": parse_feed_datetime(published),
            }
        )
    return out


def _same_site_url(source_url: str, candidate_url: str) -> bool:
    source_host = str(urlparse(source_url).netloc or "").strip().lower().removeprefix("www.")
    candidate_host = str(urlparse(candidate_url).netloc or "").strip().lower().removeprefix("www.")
    if not source_host or not candidate_host:
        return False
    if candidate_host == source_host:
        return True
    if candidate_host.endswith(f".{source_host}") or source_host.endswith(f".{candidate_host}"):
        return True
    return False


def _parse_html_items(html_text: str, source_url: str) -> list[dict]:
    anchor_re = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", flags=re.IGNORECASE | re.DOTALL)
    out: list[dict] = []
    seen_urls: set[str] = set()
    for href, inner in anchor_re.findall(str(html_text or "")):
        raw_href = html.unescape(str(href or "").strip())
        if not raw_href:
            continue
        lowered = raw_href.lower()
        if lowered.startswith("#") or lowered.startswith("javascript:") or lowered.startswith("mailto:") or lowered.startswith("tel:"):
            continue
        resolved_url = str(urljoin(source_url, raw_href)).strip()
        if not resolved_url.startswith("http://") and not resolved_url.startswith("https://"):
            continue
        if not _same_site_url(source_url, resolved_url):
            continue
        if resolved_url in seen_urls:
            continue
        text = re.sub(r"<[^>]+>", " ", str(inner or ""))
        title = re.sub(r"\s+", " ", html.unescape(text)).strip()
        if len(title) < 20:
            continue
        seen_urls.add(resolved_url)
        out.append(
            {
                "title": title,
                "summary": "",
                "url": resolved_url,
                "published_at": "",
            }
        )
        if len(out) >= 200:
            break
    if not out:
        raise RuntimeError("html scrape source returned no usable links")
    return out


def _normalize_source_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _is_businesswire_source(*, source_name: str, source_url: str) -> bool:
    normalized_name = _normalize_source_key(source_name)
    normalized_host = _normalize_source_key(urlparse(str(source_url or "").strip()).netloc.removeprefix("www."))
    return normalized_name == "businesswire" or normalized_host == "businesswirecom"


def _businesswire_title_from_url(article_url: str) -> str:
    path = str(urlparse(article_url).path or "").strip("/")
    if "/en/" in path:
        slug = path.split("/en/", 1)[1]
    else:
        parts = [part for part in path.split("/") if part]
        slug = parts[-1] if parts else ""
    cleaned = re.sub(r"[-_]+", " ", slug).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or article_url


def _parse_businesswire_items(html_text: str, source_url: str) -> list[dict]:
    root = etree.HTML(str(html_text or ""))
    if root is None:
        raise RuntimeError("businesswire html could not be parsed")
    out: list[dict] = []
    seen_urls: set[str] = set()
    anchor_nodes = root.xpath(".//a[@href]")
    for node in anchor_nodes:
        href = html.unescape(str(node.get("href") or "").strip())
        if not href:
            continue
        resolved_url = str(urljoin(source_url, href)).strip()
        if not re.search(r"/news/home/\d+/en/", resolved_url, flags=re.IGNORECASE):
            continue
        if resolved_url in seen_urls:
            continue
        title_text = " ".join(str(node.xpath("string()") or "").split()).strip()
        title = title_text or _businesswire_title_from_url(resolved_url)
        if len(title) < 20:
            title = _businesswire_title_from_url(resolved_url)
        seen_urls.add(resolved_url)
        out.append(
            {
                "title": title,
                "summary": "",
                "url": resolved_url,
                "published_at": "",
            }
        )
    if not out:
        raise RuntimeError("businesswire html returned no usable release links")
    return out


def _parse_source_html_items(*, html_text: str, source_url: str, source_name: str) -> list[dict]:
    if _is_businesswire_source(source_name=source_name, source_url=source_url):
        return _parse_businesswire_items(html_text, source_url)
    return _parse_html_items(html_text, source_url)


def _should_fetch_source_in_browser(*, source_name: str, source_url: str) -> bool:
    return _is_businesswire_source(source_name=source_name, source_url=source_url)


def _should_transform_html_source_to_rss(*, source_name: str, source_url: str) -> bool:
    normalized_name = _normalize_source_key(source_name)
    normalized_host = _normalize_source_key(urlparse(str(source_url or "").strip()).netloc.removeprefix("www."))
    return (
        normalized_name == "retaildive"
        or normalized_name in {"martek", "martech", "martechedge"}
        or normalized_host == "retaildivecom"
        or normalized_host == "martechedgecom"
        or _is_businesswire_source(source_name=source_name, source_url=source_url)
    )


def _build_rss_xml_from_items(
    *,
    source_name: str,
    source_url: str,
    items: list[dict[str, Any]],
) -> str:
    if not isinstance(items, list):
        raise RuntimeError("items must be a list")
    rss = etree.Element("rss", version="2.0")
    channel = etree.SubElement(rss, "channel")
    etree.SubElement(channel, "title").text = str(source_name or "").strip()
    etree.SubElement(channel, "link").text = str(source_url or "").strip()
    etree.SubElement(channel, "description").text = (
        f"HTML source converted to RSS-like XML for {str(source_name or '').strip()}"
    )
    etree.SubElement(channel, "lastBuildDate").text = utc_now_iso()
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        xml_item = etree.SubElement(channel, "item")
        title = str(item.get("title", "")).strip()
        link = str(item.get("url", "")).strip()
        summary = str(item.get("summary", "")).strip()
        published_at = str(item.get("published_at", "")).strip()
        if title:
            etree.SubElement(xml_item, "title").text = title
        if link:
            etree.SubElement(xml_item, "link").text = link
        guid = etree.SubElement(xml_item, "guid")
        guid.set("isPermaLink", "true")
        guid.text = link or f"{_normalize_source_key(source_name)}:{idx}"
        if published_at:
            etree.SubElement(xml_item, "pubDate").text = published_at
        if summary:
            description = etree.SubElement(xml_item, "description")
            description.text = etree.CDATA(summary)
    return etree.tostring(rss, encoding="unicode", pretty_print=True)


def _extract_article_text(html_text: str) -> str:
    raw = str(html_text or "")
    if not raw:
        return ""
    cleaned = re.sub(
        r"<(script|style|noscript|svg|iframe|template)[^>]*>.*?</\1>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"</(p|div|section|article|li|h[1-6]|br)>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", "\n", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
    return cleaned.strip()


def _fetch_source_html_browser(source_url: str, timeout_seconds: int) -> str:
    url = str(source_url or "").strip()
    if not url:
        raise RuntimeError("source url is required")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(f"browser source fetch unavailable: {exc}") from exc
    goto_timeout_ms = max(1000, int(timeout_seconds) * 1000)
    network_idle_timeout_ms = min(7000, goto_timeout_ms)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            )
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=network_idle_timeout_ms)
            except Exception:
                pass
            html_text = str(page.content() or "")
        finally:
            browser.close()
    if not html_text:
        raise RuntimeError("browser source fetch returned empty HTML")
    return html_text


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


def _fetch_source_raw_browser(source_url: str, timeout_seconds: int) -> str:
    """Fetch a URL via Playwright and return the raw response body (not browser-rendered HTML).

    Used as a fallback for RSS/XML feeds blocked by Cloudflare or similar WAFs.
    Strategy: navigate to the URL to complete any JS challenge, then re-fetch from within
    the now-unblocked browser session using fetch() — this returns the actual raw content.
    """
    url = str(source_url or "").strip()
    if not url:
        raise RuntimeError("source url is required")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(f"browser source fetch unavailable: {exc}") from exc
    goto_timeout_ms = max(1000, int(timeout_seconds) * 1000)
    network_idle_timeout_ms = min(10000, goto_timeout_ms)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=_BROWSER_UA)
        try:
            # Navigate first — this completes the Cloudflare JS challenge
            page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=network_idle_timeout_ms)
            except Exception:
                pass
            # Re-fetch from inside the unblocked session to get raw content
            raw_text: str = page.evaluate(
                """async (target) => {
                    const resp = await fetch(target, {credentials: 'include'});
                    return await resp.text();
                }""",
                url,
            )
        finally:
            browser.close()

    if not raw_text:
        raise RuntimeError("browser raw fetch returned no response body")
    return raw_text


def fetch_article_text(source_url: str, timeout_seconds: int) -> str:
    url = str(source_url or "").strip()
    if not url:
        return ""
    headers = {"User-Agent": _BROWSER_UA}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout_seconds)
    except Exception as exc:
        raise RuntimeError(f"article fetch failed: {exc}") from exc
    if resp.status_code >= 300:
        raise RuntimeError(f"article fetch failed status={resp.status_code}")
    if looks_like_xml_feed(resp.text):
        return ""
    article_text = _extract_article_text(resp.text)
    if not article_text:
        raise RuntimeError("article fetch returned no readable text")
    return article_text[:12000]


def looks_like_xml_feed(text: str) -> bool:
    probe = str(text or "").lstrip().lower()
    if not probe:
        return False
    return (
        probe.startswith("<?xml")
        or probe.startswith("<rss")
        or probe.startswith("<feed")
    )


def load_live_source_capture(
    source_type: str,
    source_url: str,
    timeout_seconds: int,
    config_path: Path,
    source_name: str = "",
) -> dict[str, Any]:
    src_type = normalize_text(source_type)
    url = str(source_url or "").strip()
    if not url:
        raise RuntimeError("source url is required")
    if not src_type:
        raise RuntimeError("source type is required")

    raw_text = ""
    raw_format = "txt"
    if _should_fetch_source_in_browser(source_name=source_name, source_url=url):
        raw_text = _fetch_source_html_browser(url, timeout_seconds)
        raw_format = "html"
        items = _parse_source_html_items(
            html_text=raw_text,
            source_url=url,
            source_name=source_name,
        )
    else:
        headers = {"User-Agent": _BROWSER_UA}
        try:
            resp = requests.get(url, headers=headers, timeout=timeout_seconds)
        except Exception as exc:
            raise RuntimeError(f"source fetch failed: {exc}") from exc
        if resp.status_code >= 300:
            # Automatically retry blocked requests via Playwright (bypasses Cloudflare/WAF)
            if resp.status_code in {403, 429, 503}:
                try:
                    raw_text = _fetch_source_raw_browser(url, timeout_seconds)
                except Exception as browser_exc:
                    body_text = str(resp.text or "")
                    body_flat = " ".join(body_text.split())
                    if "<!doctype html" in body_flat.lower() or "<html" in body_flat.lower():
                        title_match = re.search(r"<title[^>]*>(.*?)</title>", body_text, re.IGNORECASE | re.DOTALL)
                        if title_match:
                            title_text = html.unescape(" ".join(title_match.group(1).split()))
                            body_summary = f"html error page returned title={title_text[:160]}"
                        else:
                            body_summary = "html error page returned"
                    else:
                        body_summary = body_flat[:200]
                    raise RuntimeError(
                        f"source fetch failed status={resp.status_code} body={body_summary} "
                        f"(browser fallback also failed: {browser_exc})"
                    ) from browser_exc
            else:
                body_text = str(resp.text or "")
                body_flat = " ".join(body_text.split())
                if "<!doctype html" in body_flat.lower() or "<html" in body_flat.lower():
                    title_match = re.search(r"<title[^>]*>(.*?)</title>", body_text, re.IGNORECASE | re.DOTALL)
                    if title_match:
                        title_text = html.unescape(" ".join(title_match.group(1).split()))
                        body_summary = f"html error page returned title={title_text[:160]}"
                    else:
                        body_summary = "html error page returned"
                else:
                    body_summary = body_flat[:200]
                raise RuntimeError(f"source fetch failed status={resp.status_code} body={body_summary}")
        else:
            raw_text = str(resp.text or "")
        if src_type == "http":
            if looks_like_xml_feed(raw_text):
                raw_format = "xml"
                items = _parse_rss_atom_items(raw_text)
            else:
                raw_format = "html"
                items = _parse_source_html_items(
                    html_text=raw_text,
                    source_url=url,
                    source_name=source_name,
                )
        elif src_type in {"rss", "atom", "feed"}:
            raw_format = "xml"
            items = _parse_rss_atom_items(raw_text)
        elif src_type in {"json", "api"}:
            raw_format = "json"
            try:
                payload = json.loads(raw_text)
            except ValueError as exc:
                raise RuntimeError(f"json source returned invalid JSON: {exc}") from exc
            items = _parse_json_items(payload)
        elif src_type in {"scrape", "html", "web"}:
            raw_format = "html"
            items = _parse_source_html_items(
                html_text=raw_text,
                source_url=url,
                source_name=source_name,
            )
        else:
            raise RuntimeError(f"unsupported source type for live ingestion: {source_type}")

    if src_type == "http" and raw_format == "txt":
        raise RuntimeError("http source did not produce parsed items")

    if not isinstance(items, list):
        raise RuntimeError("live source parser did not return list")
    if raw_format == "html" and _should_transform_html_source_to_rss(
        source_name=source_name,
        source_url=url,
    ):
        raw_text = _build_rss_xml_from_items(
            source_name=source_name or urlparse(url).netloc,
            source_url=url,
            items=items,
        )
        raw_format = "xml"
    return {
        "items": items,
        "raw_text": raw_text,
        "raw_format": raw_format,
    }


def load_live_source_items(source_type: str, source_url: str, timeout_seconds: int, config_path: Path) -> list[dict]:
    capture = load_live_source_capture(source_type, source_url, timeout_seconds, config_path)
    items = capture.get("items")
    if not isinstance(items, list):
        raise RuntimeError("live source capture missing items")
    return items


def window_key(event_dt: datetime, days: int) -> str:
    base = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta_days = (event_dt.date() - base.date()).days
    bucket = (delta_days // days) * days
    return f"window_{bucket}_{bucket + days - 1}"


def resolve_openai_config_path(config_path: Path) -> Path:
    cfg = load_json_file(config_path)
    if not isinstance(cfg, dict):
        raise RuntimeError(f"config must be an object: {config_path}")
    openai_cfg = required_obj(cfg, "openai")
    openai_config_file = required_text(openai_cfg, "config_file")
    return resolve_path(openai_config_file, config_path)


def load_openai_api_key(config_path: Path) -> str:
    openai_config_path = resolve_openai_config_path(config_path)
    if not openai_config_path.exists():
        raise RuntimeError(f"required OpenAI config file missing: {openai_config_path}")
    raw = load_json_file(openai_config_path)
    if not isinstance(raw, dict):
        raise RuntimeError(f"OpenAI config must be an object: {openai_config_path}")
    key = str(raw.get("openai_api_key", "")).strip()
    if not key:
        raise RuntimeError(f"required key missing in {openai_config_path}: openai_api_key")
    return key


def build_runtime_logic(prompts: dict[str, str], config_path: Path, categories: list[str] | None = None) -> dict:
    required_keys = [
        "ai_classification_system_prompt",
        "ai_weekly_writer_prompt",
        "ai_model_name",
        "ai_temperature",
        "missing_financial_value_text",
        "dedupe_event_date_window_days",
    ]
    missing = [k for k in required_keys if not str(prompts.get(k, "")).strip()]
    if missing:
        raise RuntimeError(f"Missing required active prompt keys: {', '.join(missing)}")
    dedupe_days_text = str(prompts.get("dedupe_event_date_window_days", "")).strip()
    try:
        dedupe_days = int(dedupe_days_text)
    except ValueError as exc:
        raise RuntimeError("Prompt 'dedupe_event_date_window_days' must be an integer.") from exc
    if dedupe_days <= 0:
        raise RuntimeError("Prompt 'dedupe_event_date_window_days' must be > 0.")
    temp_raw = str(prompts.get("ai_temperature", "")).strip()
    try:
        ai_temperature = float(temp_raw)
    except ValueError as exc:
        raise RuntimeError("Prompt 'ai_temperature' must be a float between 0 and 0.2.") from exc
    if ai_temperature < 0 or ai_temperature > 0.2:
        raise RuntimeError("Prompt 'ai_temperature' must be between 0 and 0.2.")
    return {
        "missing_financial_value_text": str(prompts["missing_financial_value_text"]).strip(),
        "ai_classification_system_prompt": str(prompts["ai_classification_system_prompt"]).strip(),
        "ai_weekly_writer_prompt": str(prompts["ai_weekly_writer_prompt"]).strip(),
        "ai_model_name": str(prompts["ai_model_name"]).strip(),
        "ai_temperature": ai_temperature,
        "openai_api_key": load_openai_api_key(config_path),
        "dedupe_event_date_window_days": dedupe_days,
        "company_categories": categories or [],
    }


def _openai_extract_content(data: dict) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIValidationError("OpenAI response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise AIValidationError("OpenAI response choice is invalid")
    message = first.get("message")
    if not isinstance(message, dict):
        raise AIValidationError("OpenAI response missing message")
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    if isinstance(content, list):
        parts: list[str] = []
        for piece in content:
            if not isinstance(piece, dict):
                continue
            txt = str(piece.get("text", "")).strip()
            if txt:
                parts.append(txt)
        merged = "\n".join(parts).strip()
        if merged:
            return merged
    raise AIValidationError("OpenAI response did not return text content")


def _openai_chat_completion(
    *,
    api_key: str,
    payload: dict[str, Any],
    run_store: RunStore,
    run_id: str,
    request_stage: str,
    response_stage: str,
    source_id: str = "",
    record_key: str = "",
) -> dict:
    run_store.log(run_id, "info", request_stage, to_json(payload), source_id=source_id, record_key=record_key)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = 4
    base_backoff_seconds = 1.0
    resp: requests.Response | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=90,
            )
        except Exception as exc:
            run_store.log(
                run_id,
                "warn",
                response_stage,
                f"attempt={attempt}/{max_attempts} request_error={exc}",
                source_id=source_id,
                record_key=record_key,
            )
            if attempt >= max_attempts:
                raise AIServiceError(f"OpenAI request failed after {attempt} attempts: {exc}") from exc
            time.sleep(min(30.0, base_backoff_seconds * (2 ** (attempt - 1))))
            continue

        run_store.log(
            run_id,
            "info",
            response_stage,
            f"attempt={attempt}/{max_attempts} status={resp.status_code} body={resp.text}",
            source_id=source_id,
            record_key=record_key,
        )
        if resp.status_code < 300:
            break

        if resp.status_code in retryable_statuses and attempt < max_attempts:
            time.sleep(min(30.0, base_backoff_seconds * (2 ** (attempt - 1))))
            continue

        if resp.status_code in retryable_statuses:
            raise AIServiceError(f"OpenAI API error {resp.status_code} after {attempt} attempts: {resp.text[:500]}")
        raise AIServiceError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")

    if resp is None:
        raise AIServiceError("OpenAI request failed: no response")
    try:
        data = resp.json()
    except Exception as exc:
        raise AIValidationError(f"OpenAI envelope is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AIValidationError("OpenAI envelope is not an object")
    return data


def _validate_ai_classification_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise AIValidationError("classification payload is not a JSON object")
    required_keys = ["company", "event_type", "amount", "round", "investors", "event_date", "category"]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise AIValidationError(f"classification payload missing keys: {', '.join(missing)}")

    event_type = str(payload.get("event_type", "")).strip()
    if event_type not in AI_ALLOWED_EVENT_TYPES:
        raise AIValidationError(f"invalid event_type: {event_type}")

    company = _clean_optional_render_text(payload.get("company", ""))
    if not company and event_type != "consumer_industry_news":
        raise AIValidationError("classification payload missing usable company")

    category = str(payload.get("category", "")).strip()
    if category not in AI_ALLOWED_CATEGORIES:
        raise AIValidationError(f"invalid category: {category}")

    event_date = str(payload.get("event_date", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        raise AIValidationError(f"invalid event_date format (expected YYYY-MM-DD): {event_date}")
    try:
        datetime.fromisoformat(event_date)
    except ValueError as exc:
        raise AIValidationError(f"invalid event_date value: {event_date}") from exc

    amount = str(payload.get("amount", "")).strip()
    round_name = str(payload.get("round", "")).strip()
    investors = str(payload.get("investors", "")).strip()

    return {
        "company": company,
        "event_type": event_type,
        "amount": amount,
        "round": round_name,
        "investors": investors,
        "event_date": event_date,
        "category": category,
    }


def passes_prequal(item: dict) -> bool:
    funding_keywords = [
        "raise",
        "raised",
        "funding",
        "series",
        "seed",
        "round",
        "closes",
        "secures",
        "investment",
        "backed",
    ]
    ma_keywords = [
        "acquired",
        "acquisition",
        "merger",
        "buys",
        "sold to",
    ]
    industry_keywords = [
        "ipo",
        "valuation",
        "launches",
        "expands",
        "partnership",
    ]
    haystack = normalize_text(f"{item.get('title', '')} {item.get('summary', '')}")
    if not haystack:
        return False
    for keyword in funding_keywords + ma_keywords + industry_keywords:
        if keyword in haystack:
            return True
    return False


def classify_and_extract(
    item: dict,
    logic: dict,
    run_store: RunStore,
    run_id: str,
    source_id: str,
    record_key: str,
    request_timeout_seconds: int = 30,
) -> dict:
    title = str(item.get("title", "")).strip()
    body = str(item.get("summary", "")).strip()
    source_name = str(item.get("source_name", "")).strip() or str(item.get("source_id", "")).strip()
    source_link = str(item.get("url", "")).strip()
    published_at = str(item.get("published_at", "")).strip()
    published_date_fallback = datetime.now(timezone.utc).date().isoformat()
    if published_at:
        try:
            published_date_fallback = parse_iso(published_at).date().isoformat()
        except RuntimeError:
            pass
    normalizer_settings = _external_normalizer_settings_from_logic(
        logic,
        request_timeout_seconds=request_timeout_seconds,
    )
    try:
        normalizer_mod = _load_external_feed_normalizer_module()
        normalized_ai = normalizer_mod.build_normalized_ai_block(
            title=title,
            description=body,
            link=source_link,
            published=published_at,
            source_name=source_name,
            openai_settings=normalizer_settings,
            airtable_placeholders={},
        )
    except requests.RequestException as exc:
        raise AIServiceError(str(exc)) from exc
    except RuntimeError as exc:
        raise AIValidationError(str(exc)) from exc

    mapped = _map_external_normalized_ai_to_event(
        normalized_ai=normalized_ai,
        title=title,
        body=body,
        source_link=source_link,
        source_name=source_name,
        published_date_fallback=published_date_fallback,
    )
    run_store.log(run_id, "info", "ai_classify_validated", to_json(mapped), source_id=source_id, record_key=record_key)
    return mapped


def build_fingerprints(event: dict, logic: dict) -> tuple[str, str]:
    days = int(logic["dedupe_event_date_window_days"])
    event_dt = parse_iso(event["event_date"] + "T00:00:00+00:00")
    wk = window_key(event_dt, days)
    company_n = normalize_text(event["company"])
    type_n = normalize_text(event["event_type"])
    amount_n = normalize_text(event["amount"])
    fp_raw = f"{company_n}|{type_n}|{amount_n}|{wk}"
    base_raw = f"{company_n}|{type_n}|{wk}"
    return hashlib.sha256(fp_raw.encode("utf-8")).hexdigest(), hashlib.sha256(base_raw.encode("utf-8")).hexdigest()


def _has_meaningful_runtime_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_meaningful_runtime_value(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_runtime_value(v) for v in value)
    return True


def _merge_runtime_event_fields(row: dict, event: dict) -> dict:
    merged = dict(row) if isinstance(row, dict) else {}
    if not isinstance(event, dict):
        return merged

    passthrough_keys = (
        "company",
        "company_description",
        "acquirer",
        "target",
        "counterparty",
        "event_type",
        "amount",
        "round",
        "investors",
        "event_date",
        "category",
        "source_link",
        "source_name",
        "raw_title",
        "raw_summary",
        "article",
        "AIsummary",
        "SlackContent",
        "amount_usd",
        "amount_currency",
        "company_category",
        "valuation",
        "target_prior_raise",
        "target_prior_valuation",
    )
    for key in passthrough_keys:
        incoming = event.get(key)
        if not _has_meaningful_runtime_value(incoming):
            continue
        if _has_meaningful_runtime_value(merged.get(key)):
            continue
        merged[key] = incoming

    for nested_key in ("funding", "mna"):
        incoming_nested = event.get(nested_key)
        if not isinstance(incoming_nested, dict):
            continue
        existing_nested = merged.get(nested_key)
        out_nested = dict(existing_nested) if isinstance(existing_nested, dict) else {}
        for nk, nv in incoming_nested.items():
            if not _has_meaningful_runtime_value(nv):
                continue
            if _has_meaningful_runtime_value(out_nested.get(nk)):
                continue
            out_nested[nk] = nv
        if out_nested:
            merged[nested_key] = out_nested
    return merged


def _init_table_dedupe_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_source_link: dict[str, dict[str, Any]] = {}
    for row in events:
        if not isinstance(row, dict):
            continue
        source_link_key = normalize_text(row.get("source_link", ""))
        if not source_link_key:
            continue
        if source_link_key in by_source_link:
            continue
        by_source_link[source_link_key] = row
    event_count = len(events)
    return {
        "by_source_link": by_source_link,
        "event_count": event_count,
        "next_event_num": event_count + 1,
    }


def _ensure_table_dedupe_state(
    airtable: AirtableStore,
    target_table: str,
    dedupe_state: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if dedupe_state is None:
        return None
    table_key = str(target_table).strip()
    existing = dedupe_state.get(table_key)
    if isinstance(existing, dict) and isinstance(existing.get("by_source_link"), dict):
        return existing
    events = airtable.load_events(target_table)
    state = _init_table_dedupe_state(events)
    dedupe_state[table_key] = state
    return state


def _reserve_event_id(
    table_state: dict[str, Any] | None,
    fallback_event_count: int,
    airtable: "AirtableStore | None" = None,
    target_table: str | None = None,
) -> str:
    # Try to get max event_id from Airtable to handle deleted rows
    max_id_from_airtable = None
    if airtable is not None and target_table is not None:
        try:
            events = airtable.load_events(target_table)
            if events:
                event_ids = []
                for event in events:
                    event_id_str = str(event.get("event_id", "")).strip()
                    if event_id_str.startswith("evt_"):
                        try:
                            num = int(event_id_str[4:])
                            event_ids.append(num)
                        except Exception:
                            pass
                if event_ids:
                    max_id_from_airtable = max(event_ids)
        except Exception:
            pass

    if max_id_from_airtable is not None:
        next_event_num = max_id_from_airtable + 1
    elif table_state is None:
        next_event_num = fallback_event_count + 1
    else:
        try:
            next_event_num = int(table_state.get("next_event_num", 1))
        except Exception:
            next_event_num = 1
        if next_event_num < 1:
            next_event_num = 1

    if table_state is not None:
        table_state["next_event_num"] = next_event_num + 1
        try:
            event_count = int(table_state.get("event_count", 0))
        except Exception:
            event_count = 0
        table_state["event_count"] = max(0, event_count) + 1

    return f"evt_{next_event_num:06d}"


def upsert_event(
    airtable: AirtableStore,
    event: dict,
    logic: dict,
    dedupe_state: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict]:
    target_table = airtable._resolve_event_target_table(event)
    target_key = "news" if airtable.table_news and target_table == airtable.table_news else "events"
    event["airtable_target_table"] = target_key
    table_state = _ensure_table_dedupe_state(airtable, target_table, dedupe_state)
    events = airtable.load_events(target_table) if table_state is None else []
    fingerprint, base_fingerprint = build_fingerprints(event, logic)
    event["fingerprint"] = fingerprint
    event["base_fingerprint"] = base_fingerprint
    event["updated_at"] = utc_now_iso()
    event["manual_override"] = False
    event["incorrect_flag"] = False
    source_link = str(event.get("source_link", "")).strip()
    if not source_link:
        raise RuntimeError("event missing required field: source_link")
    source_link_key = normalize_text(source_link)
    incoming_slack = normalize_text(event.get("SlackContent", ""))

    candidates: list[dict[str, Any]] = []
    if table_state is not None:
        cached_row = table_state.get("by_source_link", {}).get(source_link_key)
        if isinstance(cached_row, dict):
            candidates = [cached_row]
    else:
        candidates = events

    for row in candidates:
        if table_state is None and normalize_text(row.get("source_link", "")) != source_link_key:
            continue
        existing_slack = normalize_text(row.get("SlackContent", ""))
        if existing_slack == incoming_slack:
            return "duplicate", _merge_runtime_event_fields(row, event)
        existing_event_id = row.get("event_id", "")
        existing_created_at = row.get("created_at", "")
        for key, value in event.items():
            row[key] = value
        if existing_event_id:
            row["event_id"] = existing_event_id
        if existing_created_at:
            row["created_at"] = existing_created_at
        row["updated_at"] = utc_now_iso()
        row["airtable_target_table"] = target_key
        saved = airtable.update_event(row)
        if table_state is not None:
            table_state["by_source_link"][source_link_key] = saved
        return "updated", _merge_runtime_event_fields(saved, event)

    new_id = _reserve_event_id(table_state, len(events), airtable=airtable, target_table=target_table)
    new_row = {
        "event_id": new_id,
        **event,
        "airtable_target_table": target_key,
        "created_at": utc_now_iso(),
    }
    created = airtable.create_event(new_row)
    if table_state is not None and source_link_key:
        table_state["by_source_link"][source_link_key] = created
    return "created", _merge_runtime_event_fields(created, new_row)


def create_event_without_dedupe(
    airtable: AirtableStore,
    event: dict,
    logic: dict,
    record_key: str,
    dedupe_state: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, dict]:
    target_table = airtable._resolve_event_target_table(event)
    target_key = "news" if airtable.table_news and target_table == airtable.table_news else "events"
    fingerprint, base_fingerprint = build_fingerprints(event, logic)
    nonce_raw = f"{record_key}|{utc_now_iso()}|no_dedupe"
    nonce = hashlib.sha256(nonce_raw.encode("utf-8")).hexdigest()

    event_copy = dict(event)
    event_copy["fingerprint"] = hashlib.sha256(f"{fingerprint}|{nonce}".encode("utf-8")).hexdigest()
    event_copy["base_fingerprint"] = hashlib.sha256(f"{base_fingerprint}|{nonce}".encode("utf-8")).hexdigest()
    event_copy["updated_at"] = utc_now_iso()
    event_copy["manual_override"] = False
    event_copy["incorrect_flag"] = False

    table_state = _ensure_table_dedupe_state(airtable, target_table, dedupe_state)
    events = airtable.load_events(target_table) if table_state is None else []
    new_id = _reserve_event_id(table_state, len(events), airtable=airtable, target_table=target_table)
    created = airtable.create_event(
        {
            "event_id": new_id,
            **event_copy,
            "airtable_target_table": target_key,
            "created_at": utc_now_iso(),
        }
    )
    if table_state is not None:
        source_link_key = normalize_text(event_copy.get("source_link", ""))
        if source_link_key:
            table_state["by_source_link"][source_link_key] = created
    return "created_no_dedupe", _merge_runtime_event_fields(created, event_copy)


def build_daily_summary(events: list[dict], day: datetime) -> str:
    day_str = day.date().isoformat()
    selected = [e for e in events if str(e.get("event_date", "")) == day_str]
    by_type: dict[str, int] = {}
    for e in selected:
        t = str(e.get("event_type", "unknown"))
        by_type[t] = by_type.get(t, 0) + 1
    lines = [f"# Daily Summary ({day_str})", "", f"Total events: {len(selected)}", ""]
    for t, c in sorted(by_type.items()):
        lines.append(f"- {t}: {c}")
    lines.append("")
    for e in selected[:50]:
        company = _clean_optional_render_text(e.get("company", ""))
        if not company:
            continue
        event_type = str(e.get("event_type", "unknown")).strip() or "unknown"
        amount = _normalize_amount_text(e.get("amount", ""))
        source_link = _clean_optional_render_text(e.get("source_link", ""))
        parts = [company, event_type]
        if amount:
            parts.append(amount)
        if source_link:
            parts.append(source_link)
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines).strip() + "\n"


def _resolve_week_window(
    today: datetime,
    *,
    start_override: datetime.date | None = None,
    end_override: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    end = end_override if end_override is not None else today.date()
    start = start_override if start_override is not None else end - timedelta(days=6)
    if start > end:
        raise RuntimeError(f"weekly window start {start.isoformat()} is after end {end.isoformat()}")
    return start, end


def build_weekly_summary(
    events: list[dict],
    today: datetime,
    *,
    start_override: datetime.date | None = None,
    end_override: datetime.date | None = None,
) -> str:
    start, end = _resolve_week_window(today, start_override=start_override, end_override=end_override)
    selected = []
    for e in events:
        try:
            d = datetime.fromisoformat(str(e.get("event_date", ""))).date()
        except ValueError:
            continue
        if start <= d <= end:
            # Only include records where IsConsumerNews is checked for consumer_industry_news events
            event_type = str(e.get("event_type", "")).strip()
            if event_type == "consumer_industry_news" and not e.get("IsConsumerNews"):
                continue
            selected.append(e)
    by_type: dict[str, int] = {}
    for e in selected:
        t = str(e.get("event_type", "unknown"))
        by_type[t] = by_type.get(t, 0) + 1
    lines = [f"# Weekly Summary ({start.isoformat()} to {end.isoformat()})", "", f"Total events: {len(selected)}", ""]
    for t, c in sorted(by_type.items()):
        lines.append(f"- {t}: {c}")
    lines.append("")
    for e in selected[:100]:
        event_date = str(e.get("event_date", "")).strip()
        company = _clean_optional_render_text(e.get("company", ""))
        if not company:
            continue
        event_type = str(e.get("event_type", "unknown")).strip() or "unknown"
        amount = _normalize_amount_text(e.get("amount", ""))
        parts = [part for part in [event_date, company, event_type, amount] if part]
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines).strip() + "\n"


def _select_week_events(
    events: list[dict],
    today: datetime,
    *,
    start_override: datetime.date | None = None,
    end_override: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date, list[dict]]:
    start, end = _resolve_week_window(today, start_override=start_override, end_override=end_override)
    selected: list[dict] = []
    for e in events:
        try:
            d = datetime.fromisoformat(str(e.get("event_date", ""))).date()
        except ValueError:
            continue
        if start <= d <= end:
            # Only include records where IsConsumerNews is checked for consumer_industry_news events
            event_type = str(e.get("event_type", "")).strip()
            if event_type == "consumer_industry_news" and not e.get("IsConsumerNews"):
                continue
            selected.append(e)
    return start, end, selected


def _cap_weekly_news_events(selected_events: list[dict], news_limit: int) -> tuple[list[dict], int]:
    news_events = [
        event
        for event in selected_events
        if str(event.get("event_type", "")).strip() == "consumer_industry_news" and event.get("IsConsumerNews")
    ]
    news_total = len(news_events)
    if news_total <= news_limit:
        return selected_events, news_total

    # Keep the newest News rows by event_date (descending), then event_id for stable tie-breaking.
    keep_news = sorted(
        news_events,
        key=lambda event: (
            str(event.get("event_date", "")).strip(),
            str(event.get("event_id", "")).strip(),
        ),
        reverse=True,
    )[:news_limit]
    keep_ids = {id(event) for event in keep_news}

    capped = []
    for event in selected_events:
        event_type = str(event.get("event_type", "")).strip()
        if event_type != "consumer_industry_news" or id(event) in keep_ids:
            capped.append(event)
    return capped, news_total


def _extract_section_bullets(markdown_text: str, section_header: str) -> list[str]:
    lines = markdown_text.splitlines()
    header_n = normalize_text(section_header)
    start_idx = -1
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading_text = re.sub(r"^#{1,6}\s*", "", stripped).strip()
        heading_n = normalize_text(heading_text)
        if heading_n == header_n or header_n in heading_n or heading_n in header_n:
            start_idx = idx
            break
    if start_idx < 0:
        return []
    bullets: list[str] = []
    for line in lines[start_idx + 1 :]:
        stripped = line.strip()
        if re.match(r"^#{1,6}\s+", stripped):
            break
        if stripped.startswith("- "):
            bullets.append(stripped)
    return bullets


def _validate_weekly_markdown(markdown_text: str, selected_events: list[dict]) -> str:
    body = str(markdown_text or "").strip()
    if not body:
        raise AIValidationError("weekly markdown output is empty")
    found_headers = {
        normalize_text(re.sub(r"^#{1,6}\s*", "", line.strip()).strip())
        for line in body.splitlines()
        if re.match(r"^#{1,6}\s+", line.strip())
    }
    for header in AI_WEEKLY_REQUIRED_HEADERS:
        expected = normalize_text(re.sub(r"^#{1,6}\s*", "", header).strip())
        matched = any(found == expected or expected in found or found in expected for found in found_headers)
        if not matched:
            raise AIValidationError(f"weekly markdown missing required section header: {header}")
    return body + "\n"


def _validate_weekly_sections_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise AIValidationError("weekly sections payload is not a JSON object")
    required_keys = [
        "intro",
        "weekly_snapshot",
        "key_themes",
        "closing",
    ]
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise AIValidationError(f"weekly sections payload missing keys: {', '.join(missing)}")
    out: dict[str, str] = {}
    for key in required_keys:
        out[key] = str(payload.get(key, "")).strip()
    return out


def _deduplicate_section_events(events: list[dict], event_type: str) -> list[dict]:
    """Deduplicate events by company, keeping the one with most content."""
    from collections import defaultdict

    # Group events by dedup key
    grouped = defaultdict(list)
    no_key_events = []  # Events without a dedup key

    for event in events:
        if event_type == "funding_round":
            # Group by company name
            company = str(event.get("company", "")).strip().lower()
            if company:
                grouped[company].append(event)
            else:
                no_key_events.append(event)

        elif event_type == "m_and_a_transaction":
            # Group by (acquiring company, target) tuple
            company = str(event.get("company", "")).strip().lower()
            target = str(event.get("target", "")).strip().lower()
            if not target:
                target = str(event.get("counterparty", "")).strip().lower()

            if company or target:
                key = (company, target)
                grouped[key].append(event)
            else:
                no_key_events.append(event)

        else:
            # For other event types (consumer_industry_news), don't dedupe
            no_key_events.append(event)

    # Deduplicate each group
    deduplicated = []

    for group_events in grouped.values():
        if len(group_events) == 1:
            deduplicated.append(group_events[0])
        else:
            # Score each event by content completeness
            def score_event(e):
                score = 0
                # Key fields worth more
                if str(e.get("amount", "")).strip():
                    score += 3
                if str(e.get("round", "")).strip():
                    score += 2
                if str(e.get("valuation", "")).strip():
                    score += 2
                # Investor info
                lead_inv = str(e.get("lead_investors", "")).strip()
                other_inv = str(e.get("other_investors", "")).strip()
                investors = str(e.get("investors", "")).strip()
                if lead_inv:
                    score += 2
                if other_inv:
                    score += 1
                if investors:
                    score += 2
                # Descriptions
                if str(e.get("company_description", "")).strip():
                    score += 1
                if str(e.get("summary", "")).strip():
                    score += 1
                # Also consider text length
                desc_len = len(str(e.get("company_description", "")).strip())
                summary_len = len(str(e.get("summary", "")).strip())
                score += (desc_len + summary_len) // 100  # +1 per 100 chars
                return score

            # Keep the highest scoring event
            best = max(group_events, key=score_event)
            deduplicated.append(best)

    # Add back events without dedup keys
    deduplicated.extend(no_key_events)

    return deduplicated


def _select_weekly_section_events(
    selected_events: list[dict],
    *,
    event_type: str,
    limit: int,
) -> list[dict]:
    # Filter by event type
    filtered = [
        event
        for event in selected_events
        if str(event.get("event_type", "")).strip() == event_type
    ]

    # Deduplicate events with same company
    deduplicated = _deduplicate_section_events(filtered, event_type)

    # Sort by company category (A-Z), then by date (newest first)
    def sort_key(event: dict) -> tuple[str, int, str]:
        # Get category for primary sort
        category = str(event.get("company_category", "")).strip().lower()

        # Convert date to negative ordinal for descending sort (newest first)
        # while keeping category ascending (A-Z)
        date_str = str(event.get("event_date", "")).strip()
        date_ordinal = 0
        try:
            date_obj = datetime.fromisoformat(date_str).date()
            date_ordinal = -date_obj.toordinal()  # Negative for descending
        except (ValueError, AttributeError):
            date_ordinal = 0  # Invalid dates sort to top

        event_id = str(event.get("event_id", "")).strip()

        return (category, date_ordinal, event_id)

    deduplicated.sort(key=sort_key)  # No reverse - using negative date for descending
    return deduplicated[:limit]


def _extract_text_from_slack_content(slack_content: str) -> str:
    """Return the body text from a SlackContent string, stripping metadata lines."""
    body_lines: list[str] = []
    for raw_line in slack_content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r"[A-Z]{3}[YN]", line):
            continue
        if line.lower().startswith("source:"):
            continue
        if line.startswith("\u2022 "):
            line = line[2:].strip()
        if line:
            body_lines.append(line)
    return " ".join(body_lines).strip()


def _clean_summary_for_newsletter(text: str) -> str:
    """Convert Slack markup to Markdown for newsletter rendering."""
    value = str(text or "").strip()
    # Strip leading routing code e.g. "FNDYA ", "NWSNB ", "ACQYA "
    value = re.sub(r"^[A-Z]{3,5}[YN][A-Z]?\s+", "", value)
    # Convert Slack links <url|display> → Markdown [display](url)
    value = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", value)
    # Convert bare Slack URLs <url> → Markdown [url](url)
    value = re.sub(r"<(https?://[^>]+)>", r"[\1](\1)", value)
    return value.strip()


def _is_slack_like_content(text: str) -> bool:
    candidate = str(text or "")
    if not candidate.strip():
        return False
    if candidate.lstrip().startswith("\u2022 "):
        return True
    if re.search(r"(?im)^\s*source\s*:", candidate):
        return True
    if re.search(r"\b(?:FNDYA|NWSNB|ACQYA)\b", candidate):
        return True
    return False


def _selected_article_text(
    event: dict[str, Any],
    article_format_config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Get article text from selected format field.

    Returns (content, field_used). If selected field is empty, returns ("", field_name)
    to signal that this event should be skipped.
    """
    if article_format_config is None:
        article_format_config = {
            "active_field": "SlackContent",
            "active_format_name": "SlackContent (default)",
            "all_formats": [],
        }
    active_field = str(article_format_config.get("active_field", "SlackContent")).strip() or "SlackContent"

    # Try active field only - if empty, skip this event
    primary_content = str(event.get(active_field, "")).strip()

    if not primary_content:
        return "", active_field

    if active_field == "SlackContent" or _is_slack_like_content(primary_content):
        content = _clean_summary_for_newsletter(_extract_text_from_slack_content(primary_content))
    else:
        content = _clean_summary_for_newsletter(primary_content)
    return content, active_field


def _render_substack_event_line(
    event: dict[str, Any],
    article_format_config: dict[str, Any] | None = None,
) -> str:
    """Render event line for newsletter using configured content field."""
    if article_format_config is None:
        article_format_config = {
            "active_field": "SlackContent",
            "active_format_name": "SlackContent (default)",
            "all_formats": [],
        }

    source_name = _clean_optional_render_text(event.get("source_name", ""))
    if not source_name:
        raise RuntimeError("substack event missing required render field: source_name")
    source_link = _clean_optional_render_text(event.get("source_link", ""))
    if not source_link:
        raise RuntimeError("substack event missing required render field: source_link")

    content, active_field = _selected_article_text(event, article_format_config=article_format_config)
    if not content:
        # Skip this event - selected field is empty
        return ""

    # Remove embedded "Source: [...](...)" patterns from content to avoid duplication
    # Pattern: "Source: " followed by markdown link, optionally repeated
    content = re.sub(r'\s*\.?\s*Source:\s*\[[^\]]*\]\([^\)]*\)(\s*\.\s*\[[^\]]*\]\([^\)]*\))*', '', content, flags=re.IGNORECASE)
    content = content.strip()

    # Ensure proper sentence ending
    if content and content[-1] not in ".!?":
        content += "."

    # Add source reference
    link_label = source_name.replace("[", "\\[").replace("]", "\\]")
    source_ref = f"[{link_label}]({source_link})"

    return f"- {content} {source_ref}"


def _categorize_consumer_news_by_keywords(
    events: list[dict],
    article_format_config: dict[str, Any] | None = None,
) -> dict[str, list[dict]]:
    """Categorize consumer news events by keywords into distribution, product launches, retail tech, and other."""
    categories = {
        "distribution": [],
        "product_launch": [],
        "retail_tech": [],
        "other": []
    }

    DISTRIBUTION_KEYWORDS = [
        "partnership", "store", "launch", "expansion", "distribution",
        "debut", "opens", "opening", "expands", "expanded", "retail",
        "locations", "nationwide", "stores"
    ]

    PRODUCT_LAUNCH_KEYWORDS = [
        "new product", "launches", "debuts", "introduces", "introduced",
        "unveiled", "released", "announcing", "new line", "new collection",
        "foundation", "flavor", "category", "sku", "product line"
    ]

    RETAIL_TECH_KEYWORDS = [
        "ecommerce", "e-commerce", "retail tech", "supply chain",
        "logistics", "delivery", "commerce tech", "marketplace",
        "platform", "saas", "software"
    ]

    for event in events:
        content, _ = _selected_article_text(event, article_format_config=article_format_config)
        search_text = content.lower()

        # Check keywords (priority order: product launch > distribution > retail tech > other)
        if any(keyword in search_text for keyword in PRODUCT_LAUNCH_KEYWORDS):
            categories["product_launch"].append(event)
        elif any(keyword in search_text for keyword in DISTRIBUTION_KEYWORDS):
            categories["distribution"].append(event)
        elif any(keyword in search_text for keyword in RETAIL_TECH_KEYWORDS):
            categories["retail_tech"].append(event)
        else:
            categories["other"].append(event)

    return categories


def _render_weekly_event_bullets(
    section_key: str,
    selected_events: list[dict],
    article_format_config: dict[str, Any] | None = None,
) -> list[str]:
    # Category emoji mapping
    CATEGORY_EMOJIS = {
        # Broad categories (from AI_ALLOWED_CATEGORIES)
        "consumer brands": "🏷️",
        "consumer technology": "💻",
        "commerce and retail tech": "🛒",
        # Detailed categories
        "e-commerce": "🛒",
        "ecommerce": "🛒",
        "commerce": "🛒",
        "fintech": "💳",
        "financial technology": "💳",
        "finance": "💳",
        "food & beverage": "🍕",
        "food and beverage": "🍕",
        "food": "🍕",
        "beverage": "🍺",
        "health & wellness": "🏥",
        "health and wellness": "🏥",
        "healthcare": "🏥",
        "wellness": "💊",
        "beauty & personal care": "💄",
        "beauty": "💄",
        "personal care": "💄",
        "cosmetics": "💄",
        "apparel & fashion": "👕",
        "apparel": "👕",
        "fashion": "👕",
        "clothing": "👕",
        "home & living": "🏠",
        "home": "🏠",
        "furniture": "🛋️",
        "technology": "💻",
        "saas": "☁️",
        "software": "💻",
        "pet care": "🐾",
        "pets": "🐾",
        "sports & fitness": "⚽",
        "fitness": "💪",
        "sports": "⚽",
        "media & entertainment": "🎬",
        "entertainment": "🎮",
        "media": "📺",
        "travel": "✈️",
        "hospitality": "🏨",
        "education": "📚",
        "edtech": "🎓",
        "automotive": "🚗",
        "mobility": "🚙",
        "real estate": "🏘️",
        "proptech": "🏗️",
        "marketplace": "🏪",
        "subscription": "📦",
        "delivery": "🚚",
        "logistics": "📦",
    }

    event_type = {
        "notable_funding": "funding_round",
        "notable_m_and_a": "m_and_a_transaction",
        "consumer_industry_updates": "consumer_industry_news",
    }[section_key]
    section_limits = {
        "notable_funding": 100,
        "notable_m_and_a": 100,
        "consumer_industry_updates": 25,
    }
    limit = section_limits[section_key]
    section_events = _select_weekly_section_events(selected_events, event_type=event_type, limit=limit)

    if not section_events:
        fallback = {
            "notable_funding": "- No qualifying funding events selected this week.",
            "notable_m_and_a": "- No qualifying M&A events selected this week.",
            "consumer_industry_updates": "- No qualifying consumer industry updates selected this week.",
        }
        return [fallback[section_key]]

    lines: list[str] = []

    for event in section_events:
        # Add event bullet (skip if content field is empty)
        try:
            line = _render_substack_event_line(event, article_format_config=article_format_config)
            if line:  # Skip empty returns (events with empty selected field)
                lines.append(line)
        except RuntimeError:
            continue

    if not lines:
        fallback = {
            "notable_funding": "- No qualifying funding events selected this week.",
            "notable_m_and_a": "- No qualifying M&A events selected this week.",
            "consumer_industry_updates": "- No qualifying consumer industry updates selected this week.",
        }
        return [fallback[section_key]]
    return lines


def _render_weekly_markdown_from_sections(
    sections: dict[str, str],
    selected_events: list[dict],
    *,
    week_start: Any = None,
    week_end: Any = None,
    article_format_config: dict[str, Any] | None = None,
) -> str:
    header_lines: list[str] = []
    if week_start and week_end:
        start_str = f"{week_start.strftime('%B')} {week_start.day}"
        # Include month in end date if it's different from start month
        if week_start.month != week_end.month:
            end_str = f"{week_end.strftime('%B')} {week_end.day}, {week_end.year}"
        else:
            end_str = f"{week_end.day}, {week_end.year}"
        header_lines = [f"# Consumer VC Weekly — {start_str}–{end_str}", ""]
    lines = [
        *header_lines,
        "## 👋 Intro 👋",
        sections["intro"],
        "",
        "## 📊 Weekly Snapshot 📊",
        sections["weekly_snapshot"],
        "",
        "## 💡 Key Themes 💡",
        sections["key_themes"],
        "",
        "---",
        "",
        "## 💰 Notable Funding 💰",
        *_render_weekly_event_bullets(
            "notable_funding",
            selected_events,
            article_format_config=article_format_config,
        ),
        "",
        "## 🤝 Notable M&A 🤝",
        *_render_weekly_event_bullets(
            "notable_m_and_a",
            selected_events,
            article_format_config=article_format_config,
        ),
        "",
    ]

    # Get consumer news events and categorize by keywords
    event_type_map = {
        "notable_funding": "funding_round",
        "notable_m_and_a": "m_and_a_transaction",
        "consumer_industry_updates": "consumer_industry_news",
    }
    consumer_news_events = _select_weekly_section_events(
        selected_events,
        event_type=event_type_map["consumer_industry_updates"],
        limit=25
    )

    if consumer_news_events:
        categorized = _categorize_consumer_news_by_keywords(
            consumer_news_events,
            article_format_config=article_format_config,
        )

        # Distribution & Expansion section
        if categorized["distribution"]:
            lines.extend([
                "## 🚀 Distribution & Expansion 🚀",
                *[_render_substack_event_line(e, article_format_config=article_format_config) for e in categorized["distribution"]],
                "",
            ])

        # Product Launches section
        if categorized["product_launch"]:
            lines.extend([
                "## 🚀 Product Launches",
                *[_render_substack_event_line(e, article_format_config=article_format_config) for e in categorized["product_launch"]],
                "",
            ])

        # Retail/Commerce Tech section
        if categorized["retail_tech"]:
            lines.extend([
                "## 🛍️ Retail, Commerce Tech & Supply Chain",
                *[_render_substack_event_line(e, article_format_config=article_format_config) for e in categorized["retail_tech"]],
                "",
            ])

        # Other Notable News section
        if categorized["other"]:
            lines.extend([
                "## 🔻 Other Notable News 🔻",
                *[_render_substack_event_line(e, article_format_config=article_format_config) for e in categorized["other"]],
                "",
            ])

    lines.extend([
        "---",
        "",
        "## 🙏 Closing 🙏",
        sections["closing"],
    ])
    return "\n".join(lines).strip() + "\n"


def _md_inline_html(text: str) -> str:
    """Convert inline Markdown (links, bold) to HTML. Links processed first so bold can wrap them."""
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


def _generate_newsletter_audit_report(
    all_events: list[dict],
    selected_events: list[dict],
    start_date: datetime.date,
    end_date: datetime.date,
) -> str:
    """Generate HTML audit report showing what was pulled vs what made it into newsletter."""

    # Build mapping of event_id to section
    event_sections = {}

    # Track funding events
    funding_events = _select_weekly_section_events(selected_events, event_type="funding_round", limit=100)
    for event in funding_events:
        event_sections[event.get("event_id")] = "💰 Notable Funding"

    # Track M&A events
    ma_events = _select_weekly_section_events(selected_events, event_type="m_and_a_transaction", limit=100)
    for event in ma_events:
        event_sections[event.get("event_id")] = "🤝 Notable M&A"

    # Track consumer news events (split by keywords)
    consumer_news = _select_weekly_section_events(selected_events, event_type="consumer_industry_news", limit=25)
    if consumer_news:
        categorized = _categorize_consumer_news_by_keywords(consumer_news)
        for event in categorized.get("distribution", []):
            event_sections[event.get("event_id")] = "🚀 Distribution & Expansion"
        for event in categorized.get("product_launch", []):
            event_sections[event.get("event_id")] = "🚀 Product Launches"
        for event in categorized.get("retail_tech", []):
            event_sections[event.get("event_id")] = "🛍️ Retail, Commerce Tech & Supply Chain"
        for event in categorized.get("other", []):
            event_sections[event.get("event_id")] = "🔻 Other Notable News"

    # Build HTML table rows
    rows = []
    included_count = 0
    excluded_count = 0

    for event in all_events:
        event_id = event.get("event_id", "")
        event_id_display = str(event_id).strip() or "N/A"
        company = str(event.get("company", "")).strip() or "N/A"
        event_type = str(event.get("event_type", "")).strip() or "unknown"
        event_date = str(event.get("event_date", "")).strip() or "N/A"
        source_url = str(event.get("source_link", "")).strip()
        _, source_article_file = _read_article_cache_text_by_url(source_url)
        article_checkbox = (
            f'<input type="checkbox" checked disabled title="{html.escape(source_article_file)}" aria-label="Article cached">'
            if source_article_file
            else '<input type="checkbox" disabled aria-label="Article cached">'
        )

        if event_id in event_sections:
            section = event_sections[event_id]
            status = f'<span style="color: #28a745; font-weight: bold;">✓ Included</span>'
            status_detail = section
            included_count += 1
        else:
            status = f'<span style="color: #dc3545; font-weight: bold;">✗ Excluded</span>'
            # Determine why excluded
            if event_type not in ["funding_round", "m_and_a_transaction", "consumer_industry_news"]:
                status_detail = f"Wrong event type: {event_type}"
            else:
                status_detail = "Deduped or not selected"
            excluded_count += 1

        row_style = 'background-color: #f8f9fa;' if excluded_count % 2 == 0 else ''
        rows.append(f'''
            <tr style="{row_style}">
                <td>{event_date}</td>
                <td><strong>{company}</strong></td>
                <td>{event_type}</td>
                <td>{event_id_display}</td>
                <td>{status}</td>
                <td>{status_detail}</td>
                <td style="text-align: center;">{article_checkbox}</td>
            </tr>
        ''')

    report_html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Newsletter Audit Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 1400px;
            margin: 40px auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .summary {{
            display: flex;
            gap: 30px;
            margin-top: 20px;
        }}
        .stat {{
            padding: 15px 25px;
            background: #f8f9fa;
            border-radius: 6px;
            border-left: 4px solid #007bff;
        }}
        .stat-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            margin-bottom: 5px;
        }}
        .stat-value {{
            font-size: 28px;
            font-weight: bold;
            color: #333;
        }}
        table {{
            width: 100%;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-collapse: collapse;
        }}
        th {{
            background: #343a40;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
            font-size: 14px;
        }}
        td {{
            padding: 12px 15px;
            border-bottom: 1px solid #dee2e6;
            font-size: 14px;
        }}
        tr:hover {{
            background: #e9ecef !important;
        }}
        .article-col {{
            text-align: center;
            width: 80px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Newsletter Audit Report</h1>
        <p><strong>Date Range:</strong> {start_date.strftime('%B %d, %Y')} – {end_date.strftime('%B %d, %Y')}</p>
        <div class="summary">
            <div class="stat">
                <div class="stat-label">Total Events Pulled</div>
                <div class="stat-value">{len(all_events)}</div>
            </div>
            <div class="stat" style="border-left-color: #28a745;">
                <div class="stat-label">Included in Newsletter</div>
                <div class="stat-value">{included_count}</div>
            </div>
            <div class="stat" style="border-left-color: #dc3545;">
                <div class="stat-label">Excluded</div>
                <div class="stat-value">{excluded_count}</div>
            </div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Event Date</th>
                <th>Company</th>
                <th>Event Type</th>
                <th>Event ID</th>
                <th>Status</th>
                <th>Newsletter Section / Exclusion Reason</th>
                <th class="article-col">Article</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>
</body>
</html>'''

    return report_html


def _read_article_cache_text_by_url(source_url: str) -> tuple[str, str]:
    normalized_url = str(source_url or "").strip()
    if not normalized_url:
        return "", ""
    article_cache_dir = FLOW_LOG_DIR / "article_cache"
    if not article_cache_dir.exists() or not article_cache_dir.is_dir():
        return "", ""
    cache_key = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    candidate_paths = [
        article_cache_dir / f"{cache_key}.txt",
        article_cache_dir / f"{cache_key}.html",
        article_cache_dir / f"{cache_key}.json",
    ]
    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                cached_url = str(payload.get("url", "")).strip()
                cached_text = str(payload.get("text", "")).strip()
                if cached_text and (not cached_url or cached_url == normalized_url):
                    return cached_text, str(path)
                continue
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not raw_text:
            continue
        if path.suffix.lower() == ".html":
            extracted = _extract_article_text(raw_text)
            raw_text = extracted if extracted else raw_text
        cleaned = str(raw_text or "").strip()
        if cleaned:
            return cleaned, str(path)
    return "", ""


def _render_weekly_html(markdown_text: str) -> str:
    """Render the weekly Substack draft Markdown as a self-contained styled HTML newsletter."""
    logo_tag = ""
    logo_path = Path(__file__).resolve().parent / "monitor" / "Images" / "logo.png"
    if logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        logo_tag = f'<img src="data:image/png;base64,{logo_b64}" alt="Consumer VC" class="logo">'

    mike_tag = ""
    mike_path = Path(__file__).resolve().parent / "monitor" / "Images" / "80f8d421-3a64-4f96-98b3-b1673cf9c28c_500x500.jpg"
    if mike_path.exists():
        mike_b64 = base64.b64encode(mike_path.read_bytes()).decode("ascii")
        mike_tag = f'<img src="data:image/jpeg;base64,{mike_b64}" alt="Mike Gelb" class="author-photo">'

    body_parts: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body_parts.append("</ul>")
            in_list = False

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            close_list()
            continue
        # H1
        if line.startswith("# ") and not line.startswith("## "):
            close_list()
            body_parts.append(f'<h1 class="newsletter-title">{_md_inline_html(line[2:].strip())}</h1>')
            continue
        # H2
        if line.startswith("## "):
            close_list()
            body_parts.append(f'<h2 class="section-heading">{_md_inline_html(line[3:].strip())}</h2>')
            continue
        # HR
        if line == "---":
            close_list()
            body_parts.append('<hr class="section-divider">')
            continue
        # Bullet
        if line.startswith("- "):
            if not in_list:
                body_parts.append('<ul class="event-list">')
                in_list = True
            item = _md_inline_html(line[2:].strip())
            # Style the trailing source link (always last <a> on the line) as muted ref
            item = re.sub(
                r"\s+(<a\b[^>]*>[^<]+</a>)\s*$",
                r' <span class="source-ref">\1</span>',
                item,
            )
            body_parts.append(f'<li class="event-item">{item}</li>')
            continue
        # Paragraph
        close_list()
        body_parts.append(f'<p>{_md_inline_html(line)}</p>')

    close_list()
    body_html = "\n    ".join(body_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Consumer VC Weekly</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #111018;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    color: #e8e4f0;
    line-height: 1.7;
  }}
  .email-wrapper {{
    max-width: 680px;
    margin: 32px auto;
    background: #1b1726;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 40px rgba(0,0,0,0.5);
  }}
  .header {{
    background: #CC1F1A;
    padding: 22px 40px;
    display: flex;
    align-items: center;
    gap: 18px;
  }}
  .logo {{
    width: 56px;
    height: 56px;
    border-radius: 10px;
    flex-shrink: 0;
  }}
  .header-meta .brand {{
    font-size: 20px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.3px;
  }}
  .header-meta .tagline {{
    font-size: 13px;
    color: rgba(255,255,255,0.80);
    margin-top: 3px;
  }}
  .content {{
    padding: 36px 40px 28px;
  }}
  h1.newsletter-title {{
    font-size: 24px;
    font-weight: 800;
    color: #f0ecff;
    margin-bottom: 22px;
    letter-spacing: -0.4px;
    line-height: 1.25;
  }}
  h2.section-heading {{
    font-size: 15px;
    font-weight: 700;
    color: #f0ecff;
    margin: 30px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #2e2a42;
  }}
  p {{
    margin-bottom: 16px;
    font-size: 15px;
    color: #c8c2dc;
    line-height: 1.75;
  }}
  hr.section-divider {{
    border: none;
    border-top: 1px solid #2e2a42;
    margin: 28px 0;
  }}
  ul.event-list {{
    list-style: disc;
    margin: 0 0 8px 20px;
    padding: 0;
  }}
  li.event-item {{
    padding: 14px 16px;
    margin-bottom: 8px;
    background: #231e34;
    border-radius: 8px;
    font-size: 14px;
    line-height: 1.4;
    color: #c8c2dc;
  }}
  li.event-item a {{ color: #9fa8e8; text-decoration: none; font-weight: 500; }}
  li.event-item a:hover {{ text-decoration: underline; color: #bec5f2; }}
  .source-ref {{ font-size: 12px; }}
  .source-ref a {{ color: #6b6480 !important; font-weight: 400 !important; }}
  .byline {{
    padding: 18px 40px;
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid #2e2a42;
    background: #1b1726;
  }}
  .author-photo {{
    width: 44px;
    height: 44px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    border: 2px solid #3a3554;
  }}
  .byline-text .author-name {{
    font-size: 14px;
    font-weight: 700;
    color: #f0ecff;
  }}
  .byline-text .author-sub {{
    font-size: 12px;
    color: #6b6480;
    margin-top: 2px;
  }}
  .footer {{
    background: #141120;
    padding: 20px 40px;
    border-top: 1px solid #2e2a42;
    text-align: center;
    font-size: 13px;
    color: #6b6480;
  }}
  .footer a {{
    color: #9fa8e8;
    text-decoration: none;
    font-weight: 600;
    margin: 0 8px;
  }}
  .footer a:hover {{ text-decoration: underline; }}
  @media (max-width: 680px) {{
    .email-wrapper {{ margin: 0; border-radius: 0; box-shadow: none; }}
    .header, .content, .footer {{ padding-left: 20px; padding-right: 20px; }}
  }}
</style>
</head>
<body>
<div class="email-wrapper">
  <div class="header">
    {logo_tag}
    <div class="header-meta">
      <div class="brand">Consumer VC</div>
      <div class="tagline">Weekly Roundup</div>
    </div>
  </div>
  <div class="byline">
    {mike_tag}
    <div class="byline-text">
      <div class="author-name">Mike Gelb</div>
      <div class="author-sub">Consumer VC &middot; theconsumervc.com</div>
    </div>
  </div>
  <div class="content">
    {body_html}
  </div>
  <div class="footer">
    <a href="https://www.theconsumervc.com">Subscribe</a>
    <a href="#">Share with a friend</a>
    <a href="https://www.theconsumervc.com">theconsumervc.com</a>
  </div>
</div>
</body>
</html>"""


def _build_weekly_ai_article_text(
    selected_events: list[dict],
    article_format_config: dict[str, Any] | None = None,
) -> tuple[str, int, int]:
    if article_format_config is None:
        article_format_config = {
            "active_field": "SlackContent",
            "active_format_name": "SlackContent (default)",
            "all_formats": [],
        }

    chunks: list[str] = []
    used_count = 0
    missing_count = 0
    for event in selected_events:
        body_text, _ = _selected_article_text(event, article_format_config=article_format_config)
        if not body_text:
            missing_count += 1
            continue
        used_count += 1
        source_name = _clean_optional_render_text(event.get("source_name", "")) or "Unknown"
        chunks.append(f"{body_text} ({source_name})")
    return "\n\n".join(chunks).strip(), used_count, missing_count


def build_weekly_substack_draft(
    events: list[dict],
    today: datetime,
    logic: dict,
    run_store: RunStore,
    run_id: str,
    *,
    article_format_config: dict[str, Any] | None = None,
    start_override: datetime.date | None = None,
    end_override: datetime.date | None = None,
) -> str:
    # Initialize article_format_config if not provided
    if article_format_config is None:
        article_format_config = {
            "active_field": "SlackContent",
            "active_format_name": "SlackContent (default)",
            "all_formats": [],
        }

    start, end, selected = _select_week_events(
        events,
        today,
        start_override=start_override,
        end_override=end_override,
    )
    selected, news_total = _cap_weekly_news_events(selected, AI_WEEKLY_NEWS_LIMIT)
    news_kept = sum(
        1
        for event in selected
        if str(event.get("event_type", "")).strip() == "consumer_industry_news"
    )
    if news_total > news_kept:
        run_store.log(
            run_id,
            "info",
            "ai_weekly_news_cap",
            f"consumer_industry_news capped from {news_total} to {news_kept}",
            record_key="weekly_draft",
        )
    article_text, article_text_used, article_text_missing = _build_weekly_ai_article_text(
        selected,
        article_format_config=article_format_config,
    )
    if article_text_missing > 0:
        active_field = str(article_format_config.get("active_field", "SlackContent")).strip() or "SlackContent"
        run_store.log(
            run_id,
            "info",
            "ai_weekly_article_format",
            (
                f"active_field={active_field} "
                f"used={article_text_used} "
                f"missing={article_text_missing}"
            ),
            record_key="weekly_draft",
        )
    user_payload = {
        "date_window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "article_text": article_text,
        "events": [
            {
                "event_id": str(e.get("event_id", "")).strip(),
                "company": str(e.get("company", "")).strip(),
                "event_type": str(e.get("event_type", "")).strip(),
                "amount": str(e.get("amount", "")).strip(),
                "round": str(e.get("round", "")).strip(),
                "investors": str(e.get("investors", "")).strip(),
                "event_date": str(e.get("event_date", "")).strip(),
                "category": str(e.get("category", "")).strip(),
                "source_link": str(e.get("source_link", "")).strip(),
                "source_name": str(e.get("source_name", "")).strip(),
                "summary": _selected_article_text(e, article_format_config=article_format_config)[0],
                "company_description": str(e.get("company_description", "")).strip(),
            }
            for e in selected
        ],
        "required_sections": AI_WEEKLY_REQUIRED_HEADERS,
        "required_schema": {
            "intro": "string",
            "weekly_snapshot": "string",
            "key_themes": "string",
            "closing": "string",
        },
        "rules": [
            "Return strict JSON only.",
            "Do not generate the Notable Funding, Notable M&A, or Consumer Industry Updates sections; those are rendered by the application.",
            "Only provide intro, weekly_snapshot, key_themes, and closing.",
            "Use article_text and the events list (including each event's summary field) as primary source material.",
            "Write in Mike Gelb's personal voice: casual, warm, and direct — like a note from a fellow investor, not a press release.",
            "The intro must open with 'Hey friends,' and feel like a personal letter to the reader community.",
            "Reference specific companies, deal sizes, and investors by name drawn from the data; do not make up figures.",
            "Keep each section to 2-4 punchy sentences. No bullet points in AI sections — flowing prose only.",
            "Avoid hollow filler phrases like 'signaling robust growth', 'in today's dynamic landscape', or 'continued momentum'.",
            "The closing section must feel warm and end with a genuine call-to-action to subscribe, share, or engage.",
        ],
    }
    payload = {
        "model": logic["ai_model_name"],
        "temperature": logic["ai_temperature"],
        "messages": [
            {"role": "system", "content": str(logic["ai_weekly_writer_prompt"]).strip()},
            {"role": "user", "content": to_json(user_payload)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "consumer_vc_weekly_sections",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "intro": {"type": "string"},
                        "weekly_snapshot": {"type": "string"},
                        "key_themes": {"type": "string"},
                        "closing": {"type": "string"},
                    },
                    "required": [
                        "intro",
                        "weekly_snapshot",
                        "key_themes",
                        "closing",
                    ],
                },
            },
        },
    }
    data = _openai_chat_completion(
        api_key=str(logic["openai_api_key"]).strip(),
        payload=payload,
        run_store=run_store,
        run_id=run_id,
        request_stage="ai_weekly_request",
        response_stage="ai_weekly_raw_response",
        source_id="",
        record_key="weekly_draft",
    )
    content = _openai_extract_content(data)
    run_store.log(run_id, "info", "ai_weekly_content", content, record_key="weekly_draft")
    try:
        sections_payload = json.loads(content)
    except Exception as exc:
        raise AIValidationError(f"weekly sections content is not valid JSON: {exc}") from exc
    sections = _validate_weekly_sections_payload(sections_payload)
    markdown_text = _render_weekly_markdown_from_sections(
        sections,
        selected_events=selected,
        week_start=start,
        week_end=end,
        article_format_config=article_format_config,
    )
    try:
        validated = _validate_weekly_markdown(markdown_text, selected_events=selected)
        run_store.log(run_id, "info", "ai_weekly_validated", "weekly draft validated", record_key="weekly_draft")
        audit_data = {
            "start_date": start,
            "end_date": end,
            "selected_events": selected,
        }
        return (validated, audit_data)
    except AIValidationError as exc:
        run_store.log(run_id, "warn", "ai_weekly_validation_retry", str(exc), record_key="weekly_draft")
        retry_user_payload = {
            "original_request": user_payload,
            "previous_output": markdown_text,
            "fix_instructions": [
                "Rewrite using strict JSON schema keys only.",
                "Required keys: intro, weekly_snapshot, key_themes, closing.",
                "Return strict JSON only.",
                "Do not generate the Notable Funding, Notable M&A, or Consumer Industry Updates sections; the application renders those.",
            ],
        }
        retry_payload = {
            "model": logic["ai_model_name"],
            "temperature": logic["ai_temperature"],
            "messages": [
                {"role": "system", "content": str(logic["ai_weekly_writer_prompt"]).strip()},
                {"role": "user", "content": to_json(retry_user_payload)},
            ],
            "response_format": payload["response_format"],
        }
        retry_data = _openai_chat_completion(
            api_key=str(logic["openai_api_key"]).strip(),
            payload=retry_payload,
            run_store=run_store,
            run_id=run_id,
            request_stage="ai_weekly_retry_request",
            response_stage="ai_weekly_retry_raw_response",
            source_id="",
            record_key="weekly_draft",
        )
        retry_content = _openai_extract_content(retry_data)
        run_store.log(run_id, "info", "ai_weekly_retry_content", retry_content, record_key="weekly_draft")
        try:
            retry_sections_payload = json.loads(retry_content)
        except Exception as retry_json_exc:
            raise AIValidationError(f"weekly retry sections content is not valid JSON: {retry_json_exc}") from retry_json_exc
        retry_sections = _validate_weekly_sections_payload(retry_sections_payload)
        retry_markdown = _render_weekly_markdown_from_sections(
            retry_sections,
            selected_events=selected,
            week_start=start,
            week_end=end,
        )
        validated_retry = _validate_weekly_markdown(retry_markdown, selected_events=selected)
        run_store.log(run_id, "info", "ai_weekly_validated", "weekly draft validated after retry", record_key="weekly_draft")
        audit_data = {
            "start_date": start,
            "end_date": end,
            "selected_events": selected,
        }
        return (validated_retry, audit_data)


def _run_post_category_backfill_scripts(
    *,
    project_root: Path,
    config_path: Path,
    run_store: RunStore,
    run_id: str,
) -> list[dict[str, Any]]:
    script_names = [
        "dry_run_ai_company_category_unconstrained.py",
        "dry_run_ai_company_category_unconstrained_News.py",
    ]
    script_dir = project_root / "Tools" / "AirtableScripts"
    results: list[dict[str, Any]] = []
    for script_name in script_names:
        script_path = script_dir / script_name
        if not script_path.exists() or not script_path.is_file():
            raise RuntimeError(f"post-category script not found: {script_path}")
        cmd = [
            sys.executable,
            str(script_path),
            "--write",
            "--config",
            str(config_path),
        ]
        completed = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        stdout_text = str(completed.stdout or "").strip()
        stderr_text = str(completed.stderr or "").strip()
        if stdout_text:
            run_store.log(
                run_id,
                "info",
                "post_category_backfill",
                f"{script_name} stdout: {stdout_text}",
                record_key=run_id,
            )
        if stderr_text:
            run_store.log(
                run_id,
                "warn",
                "post_category_backfill",
                f"{script_name} stderr: {stderr_text}",
                record_key=run_id,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"post-category script failed ({script_name}) rc={completed.returncode}: {stderr_text or stdout_text}"
            )
        results.append(
            {
                "script": script_name,
                "returncode": int(completed.returncode),
                "stdout": stdout_text,
                "stderr": stderr_text,
            }
        )
    return results


def _event_id_sequence(value: Any) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    m = re.search(r"(\d+)$", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _collect_new_event_ids_by_table(airtable_event_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"events": [], "news": []}
    seen: set[tuple[str, str]] = set()
    for item in airtable_event_rows:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).strip().lower()
        if action not in {"created", "created_no_dedupe"}:
            continue
        row = item.get("row")
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id", "")).strip()
        if _event_id_sequence(event_id) is None:
            continue
        table_key = str(row.get("airtable_target_table", "")).strip().lower()
        if table_key not in {"events", "news"}:
            table_key = "events"
        key = (table_key, event_id)
        if key in seen:
            continue
        seen.add(key)
        out[table_key].append(event_id)
    for table_key in ("events", "news"):
        out[table_key].sort(key=lambda eid: (_event_id_sequence(eid) or 0, eid))
    return out


def _run_post_content_backfill_scripts(
    *,
    project_root: Path,
    config_path: Path,
    run_store: RunStore,
    run_id: str,
    event_ids_by_table: dict[str, list[str]],
) -> list[dict[str, Any]]:
    script_dir = project_root / "Tools" / "AirtableScripts"
    results: list[dict[str, Any]] = []

    def _run_step(*, script_name: str, table_key: str, event_id: str, args: list[str]) -> None:
        script_path = script_dir / script_name
        if not script_path.exists() or not script_path.is_file():
            raise RuntimeError(f"post-content script not found: {script_path}")
        cmd = [sys.executable, str(script_path), *args, "--config", str(config_path)]
        completed = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        stdout_text = str(completed.stdout or "").strip()
        stderr_text = str(completed.stderr or "").strip()
        if stdout_text:
            run_store.log(
                run_id,
                "info",
                "post_content_backfill",
                f"{script_name} table={table_key} event_id={event_id} stdout: {stdout_text}",
                record_key=event_id,
            )
        if stderr_text:
            run_store.log(
                run_id,
                "warn",
                "post_content_backfill",
                f"{script_name} table={table_key} event_id={event_id} stderr: {stderr_text}",
                record_key=event_id,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"post-content script failed ({script_name}) table={table_key} event_id={event_id} "
                f"rc={completed.returncode}: {stderr_text or stdout_text}"
            )
        results.append(
            {
                "script": script_name,
                "table": table_key,
                "event_id": event_id,
                "returncode": int(completed.returncode),
                "stdout": stdout_text,
                "stderr": stderr_text,
            }
        )

    for table_key in ("events", "news"):
        event_ids = list(event_ids_by_table.get(table_key, []))
        if not event_ids:
            continue
        for event_id in event_ids:
            # Step 1: build clean Slack field for this record.
            _run_step(
                script_name="clean_slackcontent_to_slackclean.py",
                table_key=table_key,
                event_id=event_id,
                args=[
                    "--table",
                    table_key,
                    "--event-id-start",
                    event_id,
                    "--event-id-end",
                    event_id,
                    "--write",
                ],
            )

            # Step 2: generate the three primary CVC fields for this record.
            for script_name in (
                "cvc_format_slackcontent.py",
                "cvc_with_company_desc.py",
                "cvc_comp_desc_announce_editorial.py",
            ):
                _run_step(
                    script_name=script_name,
                    table_key=table_key,
                    event_id=event_id,
                    args=[
                        "--table",
                        table_key,
                        "--event-id-start",
                        event_id,
                        "--event-id-end",
                        event_id,
                        "--write",
                    ],
                )

            # Step 3: company website link formatting for each generated field.
            for field_name in ("CVCFormatted", "CVCWithCompanyDesc", "CVCCompDescAnnounceEditorial"):
                _run_step(
                    script_name="ai_link_companies_from_field.py",
                    table_key=table_key,
                    event_id=event_id,
                    args=[
                        "--table",
                        table_key,
                        "--input-field",
                        field_name,
                        "--output-field",
                        field_name,
                        "--event-id-start",
                        event_id,
                        "--event-id-end",
                        event_id,
                        "--overwrite-existing",
                        "--write",
                    ],
                )
    return results


def run_daily(
    config_path: Path,
    dry_run: bool,
    mode: str = "live",
    snapshot_run_id: str = "",
    max_items_per_source_override: int | None = None,
    test_slack_only: bool = False,
) -> int:
    cfg = load_config(config_path)
    execution_mode = str(mode or "").strip().lower()
    if execution_mode not in {"live", "replay", "review"}:
        raise RuntimeError(f"invalid run mode: {mode}")
    if max_items_per_source_override is not None and int(max_items_per_source_override) <= 0:
        raise RuntimeError("max_items_per_source_override must be > 0")
    snapshot_source_run_id = str(snapshot_run_id or "").strip()
    if execution_mode == "replay" and not snapshot_source_run_id:
        raise RuntimeError("replay mode requires snapshot_run_id")
    if execution_mode in {"live", "review"} and snapshot_source_run_id:
        raise RuntimeError("snapshot_run_id is only valid in replay mode")
    mode_snapshot = enforce_live_execution_modes(cfg)
    runtime = required_obj(cfg, "runtime")
    output_dir = resolve_path(required_text(runtime, "output_dir"), config_path)
    state_dir = resolve_path(required_text(runtime, "state_dir"), config_path)
    activity_log_path = resolve_path(required_text(runtime, "activity_log_file"), config_path)
    checkpoint_root = checkpoint_root_for_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_root.mkdir(parents=True, exist_ok=True)

    db_path = state_dir / "consumer_vc_v1.db"
    run_store = RunStore(db_path=db_path, activity_log_path=activity_log_path)
    run_id = run_store.start_run(mode=execution_mode)
    metrics = RunMetrics()
    save_checkpoint(
        checkpoint_root,
        run_id,
        "run",
        {
            "mode": execution_mode,
            "config_path": str(config_path),
            "output_dir": str(output_dir),
            "state_dir": str(state_dir),
            "snapshot_source_run_id": snapshot_source_run_id,
            "max_items_per_source_override": max_items_per_source_override,
        },
    )

    run_store.log(run_id, "info", "start", "run started")
    run_store.log(run_id, "info", "load_config", f"config loaded from {config_path}")
    save_checkpoint(
        checkpoint_root,
        run_id,
        "load_config",
        {
            "config_path": str(config_path),
            "config_keys": sorted(cfg.keys()),
            "runtime_keys": sorted(runtime.keys()),
        },
    )
    run_store.log(
        run_id,
        "info",
        "execution_modes",
        (
            f"environment={mode_snapshot['environment']} "
            f"airtable_mode={mode_snapshot['airtable_mode']} "
            f"slack_mode={mode_snapshot['slack_mode']} "
            f"email_mode={mode_snapshot['email_mode']}"
        ),
    )

    airtable = AirtableStore(cfg)
    schema = airtable.validate_required_schema()
    run_store.log(
        run_id,
        "info",
        "schema_audit",
        f"schema validated tables={','.join(sorted(schema.keys()))}",
    )
    save_checkpoint(checkpoint_root, run_id, "schema_audit", {"schema": schema})
    substack_prompt_sync = airtable.sync_current_substack_prompt()
    if substack_prompt_sync:
        run_store.log(
            run_id,
            "info",
            "substack_prompt_sync",
            (
                f"selected_name={substack_prompt_sync['selected_name']} "
                f"updated_prompts_text={substack_prompt_sync['updated_prompts_text']}"
            ),
        )
    prompts = airtable.load_prompts()
    run_store.log(run_id, "info", "load_prompts", f"prompts loaded count={len(prompts)}")
    save_checkpoint(checkpoint_root, run_id, "load_prompts", {"prompts": prompts})

    required_prompt_keys = required_obj(cfg, "prompts").get("required_prompt_keys", [])
    for key in required_prompt_keys:
        if str(key) not in prompts:
            raise RuntimeError(f"required prompt key missing in Prompts table: {key}")
    categories = airtable.load_categories()
    run_store.log(run_id, "info", "load_categories", f"company categories loaded count={len(categories)}")
    article_format_config = airtable.load_article_format()
    run_store.log(
        run_id,
        "info",
        "load_article_format",
        f"article format loaded - active_field={article_format_config.get('active_field')} "
        f"format_name={article_format_config.get('active_format_name')}",
    )
    logic = build_runtime_logic(prompts, config_path, categories=categories)
    run_store.log(run_id, "info", "load_logic", "runtime logic loaded from active Airtable prompts")
    run_store.log(
        run_id,
        "info",
        "ai_config",
        (
            f"model={logic['ai_model_name']} "
            f"temperature={logic['ai_temperature']} "
            f"openai_config_path={resolve_openai_config_path(config_path)}"
        ),
    )

    runtime_controls = airtable.load_runtime_controls()
    run_store.log(run_id, "info", "load_runtime_controls", f"runtime controls loaded count={len(runtime_controls)}")
    required_runtime_control_keys = [
        "email_notifications_enabled",
        "slack_notifications_enabled",
        "daily_summary_enabled",
        "weekly_summary_enabled",
        "ingestion_enabled",
        "ai_enabled",
        "dedupe_enabled",
        "force_source_failure",
    ]
    missing_control_keys = [k for k in required_runtime_control_keys if k not in runtime_controls]
    if missing_control_keys:
        raise RuntimeError(
            "required runtime control(s) missing in Runtime Controls table: " + ", ".join(missing_control_keys)
        )
    email_notifications_enabled = bool(runtime_controls["email_notifications_enabled"])
    slack_notifications_enabled = bool(runtime_controls["slack_notifications_enabled"])
    daily_summary_enabled = bool(runtime_controls["daily_summary_enabled"])
    weekly_summary_enabled = bool(runtime_controls["weekly_summary_enabled"])
    ingestion_enabled = bool(runtime_controls["ingestion_enabled"])
    ai_enabled = bool(runtime_controls["ai_enabled"])
    dedupe_enabled = bool(runtime_controls["dedupe_enabled"])
    force_source_failure = bool(runtime_controls["force_source_failure"])
    prequal_enabled = bool(runtime_controls.get("prequal_enabled", False))
    runtime_test_slack_only_enabled = bool(runtime_controls.get("test_slack_only_enabled", False))
    runtime_test_max_items_enabled = bool(runtime_controls.get("test_max_items_per_source_enabled", False))
    bypass_source_urls = bool(runtime_controls.get("bypass_source_urls", False))
    bypass_seen_urls = bool(runtime_controls.get("bypass_seen_urls", False) or bypass_source_urls)
    post_category_backfill_enabled = bool(runtime_controls.get("post_category_backfill_enabled", False))
    post_content_backfill_enabled = bool(runtime_controls.get("post_content_backfill_enabled", True))
    effective_test_slack_only = bool(test_slack_only or runtime_test_slack_only_enabled)
    effective_max_items_per_source_override = (
        int(max_items_per_source_override)
        if max_items_per_source_override is not None
        else (5 if runtime_test_max_items_enabled else None)
    )
    if not ai_enabled:
        raise RuntimeError("runtime control 'ai_enabled' is false; AI execution is mandatory.")
    if effective_test_slack_only and not slack_notifications_enabled:
        raise RuntimeError("test_slack_only requires slack_notifications_enabled=true")
    run_store.log(
        run_id,
        "info",
        "runtime_control",
        (
            f"email_notifications_enabled={email_notifications_enabled} "
            f"slack_notifications_enabled={slack_notifications_enabled} "
            f"daily_summary_enabled={daily_summary_enabled} "
            f"weekly_summary_enabled={weekly_summary_enabled} "
            f"ingestion_enabled={ingestion_enabled} "
            f"ai_enabled={ai_enabled} "
            f"dedupe_enabled={dedupe_enabled} "
            f"force_source_failure={force_source_failure} "
            f"prequal_enabled={prequal_enabled} "
            f"test_max_items_per_source_requested={max_items_per_source_override is not None} "
            f"test_max_items_per_source_enabled={runtime_test_max_items_enabled} "
            f"effective_max_items_per_source_override={effective_max_items_per_source_override} "
            f"test_slack_only_requested={bool(test_slack_only)} "
            f"test_slack_only_enabled={effective_test_slack_only} "
            f"bypass_source_urls={bypass_source_urls} "
            f"bypass_seen_urls={bypass_seen_urls} "
            f"post_category_backfill_enabled={post_category_backfill_enabled} "
            f"post_content_backfill_enabled={post_content_backfill_enabled}"
        ),
    )
    run_store.log(
        run_id,
        "info",
        "prequal",
        "prequal enabled" if prequal_enabled else "prequal disabled by runtime control",
    )
    save_checkpoint(
        checkpoint_root,
        run_id,
        "runtime_controls",
        {
            "controls": runtime_controls,
            "resolved": {
                "email_notifications_enabled": email_notifications_enabled,
                "slack_notifications_enabled": slack_notifications_enabled,
                "daily_summary_enabled": daily_summary_enabled,
                "weekly_summary_enabled": weekly_summary_enabled,
                "ingestion_enabled": ingestion_enabled,
                "ai_enabled": ai_enabled,
                "dedupe_enabled": dedupe_enabled,
                "force_source_failure": force_source_failure,
                "prequal_enabled": prequal_enabled,
                "bypass_source_urls": bypass_source_urls,
                "bypass_seen_urls": bypass_seen_urls,
                "post_category_backfill_enabled": post_category_backfill_enabled,
                "post_content_backfill_enabled": post_content_backfill_enabled,
            },
        },
    )
    if force_source_failure:
        run_store.log(
            run_id,
            "info",
            "runtime_control",
            "force_source_failure=true will fail the first live source during snapshot capture",
        )

    sources = airtable.load_sources()
    metrics.total_sources = len(sources)
    active_sources = [s for s in sources if bool(s.get("active"))]
    metrics.active_sources = len(active_sources)
    run_store.log(run_id, "info", "load_sources", f"sources loaded total={len(sources)} active={len(active_sources)}")
    save_checkpoint(
        checkpoint_root,
        run_id,
        "load_sources",
        {
            "total_sources": len(sources),
            "active_sources": len(active_sources),
            "sources": sources,
        },
    )

    slack = (
        SlackNotifier(cfg, config_path, run_store=run_store, run_id=run_id)
        if (not dry_run and slack_notifications_enabled)
        else None
    )
    error_slack = slack
    if error_slack is None and not dry_run:
        try:
            error_slack = SlackNotifier(cfg, config_path, run_store=run_store, run_id=run_id)
        except Exception as exc:
            run_store.log(run_id, "warn", "slack_post", f"error Slack notifier unavailable: {exc}", record_key=run_id)
    emailer = EmailNotifier(cfg, config_path) if (not dry_run and email_notifications_enabled) else None
    state_path = state_dir / "source_state.json"
    state = load_state(state_path) if execution_mode in {"live", "review"} else {"seen_urls_by_source": {}}
    persisted_seen_by_source = state.get("seen_urls_by_source", {}) if execution_mode in {"live", "review"} else {}
    if not isinstance(persisted_seen_by_source, dict):
        persisted_seen_by_source = {}
    if effective_test_slack_only:
        persisted_seen_by_source = {}
        run_store.log(
            run_id,
            "info",
            "runtime_control",
            "source_state bypassed by test_slack_only",
            record_key=run_id,
        )
    if bypass_seen_urls:
        persisted_seen_by_source = {}
        run_store.log(
            run_id,
            "info",
            "runtime_control",
            "source_state bypassed by bypass_seen_urls",
            record_key=run_id,
        )
    staged_seen_by_source = {
        str(source_key): list(source_urls) if isinstance(source_urls, list) else []
        for source_key, source_urls in persisted_seen_by_source.items()
    } if execution_mode in {"live", "review"} else {}

    force_failure_triggered = False
    transient_summary_events: list[dict] = []
    ingestion_checkpoint: dict[str, Any] = {
        "active_sources": [],
        "source_results": [],
        "pending_items": [],
    }
    classify_inputs: list[dict[str, Any]] = []
    master_normalized_records: list[dict[str, Any]] = []
    master_normalized_batch_saved = False
    classify_outputs: list[dict[str, Any]] = []
    dedupe_actions: list[dict[str, Any]] = []
    dedupe_state: dict[str, dict[str, Any]] = {}
    airtable_event_rows: list[dict[str, Any]] = []
    revision_entries: list[dict[str, Any]] = []
    active_snapshot_run_id = run_id if execution_mode in {"live", "review"} else snapshot_source_run_id
    raw_snapshot_path = raw_snapshot_file(active_snapshot_run_id)
    if execution_mode in {"live", "review"}:
        raw_snapshot_payload = {
            "run_id": run_id,
            "captured_at": utc_now_iso(),
            "mode": execution_mode,
            "sources": [],
        }
        max_items = int(runtime.get("max_items_per_source_per_run", 40))
        if effective_max_items_per_source_override is not None:
            max_items = int(effective_max_items_per_source_override)
            run_store.log(
                run_id,
                "info",
                "runtime_control",
                f"max_items_per_source_override={max_items}",
            )
        for source in active_sources:
            source_id = str(source.get("id", "")).strip()
            source_name = str(source.get("name", source_id)).strip() or source_id
            source_type = str(source.get("type", "")).strip()
            source_url = str(source.get("url", "")).strip()
            if not source_id:
                raise RuntimeError("source row missing id")
            if not source_type:
                raise RuntimeError(f"source {source_id} missing type")
            if not source_url:
                raise RuntimeError(f"source {source_id} missing url")
            seen_urls_before_run = staged_seen_by_source.get(source_id, [])
            if not isinstance(seen_urls_before_run, list):
                seen_urls_before_run = []
            seen_urls_before_run_set = {
                str(url).strip()
                for url in seen_urls_before_run
                if str(url).strip()
            }
            raw_items: list[dict[str, Any]] = []
            source_error = ""
            raw_response_format = ""
            source_records_total = 0
            source_already_seen_count = 0
            try:
                capture = load_live_source_capture(
                    source_type=source_type,
                    source_url=source_url,
                    timeout_seconds=int(runtime.get("request_timeout_seconds", 30)),
                    config_path=config_path,
                    source_name=source_name,
                )
                fetched_items = capture.get("items")
                if not isinstance(fetched_items, list):
                    raise RuntimeError("source capture missing items")
                raw_response_format = str(capture.get("raw_format", "")).strip().lower()
                raw_response_text = str(capture.get("raw_text", ""))
                if raw_response_format:
                    save_raw_source_response_checkpoint(
                        checkpoint_root,
                        run_id,
                        source_id,
                        raw_response_text,
                        raw_response_format,
                    )
                if not isinstance(fetched_items, list):
                    raise RuntimeError("source parser must return array")
                if force_source_failure and not force_failure_triggered:
                    force_failure_triggered = True
                    raise RuntimeError("forced failure for Slack testing via runtime control")
                unseen_selected = 0
                for item in fetched_items:
                    if not isinstance(item, dict):
                        continue
                    item_url = str(item.get("url", "")).strip()
                    if not item_url:
                        continue
                    source_records_total += 1
                    if item_url in seen_urls_before_run_set:
                        source_already_seen_count += 1
                        continue
                    if unseen_selected >= max_items:
                        continue
                    raw_items.append(dict(item))
                    unseen_selected += 1
            except Exception as exc:
                source_error = str(exc)

            raw_snapshot_payload["sources"].append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "source_type": source_type,
                    "source_url": source_url,
                    "raw_response_format": raw_response_format,
                    "seen_urls_before_run": list(seen_urls_before_run),
                    "raw_items_total": int(source_records_total),
                    "already_seen_count": int(source_already_seen_count),
                    "raw_items": raw_items,
                    "error": source_error,
                }
            )

            new_seen_urls = {str(url).strip() for url in seen_urls_before_run if str(url).strip()}
            for item in raw_items:
                url = str(item.get("url", "")).strip()
                if url:
                    new_seen_urls.add(url)
            staged_seen_by_source[source_id] = sorted(new_seen_urls)

        raw_snapshot_path = write_raw_snapshot(run_id, raw_snapshot_payload)
        raw_snapshot_payload = load_raw_snapshot(run_id)
    else:
        raw_snapshot_payload = load_raw_snapshot(snapshot_source_run_id)
        raw_snapshot_sources = required_list(raw_snapshot_payload, "sources")
        updated_sources: list[dict[str, Any]] = []
        snapshot_changed = False
        for source_entry in raw_snapshot_sources:
            hydrated = _hydrate_manual_source_snapshot_entry(
                checkpoint_root=checkpoint_root,
                snapshot_run_id=snapshot_source_run_id,
                source_entry=required_obj(source_entry, "source"),
            )
            if hydrated != source_entry:
                snapshot_changed = True
            updated_sources.append(hydrated)
        if snapshot_changed:
            raw_snapshot_payload = dict(raw_snapshot_payload)
            raw_snapshot_payload["sources"] = updated_sources
            write_json_file(raw_snapshot_file(snapshot_source_run_id), raw_snapshot_payload)
    raw_snapshot_path = raw_snapshot_file(active_snapshot_run_id)
    save_raw_snapshot_checkpoint(checkpoint_root, run_id, raw_snapshot_payload)
    raw_sources = required_list(raw_snapshot_payload, "sources")
    write_run_meta(
        run_id=run_id,
        timestamp=utc_now_iso(),
        mode=execution_mode,
        source_count=len(raw_sources),
        raw_snapshot_run_id=active_snapshot_run_id,
    )
    run_store.log(
        run_id,
        "info",
        "ingest_source",
        f"raw snapshot loaded {raw_snapshot_path}",
        record_key=active_snapshot_run_id,
    )
    feed_article_summary_text = build_feed_article_summary_text(raw_sources)
    feed_article_summary_file = output_dir / f"!!!-{run_id}_feed_article_summary.txt"
    feed_article_summary_file.write_text(feed_article_summary_text, encoding="utf-8")
    feed_article_summary_checkpoint_file = (
        checkpoint_root / _safe_checkpoint_id(run_id) / "!!!-feed_article_summary.txt"
    )
    feed_article_summary_checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    feed_article_summary_checkpoint_file.write_text(feed_article_summary_text, encoding="utf-8")
    run_store.log(
        run_id,
        "info",
        "ingest_source",
        f"feed article summary written {feed_article_summary_file}",
        record_key=run_id,
    )
    if execution_mode == "review":
        review_files = sorted(
            path.name
            for path in (checkpoint_root / _safe_checkpoint_id(run_id)).glob("!!*_raw.*")
            if path.is_file()
        )
        review_payload = {
            **ingestion_checkpoint,
            "review_only": True,
            "raw_snapshot_run_id": active_snapshot_run_id,
            "raw_snapshot_file": str(raw_snapshot_path),
            "raw_source_files": review_files,
        }
        save_checkpoint(checkpoint_root, run_id, "ingest_source", review_payload)
        run_store.log(
            run_id,
            "info",
            "ingest_source",
            f"review gate ready raw_files={len(review_files)}",
            record_key=active_snapshot_run_id,
        )
        run_log_payload = {
            "run_id": run_id,
            "ts": utc_now_iso(),
            "mode": execution_mode,
            "metrics": metrics.__dict__,
            "runtime_controls": {
                "email_notifications_enabled": email_notifications_enabled,
                "slack_notifications_enabled": slack_notifications_enabled,
                "daily_summary_enabled": daily_summary_enabled,
                "weekly_summary_enabled": weekly_summary_enabled,
                "ingestion_enabled": ingestion_enabled,
                "ai_enabled": ai_enabled,
                "dedupe_enabled": dedupe_enabled,
                "force_source_failure": force_source_failure,
                "prequal_enabled": prequal_enabled,
                "post_category_backfill_enabled": post_category_backfill_enabled,
                "post_content_backfill_enabled": post_content_backfill_enabled,
            },
            "post_category_backfill": {
                "enabled": post_category_backfill_enabled,
                "eligible": False,
                "attempted": False,
                "success": False,
                "skipped_reason": "review_mode",
                "error": "",
                "scripts": [],
            },
            "post_content_backfill": {
                "enabled": post_content_backfill_enabled,
                "eligible": False,
                "attempted": False,
                "success": False,
                "skipped_reason": "review_mode",
                "error": "",
                "event_ids_by_table": {"events": [], "news": []},
                "scripts": [],
            },
            "daily_summary_file": "",
            "weekly_summary_file": "",
            "weekly_substack_draft_file": "",
            "raw_snapshot_run_id": active_snapshot_run_id,
            "raw_snapshot_file": str(raw_snapshot_path),
            "feed_article_summary_file": str(feed_article_summary_file),
            "feed_article_summary_checkpoint_file": str(feed_article_summary_checkpoint_file),
            "raw_source_files": review_files,
            "review_only": True,
        }
        save_checkpoint(checkpoint_root, run_id, "run_summary", run_log_payload)
        run_store.log(run_id, "info", "run_summary", f"status=completed metrics={metrics.__dict__}")
        run_store.finish(run_id, "completed", metrics)
        out_summary = output_dir / f"{run_id}_summary.json"
        out_summary.write_text(json.dumps(run_log_payload, ensure_ascii=True, indent=2), encoding="utf-8")
        run_store.log(
            run_id,
            "info",
            "state_commit",
            f"source state deferred because status=completed mode={execution_mode}",
            record_key=run_id,
        )
        save_checkpoint(
            checkpoint_root,
            run_id,
            "complete",
            {
                "status": "completed",
                "run_id": run_id,
                "metrics": metrics.__dict__,
                "summary_file": str(out_summary),
                "state_path": str(state_path),
                "review_only": True,
            },
        )
        cleanup_active_checkpoints(checkpoint_root, run_id)
        print(f"run_id={run_id}")
        print("status=completed")
        print(f"metrics={metrics.__dict__}")
        print(f"summary_file={out_summary}")
        return 0

    if ingestion_enabled:
        ingest_records_total = 0
        ingest_already_seen_total = 0
        prep_progress_total = 0
        prep_progress_current = 0
        article_fetch_progress_current = 0
        article_fetch_progress_total = 0
        for source_payload in raw_sources:
            if not isinstance(source_payload, dict):
                continue
            raw_items_for_total = source_payload.get("raw_items")
            if not isinstance(raw_items_for_total, list):
                continue
            seen_urls_for_total = source_payload.get("seen_urls_before_run", [])
            if not isinstance(seen_urls_for_total, list):
                seen_urls_for_total = []
            if effective_test_slack_only:
                seen_urls_for_total = []
            seen_before = {str(url).strip() for url in seen_urls_for_total if str(url).strip()}
            for raw_item in raw_items_for_total:
                if not isinstance(raw_item, dict):
                    continue
                raw_url = str(raw_item.get("url", "")).strip()
                if not raw_url or raw_url in seen_before:
                    continue
                prep_progress_total += 1
        for source_payload in raw_sources:
            if not isinstance(source_payload, dict):
                raise RuntimeError("raw snapshot sources must contain objects")
            source_id = str(source_payload.get("source_id", "")).strip()
            source_name = str(source_payload.get("source_name", source_id)).strip() or source_id
            source_type = str(source_payload.get("source_type", "")).strip()
            source_url = str(source_payload.get("source_url", "")).strip()
            if not source_id:
                raise RuntimeError("raw snapshot source missing source_id")
            if not source_type:
                raise RuntimeError(f"raw snapshot source {source_id} missing source_type")
            if not source_url:
                raise RuntimeError(f"raw snapshot source {source_id} missing source_url")
            raw_items = source_payload.get("raw_items")
            if not isinstance(raw_items, list):
                raise RuntimeError(f"raw snapshot source {source_id} missing raw_items")
            seen_urls_before_run = source_payload.get("seen_urls_before_run", [])
            if not isinstance(seen_urls_before_run, list):
                raise RuntimeError(f"raw snapshot source {source_id} missing seen_urls_before_run")
            if effective_test_slack_only:
                seen_urls_before_run = []
            seen_urls = {str(url).strip() for url in seen_urls_before_run if str(url).strip()}
            source_error = str(source_payload.get("error", "")).strip()

            run_store.log(
                run_id,
                "info",
                "ingest_source",
                f"ingesting source | {source_name}",
                source_id=source_id,
            )
            ingestion_checkpoint["active_sources"].append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "source_type": source_type,
                    "source_url": source_url,
                    "snapshot_run_id": active_snapshot_run_id,
                }
            )

            if source_error:
                source_error_detail = _format_source_failure_error(
                    source_id=source_id,
                    source_name=source_name,
                    source_url=source_url,
                    error_text=source_error,
                )
                metrics.failed_sources += 1
                run_store.log(run_id, "error", "source_failure", source_error_detail, source_id=source_id)
                ingestion_checkpoint["source_results"].append(
                    {
                        "source_id": source_id,
                        "source_name": source_name,
                        "error": source_error_detail,
                        "raw_items_count": len(raw_items),
                    }
                )
                save_checkpoint(
                    checkpoint_root,
                    run_id,
                    "ingest_source",
                    {
                        **ingestion_checkpoint,
                        "raw_snapshot_run_id": active_snapshot_run_id,
                        "raw_snapshot_file": str(raw_snapshot_path),
                    },
                )
                if error_slack is not None:
                    if post_slack_error_alert(
                        slack=error_slack,
                        run_store=run_store,
                        run_id=run_id,
                        source_name=source_name,
                        error_text=source_error_detail,
                    ):
                        metrics.slack_alerts += 1
                continue

            pending_items: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                metrics.total_items_seen += 1
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                if url in seen_urls:
                    continue
                metrics.new_items += 1
                item_copy = dict(item)
                item_copy["source_id"] = source_id
                item_copy["source_name"] = source_name
                pending_items.append(item_copy)

            source_records_count = len(raw_items)
            source_already_seen_count = max(0, len(raw_items) - len(pending_items))
            try:
                source_records_count = max(
                    0,
                    int(source_payload.get("raw_items_total", source_records_count)),
                )
            except Exception:
                source_records_count = len(raw_items)
            try:
                source_already_seen_count = max(
                    0,
                    int(source_payload.get("already_seen_count", source_already_seen_count)),
                )
            except Exception:
                source_already_seen_count = max(0, len(raw_items) - len(pending_items))
            ingest_records_total += source_records_count
            ingest_already_seen_total += source_already_seen_count
            run_store.log(
                run_id,
                "info",
                "ingest_source",
                f"records={ingest_records_total} already_seen={ingest_already_seen_total}",
                source_id=source_id,
            )

            ingestion_checkpoint["source_results"].append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "raw_items_count": len(raw_items),
                    "pending_count": len(pending_items),
                }
            )
            ingestion_checkpoint["pending_items"].extend(
                [
                    {
                        "source_id": source_id,
                        "source_name": source_name,
                        "title": str(item.get("title", "")),
                        "summary": str(item.get("summary", "")),
                        "url": str(item.get("url", "")),
                        "published_at": str(item.get("published_at", "")),
                    }
                    for item in pending_items
                ]
            )
            save_checkpoint(
                checkpoint_root,
                run_id,
                "ingest_source",
                {
                    **ingestion_checkpoint,
                    "raw_snapshot_run_id": active_snapshot_run_id,
                    "raw_snapshot_file": str(raw_snapshot_path),
                },
            )

            total_classify_items = 0
            ordered_meta: list[dict[str, Any]] = []
            final_blocks: list[dict[str, Any]] = []
            normalizer_mod = _load_external_feed_normalizer_module()
            normalizer_settings = _external_normalizer_settings_from_logic(
                logic,
                request_timeout_seconds=int(runtime.get("request_timeout_seconds", 30)),
            )
            airtable_placeholders = normalizer_mod.load_airtable_event_field_placeholders(config_path)
            if not hasattr(normalizer_mod, "parse_feed_file"):
                raise RuntimeError("External parser missing required function: parse_feed_file")
            if not hasattr(normalizer_mod, "_passes_prequal"):
                raise RuntimeError("External parser missing required function: _passes_prequal")

            def _url_lookup_keys(raw_url: str) -> list[str]:
                url_text = str(raw_url or "").strip()
                if not url_text:
                    return []
                keys: list[str] = []

                def _add_key(candidate: str) -> None:
                    value = str(candidate or "").strip()
                    if value and value not in keys:
                        keys.append(value)

                _add_key(url_text)
                parsed_url = urlparse(url_text)
                host = str(parsed_url.netloc or "").strip().lower().removeprefix("www.")
                path = str(parsed_url.path or "").strip()
                if host and path:
                    path_no_trailing = path.rstrip("/") or path
                    _add_key(f"{host}{path_no_trailing}")
                    _add_key(f"http://{host}{path_no_trailing}")
                    _add_key(f"https://{host}{path_no_trailing}")
                    article_id_match = re.search(r"(/articles/)(\d+)-[^/]+$", path_no_trailing, flags=re.IGNORECASE)
                    if article_id_match:
                        article_id_path = f"{article_id_match.group(1)}{article_id_match.group(2)}"
                        _add_key(f"{host}{article_id_path}")
                        _add_key(f"http://{host}{article_id_path}")
                        _add_key(f"https://{host}{article_id_path}")
                return keys

            source_normalized_records: list[dict[str, Any]] = []
            failing_item_url = ""
            try:
                def _article_fetch_progress_callback(progress: dict[str, Any]) -> None:
                    nonlocal article_fetch_progress_current
                    nonlocal article_fetch_progress_total
                    if not isinstance(progress, dict):
                        return
                    try:
                        reported_current = int(progress.get("attempted", article_fetch_progress_current))
                    except Exception:
                        reported_current = article_fetch_progress_current
                    if reported_current > 0:
                        article_fetch_progress_current += 1
                    source_label = str(progress.get("source_name", source_name)).strip() or source_name
                    record_key_text = str(progress.get("url", "")).strip()
                    try:
                        total_hint = int(progress.get("record_total", 0))
                    except Exception:
                        total_hint = 0
                    if reported_current <= 0 and total_hint > 0:
                        article_fetch_progress_total += total_hint
                    safe_total = prep_progress_total if prep_progress_total > 0 else (total_hint if total_hint > 0 else 1)
                    if article_fetch_progress_total > 0:
                        safe_total = article_fetch_progress_total
                    safe_current = min(article_fetch_progress_current, safe_total)
                    run_store.log(
                        run_id,
                        "info",
                        "article_fetch_progress",
                        f"{safe_current}/{safe_total} | {source_label}",
                        source_id=source_id,
                        record_key=record_key_text or source_id,
                    )

                parsed_ai_by_url: dict[str, dict[str, Any]] = {}
                raw_source_file = resolve_raw_source_response_checkpoint(
                    checkpoint_root,
                    active_snapshot_run_id,
                    source_id,
                )
                parse_allowed_urls = [
                    str(item.get("url", "")).strip()
                    for item in pending_items
                    if str(item.get("url", "")).strip()
                ]
                # Do not hard-cap by raw_items length when allowed URLs are provided.
                # Unseen items can be beyond the first N entries in the raw feed.
                parse_max_items: int | None = None if parse_allowed_urls else len(raw_items)
                parsed_payload = normalizer_mod.parse_feed_file(
                    raw_source_file,
                    openai_settings=normalizer_settings,
                    airtable_placeholders=airtable_placeholders,
                    max_items=parse_max_items,
                    source_name_override=source_name,
                    source_url_override=source_url,
                    apply_prequal=prequal_enabled,
                    article_fetch_progress_hook=_article_fetch_progress_callback,
                    allowed_urls=parse_allowed_urls,
                )
                feedparser_xml = parsed_payload.get("feedparser_xml")
                if not isinstance(feedparser_xml, str) or not feedparser_xml.strip():
                    raise RuntimeError(f"parse_feed_file missing required feedparser_xml for source {source_id}")
                save_source_feedparser_xml_checkpoint(
                    checkpoint_root,
                    run_id,
                    source_id,
                    feedparser_xml,
                )
                save_run_level_library_xml_checkpoint(
                    checkpoint_root,
                    run_id,
                    "feedparser.xml",
                    feedparser_xml,
                )
                ecluded_from_run_xml = parsed_payload.get("EcludedFromRun")
                if not isinstance(ecluded_from_run_xml, str) or not ecluded_from_run_xml.strip():
                    raise RuntimeError(f"parse_feed_file missing required EcludedFromRun for source {source_id}")
                save_source_ecluded_from_run_xml_checkpoint(
                    checkpoint_root,
                    run_id,
                    source_id,
                    ecluded_from_run_xml,
                )
                parsed_items = parsed_payload.get("items", [])
                if not isinstance(parsed_items, list):
                    raise RuntimeError(f"parse_feed_file items must be a list for source {source_id}")
                for parsed_item in parsed_items:
                    if not isinstance(parsed_item, dict):
                        continue
                    feedparser_block = parsed_item.get("feedparser", {})
                    ai_block = parsed_item.get("ai", {})
                    if not isinstance(feedparser_block, dict) or not isinstance(ai_block, dict):
                        continue
                    parsed_link = str(feedparser_block.get("link", "")).strip()
                    parsed_id = str(feedparser_block.get("id", "")).strip()
                    for parsed_key in _url_lookup_keys(parsed_link) + _url_lookup_keys(parsed_id):
                        parsed_ai_by_url[parsed_key] = ai_block

                for item in pending_items:
                    url = str(item.get("url", "")).strip()
                    failing_item_url = url
                    if prep_progress_total > 0:
                        prep_progress_current += 1
                        run_store.log(
                            run_id,
                            "info",
                            "parse_progress",
                            f"{prep_progress_current}/{prep_progress_total} | {source_name}",
                            source_id=source_id,
                            record_key=url,
                        )
                    title_text = str(item.get("title", ""))
                    summary_text = str(item.get("summary", ""))
                    prequal_passed = True
                    if prequal_enabled:
                        prequal_passed = bool(normalizer_mod._passes_prequal(title=title_text, description=summary_text))
                    if not prequal_passed:
                        metrics.discarded_prequal += 1
                        run_store.log(
                            run_id,
                            "info",
                            "prequal",
                            "prequal skipped",
                            source_id=source_id,
                            record_key=url,
                        )
                        continue
                    parsed_ai: dict[str, Any] | None = None
                    candidate_lookup_keys = _url_lookup_keys(url)
                    for lookup_key in candidate_lookup_keys:
                        mapped_ai = parsed_ai_by_url.get(lookup_key)
                        if isinstance(mapped_ai, dict) and mapped_ai:
                            parsed_ai = mapped_ai
                            break
                    if not isinstance(parsed_ai, dict) or not parsed_ai:
                        if not prequal_enabled:
                            run_store.log(
                                run_id,
                                "warning",
                                "parse_skip",
                                f"parsed ai block missing; skipped while prequal disabled | {url}",
                                source_id=source_id,
                                record_key=url,
                            )
                            continue
                        raise RuntimeError(
                            f"Parsed AI block missing for source {source_id} url {url} keys={candidate_lookup_keys}"
                        )
                    article_text = str(parsed_ai.get("AIContent", ""))
                    if not article_text.strip():
                        if not prequal_enabled:
                            run_store.log(
                                run_id,
                                "warning",
                                "parse_skip",
                                f"parsed ai content missing; skipped while prequal disabled | {url}",
                                source_id=source_id,
                                record_key=url,
                            )
                            continue
                        raise RuntimeError(f"Parsed AIContent missing for source {source_id} url {url}")
                    classify_input = {
                        "source_id": source_id,
                        "source_name": source_name,
                        "title": title_text,
                        "summary": summary_text,
                        "article_text": article_text,
                        "url": url,
                        "published_at": str(item.get("published_at", "")),
                        "request_timeout_seconds": int(runtime.get("request_timeout_seconds", 30)),
                    }
                    classify_inputs.append(classify_input)
                    total_classify_items += 1
                    ordered_meta.append(
                        {
                            "url": url,
                            "title": classify_input["title"],
                            "summary": classify_input["summary"],
                            "article_text": classify_input["article_text"],
                            "published_at": classify_input["published_at"],
                        }
                    )
                    final_blocks.append(parsed_ai)
                save_checkpoint(
                    checkpoint_root,
                    run_id,
                    "classify",
                    {
                        "total_items": len(classify_inputs),
                        "input_items": classify_inputs,
                        "output_events": classify_outputs,
                    },
                )
                save_source_normalized_batch_checkpoint(
                    checkpoint_root,
                    run_id,
                    source_id,
                    {
                        "source_id": source_id,
                        "source_name": source_name,
                        "total_items": len(final_blocks),
                        "items": final_blocks,
                    },
                )

                for meta, normalized_ai in zip(ordered_meta, final_blocks):
                    url = str(meta.get("url", "")).strip()
                    source_normalized_records.append(
                        {
                            "source_id": source_id,
                            "source_name": source_name,
                            "source_url": source_url,
                            "url": url,
                            "title": str(meta.get("title", "")).strip(),
                            "summary": str(meta.get("summary", "")).strip(),
                            "published_at": str(meta.get("published_at", "")).strip(),
                            "normalized_ai": normalized_ai,
                        }
                    )
            except Exception as exc:
                source_processing_error = _format_source_failure_error(
                    source_id=source_id,
                    source_name=source_name,
                    source_url=source_url,
                    failing_url=failing_item_url,
                    error_text=str(exc),
                )
                metrics.failed_sources += 1
                run_store.log(run_id, "error", "source_failure", source_processing_error, source_id=source_id)
                ingestion_checkpoint["source_results"].append(
                    {
                        "source_id": source_id,
                        "source_name": source_name,
                        "error": source_processing_error,
                        "raw_items_count": len(raw_items),
                        "pending_count": len(pending_items),
                    }
                )
                save_checkpoint(
                    checkpoint_root,
                    run_id,
                    "ingest_source",
                    {
                        **ingestion_checkpoint,
                        "raw_snapshot_run_id": active_snapshot_run_id,
                        "raw_snapshot_file": str(raw_snapshot_path),
                    },
                )
                if error_slack is not None:
                    if post_slack_error_alert(
                        slack=error_slack,
                        run_store=run_store,
                        run_id=run_id,
                        source_name=source_name,
                        error_text=source_processing_error,
                    ):
                        metrics.slack_alerts += 1
                continue

            master_normalized_records.extend(source_normalized_records)

        save_master_normalized_batch_checkpoint(
            checkpoint_root,
            run_id,
            {
                "run_id": run_id,
                "raw_snapshot_run_id": active_snapshot_run_id,
                "total_items": len(master_normalized_records),
                "items": master_normalized_records,
            },
        )
        master_normalized_batch_saved = True

        total_classify_items = len(master_normalized_records)
        classify_index = 0
        runtime_error_alerted_sources: set[str] = set()
        for normalized_entry in master_normalized_records:
            source_id = ""
            source_name = ""
            source_url = ""
            url = ""
            try:
                if not isinstance(normalized_entry, dict):
                    raise RuntimeError("master normalized records must contain objects")
                source_id = str(normalized_entry.get("source_id", "")).strip()
                source_name = str(normalized_entry.get("source_name", source_id)).strip() or source_id
                source_url = str(normalized_entry.get("source_url", "")).strip()
                url = str(normalized_entry.get("url", "")).strip()
                normalized_ai = normalized_entry.get("normalized_ai")
                if not isinstance(normalized_ai, dict) or not normalized_ai:
                    raise RuntimeError(f"master normalized record missing normalized_ai for source {source_id} url {url}")

                classify_index += 1
                run_store.log(
                    run_id,
                    "info",
                    "classify_progress",
                    f"{classify_index}/{total_classify_items} | {source_name}",
                    source_id=source_id,
                    record_key=url,
                )
                run_store.log(run_id, "info", "classify", "classifying item", source_id=source_id, record_key=url)

                published_fallback = datetime.now(timezone.utc).date().isoformat()
                published_at = str(normalized_entry.get("published_at", "")).strip()
                if published_at:
                    try:
                        published_fallback = parse_iso(published_at).date().isoformat()
                    except RuntimeError:
                        pass

                event = _map_external_normalized_ai_to_event(
                    normalized_ai=normalized_ai,
                    title=str(normalized_entry.get("title", "")).strip(),
                    body=str(normalized_entry.get("summary", "")).strip(),
                    source_link=url,
                    source_name=source_name,
                    published_date_fallback=published_fallback,
                )
                run_store.log(run_id, "info", "ai_classify_validated", to_json(event), source_id=source_id, record_key=url)
                classify_outputs.append(
                    {
                        "source_id": source_id,
                        "url": url,
                        "event": event,
                    }
                )
                save_checkpoint(
                    checkpoint_root,
                    run_id,
                    "classify",
                    {
                        "total_items": total_classify_items,
                        "input_items": classify_inputs,
                        "output_events": classify_outputs,
                    },
                )

                if event["event_type"] == "irrelevant":
                    metrics.discarded_irrelevant += 1
                    run_store.log(run_id, "info", "classify", "discarded irrelevant", source_id=source_id, record_key=url)
                    continue

                if str(event.get("event_flag", "")).strip().upper() != "Y":
                    run_store.log(
                        run_id,
                        "info",
                        "classify",
                        f"non-structured event routed to {event.get('airtable_target_table', 'news') or 'news'}",
                        source_id=source_id,
                        record_key=url,
                    )

                if effective_test_slack_only:
                    if slack is None:
                        raise RuntimeError("Slack notifier unavailable while test_slack_only is true")
                    slack_content = str(event.get("SlackContent", "")).strip()
                    if not slack_content:
                        raise RuntimeError("test_slack_only event missing SlackContent")
                    run_store.log(
                        run_id,
                        "info",
                        "slack_post",
                        "queued event Slack content for summary-only test mode",
                        source_id=source_id,
                        record_key=url,
                    )
                    run_store.log(
                        run_id,
                        "info",
                        "airtable_events",
                        "airtable write skipped by test_slack_only",
                        source_id=source_id,
                        record_key=url,
                    )
                    continue

                if dedupe_enabled:
                    run_store.log(run_id, "info", "dedupe", "dedupe check", source_id=source_id, record_key=url)
                    action, row = upsert_event(airtable, event, logic, dedupe_state=dedupe_state)
                else:
                    run_store.log(
                        run_id,
                        "info",
                        "dedupe",
                        "dedupe bypassed by runtime control",
                        source_id=source_id,
                        record_key=url,
                    )
                    action, row = create_event_without_dedupe(
                        airtable,
                        event,
                        logic,
                        record_key=url,
                        dedupe_state=dedupe_state,
                    )
                dedupe_actions.append(
                    {
                        "source_id": source_id,
                        "url": url,
                        "action": action,
                        "event": event,
                        "row": row,
                    }
                )
                save_checkpoint(
                    checkpoint_root,
                    run_id,
                    "dedupe",
                    {
                        "actions": dedupe_actions,
                    },
                )
                run_store.log(
                    run_id,
                    "info",
                    "upsert_event",
                    action,
                    source_id=source_id,
                    record_key=str(row.get("event_id", "")),
                )
                airtable_event_rows.append(
                    {
                        "action": action,
                        "row": row,
                    }
                )
                save_checkpoint(
                    checkpoint_root,
                    run_id,
                    "airtable_events",
                    {
                        "results": airtable_event_rows,
                    },
                )

                if action in {"created", "created_no_dedupe"}:
                    metrics.created_events += 1
                elif action == "duplicate":
                    metrics.duplicate_records += 1
                    run_store.log(
                        run_id,
                        "info",
                        "dedupe",
                        "duplicate skipped",
                        source_id=source_id,
                        record_key=str(row.get("event_id", "")),
                    )
                elif action == "revision_update":
                    metrics.updated_events += 1
                    metrics.revision_events += 1
                    revision_entries.append({"row": row, "event": event})
                    save_checkpoint(
                        checkpoint_root,
                        run_id,
                        "revision_log",
                        {
                            "revisions": revision_entries,
                        },
                    )
                    run_store.log(
                        run_id,
                        "info",
                        "revision_logged",
                        "revision updated",
                        source_id=source_id,
                        record_key=str(row.get("event_id", "")),
                    )
                else:
                    metrics.updated_events += 1
            except Exception as exc:
                failure_source_id = source_id or "unknown_source"
                failure_source_name = source_name or failure_source_id
                failure_source_url = source_url or url
                classify_error_detail = _format_source_failure_error(
                    source_id=failure_source_id,
                    source_name=failure_source_name,
                    source_url=failure_source_url,
                    failing_url=url,
                    error_text=str(exc),
                )
                if failure_source_id not in runtime_error_alerted_sources:
                    metrics.failed_sources += 1
                    runtime_error_alerted_sources.add(failure_source_id)
                run_store.log(
                    run_id,
                    "error",
                    "source_failure",
                    classify_error_detail,
                    source_id=failure_source_id,
                    record_key=url,
                )
                if error_slack is not None:
                    if post_slack_error_alert(
                        slack=error_slack,
                        run_store=run_store,
                        run_id=run_id,
                        source_name=failure_source_name,
                        error_text=classify_error_detail,
                    ):
                        metrics.slack_alerts += 1
                continue
    else:
        run_store.log(run_id, "info", "ingestion", "ingestion skipped by runtime control")
        save_checkpoint(
            checkpoint_root,
            run_id,
            "ingest_source",
            {
                "active_sources": [],
                "source_results": [],
                "pending_items": [],
                "skipped": True,
                "raw_snapshot_run_id": active_snapshot_run_id,
                "raw_snapshot_file": str(raw_snapshot_path),
            },
        )

    if not master_normalized_batch_saved:
        save_master_normalized_batch_checkpoint(
            checkpoint_root,
            run_id,
            {
                "run_id": run_id,
                "raw_snapshot_run_id": active_snapshot_run_id,
                "total_items": len(master_normalized_records),
                "items": master_normalized_records,
            },
        )

    if not classify_inputs and not classify_outputs:
        save_checkpoint(
            checkpoint_root,
            run_id,
            "classify",
            {
                "total_items": 0,
                "input_items": [],
                "output_events": [],
            },
        )
    if not dedupe_actions:
        save_checkpoint(checkpoint_root, run_id, "dedupe", {"actions": []})
    if not airtable_event_rows:
        save_checkpoint(checkpoint_root, run_id, "airtable_events", {"results": []})
    if not revision_entries:
        save_checkpoint(checkpoint_root, run_id, "revision_log", {"revisions": []})

    summary_cfg = required_obj(cfg, "summary")
    events: list[dict[str, Any]] = []
    for action_entry in dedupe_actions:
        if not isinstance(action_entry, dict):
            continue
        event_payload = action_entry.get("event")
        if not isinstance(event_payload, dict):
            continue
        event_copy = dict(event_payload)
        row_payload = action_entry.get("row")
        if isinstance(row_payload, dict):
            record_id = str(row_payload.get("__record_id", "")).strip()
            event_id = str(row_payload.get("event_id", "")).strip()
            if record_id:
                event_copy["__record_id"] = record_id
            if event_id and not str(event_copy.get("event_id", "")).strip():
                event_copy["event_id"] = event_id
        events.append(event_copy)
    summary_events = events + transient_summary_events
    today = _runtime_now(cfg)
    daily_text = ""
    weekly_text = ""
    weekly_draft_text = ""
    save_checkpoint(
        checkpoint_root,
        run_id,
        "summary_route",
        {
            "event_count": len(events),
            "summary_event_count": len(summary_events),
            "transient_summary_events": transient_summary_events,
        },
    )
    output_timestamp = _output_timestamp_label(today)
    daily_file_base = resolve_path(required_text(summary_cfg, "daily_output_file"), config_path)
    weekly_file_base = resolve_path(required_text(summary_cfg, "weekly_output_file"), config_path)
    weekly_draft_file_base = resolve_path(required_text(summary_cfg, "weekly_substack_draft_file"), config_path)
    daily_file = _timestamped_output_path(daily_file_base, output_timestamp)
    weekly_file = _timestamped_output_path(weekly_file_base, output_timestamp)
    weekly_draft_file = _timestamped_output_path(weekly_draft_file_base, output_timestamp)
    weekly_draft_html_file = weekly_draft_file.with_suffix(".html")
    if daily_summary_enabled:
        save_checkpoint(
            checkpoint_root,
            run_id,
            "summary_daily",
            {
                "today": today.isoformat(),
                "summary_events": summary_events,
                "output_file": str(daily_file),
            },
        )
        daily_text = build_daily_summary(summary_events, today)
        daily_file.parent.mkdir(parents=True, exist_ok=True)
        daily_file.write_text(daily_text, encoding="utf-8")
        run_store.log(run_id, "info", "summary_daily", f"daily summary written {daily_file}")
        save_checkpoint(
            checkpoint_root,
            run_id,
            "summary_daily",
            {
                "today": today.isoformat(),
                "summary_events": summary_events,
                "output_file": str(daily_file),
                "summary_text": daily_text,
            },
        )
    else:
        run_store.log(run_id, "info", "summary_daily", "daily summary skipped by runtime control")
        save_checkpoint(
            checkpoint_root,
            run_id,
            "summary_daily",
            {
                "today": today.isoformat(),
                "summary_events": summary_events,
                "output_file": str(daily_file),
                "skipped": True,
            },
        )

    if weekly_summary_enabled:
        substack_events = airtable.load_events() + airtable.load_news()
        if not substack_events:
            substack_events = list(summary_events)
        run_store.log(run_id, "info", "summary_weekly", "building weekly summary")
        save_checkpoint(
            checkpoint_root,
            run_id,
            "summary_weekly",
            {
                "today": today.isoformat(),
                "summary_events": substack_events,
                "output_file": str(weekly_file),
            },
        )
        weekly_text = build_weekly_summary(substack_events, today)
        save_checkpoint(
            checkpoint_root,
            run_id,
            "ai_weekly_draft",
            {
                "today": today.isoformat(),
                "summary_events": substack_events,
                "output_file": str(weekly_draft_file),
            },
        )
        weekly_draft_text, audit_data = build_weekly_substack_draft(
            substack_events,
            today,
            logic=logic,
            run_store=run_store,
            run_id=run_id,
            article_format_config=article_format_config,
        )

        # Extract title from markdown for filename
        title_filename = _extract_title_for_filename(weekly_draft_text)
        if title_filename:
            # Use title-based filename for draft files
            weekly_draft_file = weekly_draft_file_base.parent / f"{title_filename}.md"
            weekly_draft_html_file = weekly_draft_file_base.parent / f"{title_filename}.html"
        else:
            # Fallback to timestamped if title extraction fails
            weekly_draft_file = _timestamped_output_path(weekly_draft_file_base, output_timestamp)
            weekly_draft_html_file = weekly_draft_file.with_suffix(".html")

        weekly_file.parent.mkdir(parents=True, exist_ok=True)
        weekly_draft_file.parent.mkdir(parents=True, exist_ok=True)
        weekly_file.write_text(weekly_text, encoding="utf-8")
        weekly_draft_file.write_text(weekly_draft_text, encoding="utf-8")
        weekly_draft_html_file.write_text(_render_weekly_html(weekly_draft_text), encoding="utf-8")

        # Generate audit report
        audit_report_html = _generate_newsletter_audit_report(
            all_events=audit_data["selected_events"],
            selected_events=audit_data["selected_events"],
            start_date=audit_data["start_date"],
            end_date=audit_data["end_date"],
        )
        if title_filename:
            audit_report_file = weekly_draft_file_base.parent / f"{title_filename} - Audit Report.html"
        else:
            audit_report_file = weekly_draft_file.with_stem(f"{weekly_draft_file.stem} - Audit Report").with_suffix(".html")
        audit_report_file.write_text(audit_report_html, encoding="utf-8")

        run_store.log(run_id, "info", "summary_weekly", f"weekly summary written {weekly_file}")
        run_store.log(run_id, "info", "summary_weekly_draft", f"weekly Substack draft written {weekly_draft_file}")
        run_store.log(run_id, "info", "audit_report", f"audit report written {audit_report_file}")
        save_checkpoint(
            checkpoint_root,
            run_id,
            "summary_weekly",
            {
                "today": today.isoformat(),
                "summary_events": substack_events,
                "output_file": str(weekly_file),
                "summary_text": weekly_text,
            },
        )
        save_checkpoint(
            checkpoint_root,
            run_id,
            "ai_weekly_draft",
            {
                "today": today.isoformat(),
                "summary_events": substack_events,
                "output_file": str(weekly_draft_file),
                "draft_text": weekly_draft_text,
            },
        )
    else:
        run_store.log(run_id, "info", "summary_weekly", "weekly summary skipped by runtime control")
        run_store.log(run_id, "info", "summary_weekly_draft", "weekly Substack draft skipped by runtime control")
        save_checkpoint(
            checkpoint_root,
            run_id,
            "summary_weekly",
            {
                "today": today.isoformat(),
                "summary_events": summary_events,
                "output_file": str(weekly_file),
                "skipped": True,
            },
        )
        save_checkpoint(
            checkpoint_root,
            run_id,
            "ai_weekly_draft",
            {
                "today": today.isoformat(),
                "summary_events": summary_events,
                "output_file": str(weekly_draft_file),
                "skipped": True,
            },
        )

    post_category_backfill_result: dict[str, Any] = {
        "enabled": post_category_backfill_enabled,
        "eligible": bool(execution_mode == "live" and not dry_run and not effective_test_slack_only),
        "attempted": False,
        "success": False,
        "skipped_reason": "",
        "error": "",
        "scripts": [],
    }
    if not post_category_backfill_enabled:
        post_category_backfill_result["skipped_reason"] = "runtime_control_disabled"
        run_store.log(run_id, "info", "post_category_backfill", "skipped by runtime control", record_key=run_id)
    elif execution_mode != "live":
        post_category_backfill_result["skipped_reason"] = f"mode_{execution_mode}"
        run_store.log(
            run_id,
            "info",
            "post_category_backfill",
            f"skipped because mode is {execution_mode}",
            record_key=run_id,
        )
    elif dry_run:
        post_category_backfill_result["skipped_reason"] = "dry_run"
        run_store.log(run_id, "info", "post_category_backfill", "skipped because dry_run is true", record_key=run_id)
    elif effective_test_slack_only:
        post_category_backfill_result["skipped_reason"] = "test_slack_only"
        run_store.log(
            run_id,
            "info",
            "post_category_backfill",
            "skipped because test_slack_only is enabled",
            record_key=run_id,
        )
    else:
        post_category_backfill_result["attempted"] = True
        run_store.log(run_id, "info", "post_category_backfill", "starting post-category backfill scripts", record_key=run_id)
        try:
            script_results = _run_post_category_backfill_scripts(
                project_root=config_path.resolve().parent,
                config_path=config_path.resolve(),
                run_store=run_store,
                run_id=run_id,
            )
            post_category_backfill_result["scripts"] = script_results
            post_category_backfill_result["success"] = True
            run_store.log(
                run_id,
                "info",
                "post_category_backfill",
                f"completed scripts={len(script_results)}",
                record_key=run_id,
            )
        except Exception as exc:
            post_category_backfill_result["error"] = str(exc)
            metrics.failed_sources += 1
            run_store.log(
                run_id,
                "error",
                "post_category_backfill",
                f"failed: {exc}",
                record_key=run_id,
            )
    save_checkpoint(checkpoint_root, run_id, "post_category_backfill", post_category_backfill_result)

    new_event_ids_by_table = _collect_new_event_ids_by_table(airtable_event_rows)
    post_content_backfill_result: dict[str, Any] = {
        "enabled": post_content_backfill_enabled,
        "eligible": bool(execution_mode == "live" and not dry_run and not effective_test_slack_only),
        "attempted": False,
        "success": False,
        "skipped_reason": "",
        "error": "",
        "event_ids_by_table": new_event_ids_by_table,
        "scripts": [],
    }
    if not post_content_backfill_enabled:
        post_content_backfill_result["skipped_reason"] = "runtime_control_disabled"
        run_store.log(run_id, "info", "post_content_backfill", "skipped by runtime control", record_key=run_id)
    elif execution_mode != "live":
        post_content_backfill_result["skipped_reason"] = f"mode_{execution_mode}"
        run_store.log(
            run_id,
            "info",
            "post_content_backfill",
            f"skipped because mode is {execution_mode}",
            record_key=run_id,
        )
    elif dry_run:
        post_content_backfill_result["skipped_reason"] = "dry_run"
        run_store.log(run_id, "info", "post_content_backfill", "skipped because dry_run is true", record_key=run_id)
    elif effective_test_slack_only:
        post_content_backfill_result["skipped_reason"] = "test_slack_only"
        run_store.log(
            run_id,
            "info",
            "post_content_backfill",
            "skipped because test_slack_only is enabled",
            record_key=run_id,
        )
    elif not new_event_ids_by_table.get("events") and not new_event_ids_by_table.get("news"):
        post_content_backfill_result["skipped_reason"] = "no_new_created_records"
        run_store.log(run_id, "info", "post_content_backfill", "skipped because no new created records", record_key=run_id)
    else:
        post_content_backfill_result["attempted"] = True
        run_store.log(
            run_id,
            "info",
            "post_content_backfill",
            (
                "starting post-content backfill scripts "
                f"events={len(new_event_ids_by_table.get('events', []))} "
                f"news={len(new_event_ids_by_table.get('news', []))}"
            ),
            record_key=run_id,
        )
        try:
            script_results = _run_post_content_backfill_scripts(
                project_root=config_path.resolve().parent,
                config_path=config_path.resolve(),
                run_store=run_store,
                run_id=run_id,
                event_ids_by_table=new_event_ids_by_table,
            )
            post_content_backfill_result["scripts"] = script_results
            post_content_backfill_result["success"] = True
            run_store.log(
                run_id,
                "info",
                "post_content_backfill",
                f"completed scripts={len(script_results)}",
                record_key=run_id,
            )
        except Exception as exc:
            post_content_backfill_result["error"] = str(exc)
            metrics.failed_sources += 1
            run_store.log(
                run_id,
                "error",
                "post_content_backfill",
                f"failed: {exc}",
                record_key=run_id,
            )
    save_checkpoint(checkpoint_root, run_id, "post_content_backfill", post_content_backfill_result)

    status = "completed_with_errors" if metrics.failed_sources > 0 else "completed"
    slack_digest_events = [
        dict(entry.get("event", {}))
        for entry in classify_outputs
        if isinstance(entry, dict) and isinstance(entry.get("event"), dict)
    ]
    raw_slack_digest_text = build_slack_run_digest(slack_digest_events)
    slack_digest_blocks = build_slack_run_blocks(slack_digest_events)
    slack_digest_text = _prepare_slack_digest_for_post(
        raw_slack_digest_text,
        run_store=run_store,
        run_id=run_id,
    )
    save_checkpoint(
        checkpoint_root,
        run_id,
        "email_notify",
        {
            "enabled": email_notifications_enabled,
            "daily_summary_enabled": daily_summary_enabled,
            "content_text": slack_digest_text,
            "metrics": metrics.__dict__,
        },
    )
    if not dry_run and email_notifications_enabled and daily_summary_enabled:
        if emailer is None:
            raise RuntimeError("emailer unavailable while email_notifications_enabled is true")
        emailer.send_daily_summary(run_id=run_id, content_text=slack_digest_text, metrics=metrics)
        metrics.email_summaries += 1
        run_store.log(run_id, "info", "daily_email", "daily summary email sent", record_key=run_id)
    elif not dry_run and not email_notifications_enabled:
        run_store.log(run_id, "info", "daily_email", "daily summary email skipped by runtime control", record_key=run_id)
    elif not dry_run and email_notifications_enabled and not daily_summary_enabled:
        run_store.log(
            run_id,
            "info",
            "daily_email",
            "daily summary email skipped because daily summary is disabled",
            record_key=run_id,
        )
    save_checkpoint(
        checkpoint_root,
        run_id,
        "email_notify",
        {
            "enabled": email_notifications_enabled,
            "daily_summary_enabled": daily_summary_enabled,
            "summary_text": daily_text,
            "metrics": metrics.__dict__,
            "sent": metrics.email_summaries > 0,
        },
    )
    save_checkpoint(
        checkpoint_root,
        run_id,
        "slack_post",
        {
            "enabled": slack_notifications_enabled,
            "status": status,
            "metrics": metrics.__dict__,
            "digest_text_raw": raw_slack_digest_text,
            "digest_text": slack_digest_text,
        },
    )
    if slack is not None and not effective_test_slack_only:
        slack.post_run_summary(run_id=run_id, status=status, metrics=metrics, digest_text=slack_digest_text, digest_blocks=slack_digest_blocks)
        metrics.slack_posts += 1
        run_store.log(run_id, "info", "slack_post", "posted run summary with digest", record_key=run_id)
    elif slack is not None and effective_test_slack_only:
        slack.post_run_summary(run_id=run_id, status=status, metrics=metrics, digest_text=slack_digest_text, digest_blocks=slack_digest_blocks)
        metrics.slack_posts += 1
        run_store.log(run_id, "info", "slack_post", "posted digest summary Slack content (test_slack_only)", record_key=run_id)
    elif not dry_run and not slack_notifications_enabled:
        run_store.log(run_id, "info", "slack_post", "run summary Slack post skipped by runtime control", record_key=run_id)
    save_checkpoint(
        checkpoint_root,
        run_id,
        "slack_post",
        {
            "enabled": slack_notifications_enabled,
            "status": status,
            "metrics": metrics.__dict__,
            "digest_text_raw": raw_slack_digest_text,
            "digest_text": slack_digest_text,
            "sent": metrics.slack_posts > 0,
        },
    )
    slack_payload_records = slack.snapshot_payloads() if slack is not None else []
    slack_payload_file = save_run_level_json_checkpoint(
        checkpoint_root,
        run_id,
        "slack_payloads.json",
        {
            "run_id": run_id,
            "sent": metrics.slack_posts > 0,
            "payload_count": len(slack_payload_records),
            "payloads": slack_payload_records,
        },
    )
    run_store.log(run_id, "info", "slack_post", f"saved Slack payload file {slack_payload_file}", record_key=run_id)

    run_log_payload = {
        "run_id": run_id,
        "ts": utc_now_iso(),
        "mode": execution_mode,
        "metrics": metrics.__dict__,
        "runtime_controls": {
            "email_notifications_enabled": email_notifications_enabled,
            "slack_notifications_enabled": slack_notifications_enabled,
            "daily_summary_enabled": daily_summary_enabled,
            "weekly_summary_enabled": weekly_summary_enabled,
            "ingestion_enabled": ingestion_enabled,
            "ai_enabled": ai_enabled,
            "dedupe_enabled": dedupe_enabled,
            "force_source_failure": force_source_failure,
            "prequal_enabled": prequal_enabled,
            "post_category_backfill_enabled": post_category_backfill_enabled,
            "post_content_backfill_enabled": post_content_backfill_enabled,
        },
        "post_category_backfill": post_category_backfill_result,
        "post_content_backfill": post_content_backfill_result,
        "daily_summary_file": str(daily_file) if daily_summary_enabled else "",
        "weekly_summary_file": str(weekly_file) if weekly_summary_enabled else "",
        "weekly_substack_draft_file": str(weekly_draft_file) if weekly_summary_enabled else "",
        "raw_snapshot_run_id": active_snapshot_run_id,
        "raw_snapshot_file": str(raw_snapshot_path),
        "feed_article_summary_file": str(feed_article_summary_file),
        "feed_article_summary_checkpoint_file": str(feed_article_summary_checkpoint_file),
    }
    save_checkpoint(checkpoint_root, run_id, "run_summary", run_log_payload)
    airtable.append_run_log(run_log_payload)
    run_store.log(run_id, "info", "run_summary", f"status={status} metrics={metrics.__dict__}")
    run_store.finish(run_id, status, metrics)

    out_summary = output_dir / f"{run_id}_summary.json"
    out_summary.write_text(json.dumps(run_log_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    if status in {"completed", "completed_with_errors"} and execution_mode == "live":
        state["seen_urls_by_source"] = staged_seen_by_source
        save_state(state_path, state)
        run_store.log(run_id, "info", "state_commit", f"source state saved {state_path}", record_key=run_id)
    else:
        run_store.log(
            run_id,
            "info",
            "state_commit",
            f"source state deferred because status={status} mode={execution_mode}",
            record_key=run_id,
        )
    save_checkpoint(
        checkpoint_root,
        run_id,
        "complete",
        {
            "status": status,
            "run_id": run_id,
            "metrics": metrics.__dict__,
            "summary_file": str(out_summary),
            "state_path": str(state_path),
        },
    )
    cleanup_active_checkpoints(checkpoint_root, run_id)

    print(f"run_id={run_id}")
    print(f"status={status}")
    print(f"metrics={metrics.__dict__}")
    print(f"summary_file={out_summary}")
    return 1 if status != "completed" else 0


REPLAY_DEPENDENCIES: dict[str, list[str]] = {
    "run": [],
    "load_config": [],
    "schema_audit": [],
    "load_prompts": [],
    "runtime_controls": [],
    "load_sources": [],
    "ingest_source": [],
    "classify": ["ingest_source"],
    "dedupe": ["classify"],
    "airtable_events": ["dedupe"],
    "revision_log": ["dedupe"],
    "summary_route": ["classify"],
    "summary_daily": ["summary_route"],
    "summary_weekly": ["summary_route"],
    "ai_weekly_draft": ["summary_route"],
    "email_notify": ["summary_daily"],
    "slack_post": [],
    "run_summary": [],
    "complete": ["run_summary"],
}


def _metrics_from_checkpoint_payload(payload: dict[str, Any]) -> RunMetrics:
    metrics = RunMetrics()
    for key, value in payload.items():
        if hasattr(metrics, key):
            setattr(metrics, key, int(value))
    return metrics


def _load_branch_metrics(checkpoint_root: Path, checkpoint_run_id: str) -> RunMetrics:
    summary_payload = load_effective_checkpoint(checkpoint_root, checkpoint_run_id, "run_summary")
    metrics_payload = summary_payload.get("metrics")
    if not isinstance(metrics_payload, dict):
        raise RuntimeError("run_summary checkpoint missing metrics")
    return _metrics_from_checkpoint_payload(metrics_payload)


def _summary_events_from_classify_payload(classify_payload: dict[str, Any]) -> list[dict[str, Any]]:
    output_events = classify_payload.get("output_events")
    if not isinstance(output_events, list):
        raise RuntimeError("classify checkpoint missing output_events")
    summary_events: list[dict[str, Any]] = []
    for entry in output_events:
        if not isinstance(entry, dict):
            raise RuntimeError("classify checkpoint output_events must contain objects")
        event = entry.get("event")
        if not isinstance(event, dict):
            raise RuntimeError("classify checkpoint output event missing event payload")
        if str(event.get("event_type", "")).strip() == "irrelevant":
            continue
        summary_events.append(event)
    return summary_events


def _canonical_events_from_classify_payload(classify_payload: dict[str, Any]) -> list[dict[str, Any]]:
    output_events = classify_payload.get("output_events")
    if not isinstance(output_events, list):
        raise RuntimeError("classify checkpoint missing output_events")
    canonical: list[dict[str, Any]] = []
    for entry in output_events:
        if not isinstance(entry, dict):
            raise RuntimeError("classify checkpoint output_events must contain objects")
        event = entry.get("event")
        if not isinstance(event, dict):
            raise RuntimeError("classify checkpoint output event missing event payload")
        if str(event.get("event_type", "")).strip() == "irrelevant":
            continue
        canonical.append({"source_id": str(entry.get("source_id", "")), "url": str(entry.get("url", "")), "event": event})
    return canonical


def _load_optional_effective_checkpoint(checkpoint_root: Path, run_id: str, node_id: str) -> dict[str, Any] | None:
    try:
        return load_effective_checkpoint(checkpoint_root, run_id, node_id)
    except Exception:
        return None


def _source_run_started_at(state_dir: Path, run_id: str) -> datetime:
    db_path = state_dir / "consumer_vc_v1.db"
    if not db_path.exists():
        raise RuntimeError(f"run database not found: {db_path}")
    with sqlite3.connect(str(db_path), timeout=10) as conn:
        row = conn.execute("SELECT started_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"run not found: {run_id}")
    return parse_iso(str(row[0]))


def _replay_chain_for_target(checkpoint_root: Path, checkpoint_run_id: str, node_id: str) -> list[str]:
    if node_id not in REPLAY_DEPENDENCIES:
        raise RuntimeError(f"unsupported replay node: {node_id}")
    chain: list[str] = []
    added: set[str] = set()

    def ensure(node_name: str) -> None:
        deps = REPLAY_DEPENDENCIES.get(node_name)
        if deps is None:
            raise RuntimeError(f"unsupported replay node: {node_name}")
        for dep in deps:
            payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, dep)
            if payload is None:
                ensure(dep)
                if dep not in added:
                    chain.append(dep)
                    added.add(dep)

    ensure(node_id)
    chain.append(node_id)
    return chain


def replay_node_from_checkpoint(
    config_path: Path,
    checkpoint_run_id: str,
    node_id: str,
    weekly_prompt_name: str = "",
    content_start_date: str = "",
    content_end_date: str = "",
) -> int:
    replay_target = str(node_id or "").strip()
    replay_plan = _replay_chain_for_target(checkpoint_root_for_config(config_path), checkpoint_run_id, replay_target)
    if not replay_plan:
        raise RuntimeError(f"unsupported replay node: {node_id}")

    content_start_text = str(content_start_date or "").strip()
    content_end_text = str(content_end_date or "").strip()
    if bool(content_start_text) != bool(content_end_text):
        raise RuntimeError("content_start_date and content_end_date must both be provided or both be empty")
    content_start_override: datetime.date | None = None
    content_end_override: datetime.date | None = None
    if content_start_text and content_end_text:
        content_start_override = parse_iso_date(content_start_text, field_name="content_start_date")
        content_end_override = parse_iso_date(content_end_text, field_name="content_end_date")
        if content_start_override > content_end_override:
            raise RuntimeError("content_start_date must be on or before content_end_date")

    cfg = load_config(config_path)
    runtime = required_obj(cfg, "runtime")
    summary_cfg = required_obj(cfg, "summary")
    state_dir = resolve_path(required_text(runtime, "state_dir"), config_path)
    activity_log_path = resolve_path(required_text(runtime, "activity_log_file"), config_path)
    checkpoint_root = checkpoint_root_for_config(config_path)
    state_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_root.mkdir(parents=True, exist_ok=True)

    db_path = state_dir / "consumer_vc_v1.db"
    run_store = RunStore(db_path=db_path, activity_log_path=activity_log_path)
    run_id = run_store.start_run(mode=f"replay_from:{replay_target}")
    replay_output_timestamp = _output_timestamp_label()
    run_store.log(run_id, "info", "start", f"replay started source_run={checkpoint_run_id} node={replay_target}")
    if content_start_override is not None and content_end_override is not None:
        run_store.log(
            run_id,
            "info",
            "summary_weekly",
            f"content date override start={content_start_override.isoformat()} end={content_end_override.isoformat()}",
            record_key=replay_target,
        )

    metrics = _load_branch_metrics(checkpoint_root, checkpoint_run_id)
    status = "completed"

    try:
        airtable = AirtableStore(cfg)
        current_runtime_controls = airtable.load_runtime_controls()
        article_format_config = airtable.load_article_format()
        logic_cache: dict[str, Any] | None = None
        weekly_prompt_override_text = ""
        weekly_prompt_selected_name = ""
        if replay_target == "ai_weekly_draft":
            selected_prompt_name = str(weekly_prompt_name or "").strip()
            if selected_prompt_name:
                selected_prompt = airtable.resolve_substack_prompt_text(selected_prompt_name)
                weekly_prompt_selected_name = selected_prompt["name"]
                weekly_prompt_override_text = selected_prompt["prompt_text"]
                run_store.log(
                    run_id,
                    "info",
                    "summary_weekly_draft",
                    f"manual prompt selected name={weekly_prompt_selected_name}",
                    record_key=replay_target,
                )
            else:
                substack_prompt_sync = airtable.sync_current_substack_prompt()
                logic_cache = None
                if substack_prompt_sync:
                    weekly_prompt_selected_name = str(substack_prompt_sync.get("selected_name", "")).strip()
                    run_store.log(
                        run_id,
                        "info",
                        "substack_prompt_sync",
                        (
                            f"selected_name={substack_prompt_sync['selected_name']} "
                            f"updated_prompts_text={substack_prompt_sync['updated_prompts_text']}"
                        ),
                        record_key=replay_target,
                    )
        stage_aliases = {
            "runtime_controls": "load_runtime_controls",
            "airtable_events": "upsert_event",
            "revision_log": "revision_logged",
            "ai_weekly_draft": "summary_weekly_draft",
            "email_notify": "daily_email",
        }

        def current_logic() -> dict[str, Any]:
            nonlocal logic_cache
            if logic_cache is None:
                logic_cache = build_runtime_logic(
                    airtable.load_prompts(),
                    config_path,
                    categories=airtable.load_categories(),
                )
            return logic_cache

        def effective(node_name: str) -> dict[str, Any]:
            return load_effective_checkpoint(checkpoint_root, checkpoint_run_id, node_name)

        for current_node in replay_plan:
            stage_name = stage_aliases.get(current_node, current_node)
            run_store.log(run_id, "info", stage_name, "replay started", record_key=current_node)
            result_payload: dict[str, Any]

            if current_node == "run":
                result_payload = dict(effective("run"))
            elif current_node == "load_config":
                replay_cfg = load_config(config_path)
                result_payload = {"config_path": str(config_path), "config_keys": sorted(replay_cfg.keys())}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "load_config", result_payload)
            elif current_node == "schema_audit":
                result_payload = {"schema": airtable.validate_required_schema()}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "schema_audit", result_payload)
            elif current_node == "load_prompts":
                result_payload = {"prompts": airtable.load_prompts()}
                logic_cache = None
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "load_prompts", result_payload)
            elif current_node == "runtime_controls":
                current_runtime_controls = airtable.load_runtime_controls()
                result_payload = {"controls": current_runtime_controls}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "runtime_controls", result_payload)
            elif current_node == "load_sources":
                result_payload = {"sources": airtable.load_sources()}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "load_sources", result_payload)
            elif current_node == "ingest_source":
                result_payload = dict(effective("ingest_source"))
            elif current_node == "classify":
                classify_source = effective("classify")
                input_items = classify_source.get("input_items")
                if not isinstance(input_items, list):
                    ingest_payload = effective("ingest_source")
                    input_items = ingest_payload.get("pending_items")
                if not isinstance(input_items, list):
                    raise RuntimeError("classify replay requires input_items or pending_items")
                output_events: list[dict[str, Any]] = []
                total_items = len(input_items)
                for index, item in enumerate(input_items, start=1):
                    if not isinstance(item, dict):
                        raise RuntimeError("classify replay input_items must contain objects")
                    url = str(item.get("url", "")).strip()
                    source_id = str(item.get("source_id", "")).strip()
                    source_name = str(item.get("source_name", "")).strip() or source_id
                    run_store.log(run_id, "info", "classify_progress", f"{index}/{total_items} | {source_name}", source_id=source_id, record_key=url)
                    run_store.log(run_id, "info", "classify", "classifying item", source_id=source_id, record_key=url)
                    event = classify_and_extract(
                        {
                            "title": str(item.get("title", "")),
                            "summary": str(item.get("summary", "")),
                            "url": url,
                            "source_id": source_id,
                            "source_name": str(item.get("source_name", "")),
                            "published_at": str(item.get("published_at", "")),
                            "request_timeout_seconds": int(item.get("request_timeout_seconds", 30) or 30),
                        },
                        current_logic(),
                        run_store=run_store,
                        run_id=run_id,
                        source_id=source_id,
                        record_key=url,
                        request_timeout_seconds=int(item.get("request_timeout_seconds", 30) or 30),
                    )
                    output_events.append({"source_id": source_id, "url": url, "event": event})
                metrics.discarded_irrelevant = sum(1 for entry in output_events if isinstance(entry, dict) and isinstance(entry.get("event"), dict) and str(entry["event"].get("event_type", "")).strip() == "irrelevant")
                result_payload = {"total_items": total_items, "input_items": input_items, "output_events": output_events}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "classify", result_payload)
            elif current_node in {"dedupe", "airtable_events"}:
                dedupe_enabled = bool(current_runtime_controls.get("dedupe_enabled", True))
                if current_node == "dedupe":
                    canonical_events = _canonical_events_from_classify_payload(effective("classify"))
                    logic = current_logic()
                    dedupe_actions: list[dict[str, Any]] = []
                    dedupe_state: dict[str, dict[str, Any]] = {}
                    created_events = 0
                    updated_events = 0
                    for entry in canonical_events:
                        event = required_obj(entry, "event")
                        source_id = str(entry.get("source_id", "")).strip()
                        url = str(entry.get("url", "")).strip()
                        run_store.log(run_id, "info", "dedupe", "dedupe check", source_id=source_id, record_key=url)
                        if dedupe_enabled:
                            action, row = upsert_event(airtable, event, current_logic(), dedupe_state=dedupe_state)
                        else:
                            action, row = create_event_without_dedupe(
                                airtable,
                                event,
                                current_logic(),
                                record_key=url,
                                dedupe_state=dedupe_state,
                            )
                        dedupe_actions.append({"source_id": source_id, "url": url, "action": action, "event": event, "row": row})
                        if action in {"created", "created_no_dedupe"}:
                            created_events += 1
                        elif action == "updated":
                            updated_events += 1
                    metrics.created_events = created_events
                    metrics.updated_events = updated_events
                    save_active_checkpoint(checkpoint_root, checkpoint_run_id, "dedupe", {"actions": dedupe_actions})
                    result_payload = {"actions": dedupe_actions}
                else:
                    dedupe_payload = effective("dedupe")
                    actions = required_list(dedupe_payload, "actions")
                    airtable_results: list[dict[str, Any]] = []
                    dedupe_state: dict[str, dict[str, Any]] = {}
                    for entry in actions:
                        if not isinstance(entry, dict):
                            raise RuntimeError("dedupe checkpoint actions must contain objects")
                        source_id = str(entry.get("source_id", "")).strip()
                        event = required_obj(entry, "event")
                        url = str(entry.get("url", "")).strip()
                        if dedupe_enabled:
                            action, row = upsert_event(airtable, event, current_logic(), dedupe_state=dedupe_state)
                        else:
                            action, row = create_event_without_dedupe(
                                airtable,
                                event,
                                current_logic(),
                                record_key=url,
                                dedupe_state=dedupe_state,
                            )
                        run_store.log(run_id, "info", "upsert_event", action, source_id=source_id, record_key=str(row.get("event_id", "")))
                        airtable_results.append({"action": action, "row": row})
                    save_active_checkpoint(checkpoint_root, checkpoint_run_id, "airtable_events", {"results": airtable_results})
                    result_payload = {"results": airtable_results}
            elif current_node == "revision_log":
                dedupe_payload = effective("dedupe")
                actions = required_list(dedupe_payload, "actions")
                revisions = [entry for entry in actions if isinstance(entry, dict) and str(entry.get("action", "")).strip() == "updated"]
                metrics.revision_events = len(revisions)
                result_payload = {"revisions": revisions}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "revision_log", result_payload)
            elif current_node == "summary_route":
                summary_events = _summary_events_from_classify_payload(effective("classify"))
                transient_summary_events = [event for event in summary_events if str(event.get("event_type", "")).strip() not in {"funding_round", "m_and_a_transaction"}]
                result_payload = {"event_count": len(summary_events) - len(transient_summary_events), "summary_event_count": len(summary_events), "transient_summary_events": transient_summary_events, "summary_events": summary_events}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "summary_route", result_payload)
            elif current_node == "summary_daily":
                summary_route_payload = effective("summary_route")
                summary_events = summary_route_payload.get("summary_events")
                if not isinstance(summary_events, list):
                    summary_events = _summary_events_from_classify_payload(effective("classify"))
                    save_active_checkpoint(
                        checkpoint_root,
                        checkpoint_run_id,
                        "summary_route",
                        {
                            "event_count": len(
                                [
                                    event
                                    for event in summary_events
                                    if str(event.get("event_type", "")).strip() in {"funding_round", "m_and_a_transaction"}
                                ]
                            ),
                            "summary_event_count": len(summary_events),
                            "transient_summary_events": [
                                event
                                for event in summary_events
                                if str(event.get("event_type", "")).strip() not in {"funding_round", "m_and_a_transaction"}
                            ],
                            "summary_events": summary_events,
                        },
                    )
                existing_payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, "summary_daily")
                today = parse_iso(required_text(existing_payload, "today")) if isinstance(existing_payload, dict) else _source_run_started_at(state_dir, checkpoint_run_id)
                output_file = _timestamped_output_path(
                    resolve_path(required_text(summary_cfg, "daily_output_file"), config_path),
                    replay_output_timestamp,
                )
                summary_text = build_daily_summary(summary_events, today)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(summary_text, encoding="utf-8")
                result_payload = {"today": today.isoformat(), "summary_events": summary_events, "output_file": str(output_file), "summary_text": summary_text}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "summary_daily", result_payload)
            elif current_node == "summary_weekly":
                if content_start_override is not None and content_end_override is not None:
                    summary_events = airtable.load_events() + airtable.load_news()
                    today = datetime.combine(content_end_override, datetime.min.time(), tzinfo=timezone.utc)
                else:
                    summary_route_payload = effective("summary_route")
                    summary_events = summary_route_payload.get("summary_events")
                    if not isinstance(summary_events, list):
                        summary_events = _summary_events_from_classify_payload(effective("classify"))
                        save_active_checkpoint(
                            checkpoint_root,
                            checkpoint_run_id,
                            "summary_route",
                            {
                                "event_count": len(
                                    [
                                        event
                                        for event in summary_events
                                        if str(event.get("event_type", "")).strip() in {"funding_round", "m_and_a_transaction"}
                                    ]
                                ),
                                "summary_event_count": len(summary_events),
                                "transient_summary_events": [
                                    event
                                    for event in summary_events
                                    if str(event.get("event_type", "")).strip() not in {"funding_round", "m_and_a_transaction"}
                                ],
                                "summary_events": summary_events,
                            },
                        )
                    existing_payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, "summary_weekly")
                    today = parse_iso(required_text(existing_payload, "today")) if isinstance(existing_payload, dict) else _source_run_started_at(state_dir, checkpoint_run_id)
                output_file = _timestamped_output_path(
                    resolve_path(required_text(summary_cfg, "weekly_output_file"), config_path),
                    replay_output_timestamp,
                )
                summary_text = build_weekly_summary(
                    summary_events,
                    today,
                    start_override=content_start_override,
                    end_override=content_end_override,
                )
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(summary_text, encoding="utf-8")
                result_payload = {
                    "today": today.isoformat(),
                    "summary_events": summary_events,
                    "output_file": str(output_file),
                    "summary_text": summary_text,
                    "content_source": "airtable" if content_start_override is not None and content_end_override is not None else "checkpoint",
                    "content_start_date": content_start_override.isoformat() if content_start_override is not None else "",
                    "content_end_date": content_end_override.isoformat() if content_end_override is not None else "",
                }
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "summary_weekly", result_payload)
            elif current_node == "ai_weekly_draft":
                if content_start_override is not None and content_end_override is not None:
                    summary_events = airtable.load_events() + airtable.load_news()
                    today = datetime.combine(content_end_override, datetime.min.time(), tzinfo=timezone.utc)
                else:
                    summary_route_payload = effective("summary_route")
                    summary_events = summary_route_payload.get("summary_events")
                    if not isinstance(summary_events, list):
                        summary_events = _summary_events_from_classify_payload(effective("classify"))
                        save_active_checkpoint(
                            checkpoint_root,
                            checkpoint_run_id,
                            "summary_route",
                            {
                                "event_count": len(
                                    [
                                        event
                                        for event in summary_events
                                        if str(event.get("event_type", "")).strip() in {"funding_round", "m_and_a_transaction"}
                                    ]
                                ),
                                "summary_event_count": len(summary_events),
                                "transient_summary_events": [
                                    event
                                    for event in summary_events
                                    if str(event.get("event_type", "")).strip() not in {"funding_round", "m_and_a_transaction"}
                                ],
                                "summary_events": summary_events,
                            },
                        )
                    existing_payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, "ai_weekly_draft")
                    today = parse_iso(required_text(existing_payload, "today")) if isinstance(existing_payload, dict) else _source_run_started_at(state_dir, checkpoint_run_id)
                active_article_field = str(article_format_config.get("active_field", "")).strip()
                if active_article_field and active_article_field != "SlackContent":
                    has_active_content = any(
                        isinstance(event, dict) and str(event.get(active_article_field, "")).strip()
                        for event in summary_events
                    )
                    if not has_active_content:
                        summary_events = airtable.load_events() + airtable.load_news()
                        run_store.log(
                            run_id,
                            "info",
                            "summary_weekly_draft",
                            f"reloaded summary_events from Airtable for article format field={active_article_field}",
                            record_key=current_node,
                        )
                output_file = _timestamped_output_path(
                    resolve_path(required_text(summary_cfg, "weekly_substack_draft_file"), config_path),
                    replay_output_timestamp,
                )
                weekly_logic = dict(current_logic())
                if weekly_prompt_override_text:
                    weekly_logic["ai_weekly_writer_prompt"] = weekly_prompt_override_text
                draft_text, audit_data = build_weekly_substack_draft(
                    summary_events,
                    today,
                    logic=weekly_logic,
                    run_store=run_store,
                    run_id=run_id,
                    article_format_config=article_format_config,
                    start_override=content_start_override,
                    end_override=content_end_override,
                )

                # Extract title from markdown for filename
                output_file_base = resolve_path(required_text(summary_cfg, "weekly_substack_draft_file"), config_path)
                title_filename = _extract_title_for_filename(draft_text)
                if title_filename:
                    # Use title-based filename for draft files
                    output_file = output_file_base.parent / f"{title_filename}.md"
                    output_html_file = output_file_base.parent / f"{title_filename}.html"
                else:
                    # Fallback to timestamped if title extraction fails
                    output_html_file = output_file.with_suffix(".html")

                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(draft_text, encoding="utf-8")
                output_html_file.write_text(_render_weekly_html(draft_text), encoding="utf-8")

                # Generate audit report
                audit_report_html = _generate_newsletter_audit_report(
                    all_events=audit_data["selected_events"],
                    selected_events=audit_data["selected_events"],
                    start_date=audit_data["start_date"],
                    end_date=audit_data["end_date"],
                )
                if title_filename:
                    audit_report_file = output_file_base.parent / f"{title_filename} - Audit Report.html"
                else:
                    audit_report_file = output_file.with_stem(f"{output_file.stem} - Audit Report").with_suffix(".html")
                audit_report_file.write_text(audit_report_html, encoding="utf-8")

                result_payload = {
                    "today": today.isoformat(),
                    "summary_events": summary_events,
                    "output_file": str(output_file),
                    "draft_text": draft_text,
                    "prompt_name": weekly_prompt_selected_name,
                    "prompt_override": bool(weekly_prompt_override_text),
                    "content_source": "airtable" if content_start_override is not None and content_end_override is not None else "checkpoint",
                    "content_start_date": content_start_override.isoformat() if content_start_override is not None else "",
                    "content_end_date": content_end_override.isoformat() if content_end_override is not None else "",
                }
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "ai_weekly_draft", result_payload)
            elif current_node == "email_notify":
                email_payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, "email_notify") or {}
                slack_payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, "slack_post") or {}
                content_text = required_text(slack_payload, "digest_text")
                email_enabled = bool(email_payload.get("enabled", current_runtime_controls.get("email_notifications_enabled", False)))
                daily_summary_enabled = bool(email_payload.get("daily_summary_enabled", current_runtime_controls.get("daily_summary_enabled", False)))
                sent = False
                if email_enabled and daily_summary_enabled:
                    EmailNotifier(cfg, config_path).send_daily_summary(run_id=run_id, content_text=content_text, metrics=metrics)
                    run_store.log(run_id, "info", "daily_email", "daily summary email sent", record_key=checkpoint_run_id)
                    sent = True
                elif not email_enabled:
                    run_store.log(run_id, "info", "daily_email", "daily summary email skipped by runtime control", record_key=checkpoint_run_id)
                else:
                    run_store.log(run_id, "info", "daily_email", "daily summary email skipped because daily summary is disabled", record_key=checkpoint_run_id)
                result_payload = {"enabled": email_enabled, "daily_summary_enabled": daily_summary_enabled, "content_text": content_text, "metrics": metrics.__dict__, "sent": sent}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "email_notify", result_payload)
            elif current_node == "slack_post":
                slack_payload = _load_optional_effective_checkpoint(checkpoint_root, checkpoint_run_id, "slack_post") or {}
                slack_enabled = bool(slack_payload.get("enabled", current_runtime_controls.get("slack_notifications_enabled", False)))
                digest_text = str(slack_payload.get("digest_text", "")).strip()
                digest_text = _prepare_slack_digest_for_post(
                    digest_text,
                    run_store=run_store,
                    run_id=run_id,
                )
                sent = False
                if slack_enabled:
                    SlackNotifier(cfg, config_path, run_store=run_store, run_id=run_id).post_run_summary(
                        run_id=run_id,
                        status=status,
                        metrics=metrics,
                        digest_text=digest_text,
                    )
                    run_store.log(run_id, "info", "slack_post", "posted run summary", record_key=checkpoint_run_id)
                    sent = True
                else:
                    run_store.log(run_id, "info", "slack_post", "run summary Slack post skipped by runtime control", record_key=checkpoint_run_id)
                result_payload = {
                    "enabled": slack_enabled,
                    "status": status,
                    "metrics": metrics.__dict__,
                    "digest_text": digest_text,
                    "sent": sent,
                }
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "slack_post", result_payload)
            elif current_node == "run_summary":
                result_payload = {"run_id": checkpoint_run_id, "status": status, "metrics": metrics.__dict__, "replayed_from_node": replay_target, "last_replay_run_id": run_id}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "run_summary", result_payload)
            elif current_node == "complete":
                result_payload = {"status": status, "run_id": checkpoint_run_id, "replayed_from_node": replay_target, "last_replay_run_id": run_id}
                save_active_checkpoint(checkpoint_root, checkpoint_run_id, "complete", result_payload)
                cleanup_active_checkpoints(checkpoint_root, checkpoint_run_id)
            else:
                raise RuntimeError(f"unsupported replay node: {current_node}")

            run_store.log(run_id, "info", stage_name, "replay completed", record_key=current_node)

        run_store.finish(run_id, "completed", metrics)
        print(f"run_id={run_id}")
        print("status=completed")
        print(f"node_id={replay_target}")
        print(f"source_run_id={checkpoint_run_id}")
        print(f"replay_plan={','.join(replay_plan)}")
        return 0
    except Exception:
        run_store.finish(run_id, "failed", metrics)
        raise

def run_weekly_summary_only(config_path: Path) -> int:
    cfg = load_config(config_path)
    mode_snapshot = enforce_live_execution_modes(cfg)
    runtime = required_obj(cfg, "runtime")
    state_dir = resolve_path(required_text(runtime, "state_dir"), config_path)
    activity_log_path = resolve_path(required_text(runtime, "activity_log_file"), config_path)
    state_dir.mkdir(parents=True, exist_ok=True)
    run_store = RunStore(db_path=state_dir / "consumer_vc_v1.db", activity_log_path=activity_log_path)
    run_id = run_store.start_run(mode="weekly_summary_only")
    run_store.log(run_id, "info", "start", "weekly summary run started")
    run_store.log(
        run_id,
        "info",
        "execution_modes",
        (
            f"environment={mode_snapshot['environment']} "
            f"airtable_mode={mode_snapshot['airtable_mode']} "
            f"slack_mode={mode_snapshot['slack_mode']} "
            f"email_mode={mode_snapshot['email_mode']}"
        ),
    )
    airtable = AirtableStore(cfg)
    schema = airtable.validate_required_schema()
    run_store.log(
        run_id,
        "info",
        "schema_audit",
        f"schema validated tables={','.join(sorted(schema.keys()))}",
    )
    runtime_controls = airtable.load_runtime_controls()
    run_store.log(run_id, "info", "load_runtime_controls", f"runtime controls loaded count={len(runtime_controls)}")
    required_runtime_control_keys = ["weekly_summary_enabled", "ai_enabled"]
    missing_runtime_controls = [k for k in required_runtime_control_keys if k not in runtime_controls]
    if missing_runtime_controls:
        raise RuntimeError(
            "required runtime control(s) missing in Runtime Controls table: " + ", ".join(missing_runtime_controls)
        )
    weekly_summary_enabled = bool(runtime_controls["weekly_summary_enabled"])
    ai_enabled = bool(runtime_controls["ai_enabled"])
    if not ai_enabled:
        raise RuntimeError("runtime control 'ai_enabled' is false; AI execution is mandatory.")

    substack_prompt_sync = airtable.sync_current_substack_prompt()
    if substack_prompt_sync:
        run_store.log(
            run_id,
            "info",
            "substack_prompt_sync",
            (
                f"selected_name={substack_prompt_sync['selected_name']} "
                f"updated_prompts_text={substack_prompt_sync['updated_prompts_text']}"
            ),
        )
    prompts = airtable.load_prompts()
    run_store.log(run_id, "info", "load_prompts", f"prompts loaded count={len(prompts)}")
    required_prompt_keys = required_obj(cfg, "prompts").get("required_prompt_keys", [])
    for key in required_prompt_keys:
        if str(key) not in prompts:
            raise RuntimeError(f"required prompt key missing in Prompts table: {key}")
    categories = airtable.load_categories()
    run_store.log(run_id, "info", "load_categories", f"company categories loaded count={len(categories)}")
    article_format_config = airtable.load_article_format()
    run_store.log(
        run_id,
        "info",
        "load_article_format",
        f"article format loaded - active_field={article_format_config.get('active_field')} "
        f"format_name={article_format_config.get('active_format_name')}",
    )
    logic = build_runtime_logic(prompts, config_path, categories=categories)
    run_store.log(run_id, "info", "load_logic", "runtime logic loaded from active Airtable prompts")
    run_store.log(
        run_id,
        "info",
        "ai_config",
        (
            f"model={logic['ai_model_name']} "
            f"temperature={logic['ai_temperature']} "
            f"openai_config_path={resolve_openai_config_path(config_path)}"
        ),
    )
    if not weekly_summary_enabled:
        run_store.log(run_id, "info", "summary_weekly", "weekly summary skipped by runtime control")
        run_store.finish(run_id, "completed", RunMetrics())
        print("weekly_summary_file=")
        print("weekly_substack_draft_file=")
        return 0

    summary_cfg = required_obj(cfg, "summary")
    summary_now = _runtime_now(cfg)
    output_timestamp = _output_timestamp_label(summary_now)
    weekly_file = _timestamped_output_path(
        resolve_path(required_text(summary_cfg, "weekly_output_file"), config_path),
        output_timestamp,
    )
    weekly_draft_file = _timestamped_output_path(
        resolve_path(required_text(summary_cfg, "weekly_substack_draft_file"), config_path),
        output_timestamp,
    )
    events = airtable.load_events()
    events = airtable.load_events() + airtable.load_news()
    text = build_weekly_summary(events, summary_now)
    article_format_config = airtable.load_article_format()
    draft, audit_data = build_weekly_substack_draft(
        events,
        summary_now,
        logic=logic,
        run_store=run_store,
        run_id=run_id,
        article_format_config=article_format_config,
    )

    # Extract title from markdown for filename
    weekly_draft_file_base = resolve_path(required_text(summary_cfg, "weekly_substack_draft_file"), config_path)
    title_filename = _extract_title_for_filename(draft)
    if title_filename:
        # Use title-based filename for draft files
        weekly_draft_file = weekly_draft_file_base.parent / f"{title_filename}.md"
        weekly_draft_html_file = weekly_draft_file_base.parent / f"{title_filename}.html"
    else:
        # Fallback to timestamped if title extraction fails
        weekly_draft_html_file = weekly_draft_file.with_suffix(".html")

    weekly_file.parent.mkdir(parents=True, exist_ok=True)
    weekly_draft_file.parent.mkdir(parents=True, exist_ok=True)
    weekly_file.write_text(text, encoding="utf-8")
    weekly_draft_file.write_text(draft, encoding="utf-8")
    weekly_draft_html_file.write_text(_render_weekly_html(draft), encoding="utf-8")

    # Generate audit report
    audit_report_html = _generate_newsletter_audit_report(
        all_events=audit_data["selected_events"],
        selected_events=audit_data["selected_events"],
        start_date=audit_data["start_date"],
        end_date=audit_data["end_date"],
    )
    if title_filename:
        audit_report_file = weekly_draft_file_base.parent / f"{title_filename} - Audit Report.html"
    else:
        audit_report_file = weekly_draft_file.with_stem(f"{weekly_draft_file.stem} - Audit Report").with_suffix(".html")
    audit_report_file.write_text(audit_report_html, encoding="utf-8")

    run_store.log(run_id, "info", "summary_weekly", f"weekly summary written {weekly_file}")
    run_store.log(run_id, "info", "summary_weekly_draft", f"weekly Substack draft written {weekly_draft_file}")
    run_store.log(run_id, "info", "audit_report", f"audit report written {audit_report_file}")
    run_store.finish(run_id, "completed", RunMetrics())
    print(f"weekly_summary_file={weekly_file}")
    print(f"weekly_substack_draft_file={weekly_draft_file}")
    return 0


def list_substack_prompts(config_path: Path) -> int:
    cfg = load_config(config_path)
    prompts = AirtableStore(cfg).list_substack_prompt_library()
    print(json.dumps({"ok": True, "substack_prompts": prompts}, ensure_ascii=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consumer VC Automation V1 foundation runner.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent / "Global.json",
        help="Path to Global.json",
    )
    sub = parser.add_subparsers(dest="command")

    sp_run = sub.add_parser("run", help="Run daily ingestion/classification/dedupe/store/notify/summaries")
    sp_run.add_argument("--dry-run", action="store_true", help="Deprecated flag; live notifications always run")
    sp_run.add_argument("--mode", choices=["live", "replay", "review"], default="live", help="Execution mode")
    sp_run.add_argument("--snapshot-run-id", default="", help="Source run_id for replay mode raw snapshot")
    sp_run.add_argument("--max-items-per-source-override", type=int, default=None, help="Optional per-run source item cap override")
    sp_run.add_argument("--test-slack-only", action="store_true", help="Send event SlackContent without Airtable writes")

    sub.add_parser("weekly-summary", help="Build weekly summary from Airtable Events table only")
    sp_replay = sub.add_parser("replay-node", help="Replay a single node from a saved checkpoint")
    sp_replay.add_argument("--checkpoint-run-id", required=True, help="Source run_id that owns the checkpoint")
    sp_replay.add_argument("--node-id", required=True, help="Node id to replay")
    sp_replay.add_argument("--weekly-prompt-name", default="", help="Optional Substack prompt library name for ai_weekly_draft replay")
    sp_replay.add_argument("--content-start-date", default="", help="Optional replay content start date (YYYY-MM-DD)")
    sp_replay.add_argument("--content-end-date", default="", help="Optional replay content end date (YYYY-MM-DD)")
    sub.add_parser("list-substack-prompts", help="List active Substack prompt library options")
    parser.set_defaults(command="run", dry_run=False, mode="live", snapshot_run_id="")
    args = parser.parse_args()
    if args.command is None:
        args.command = "run"
        args.dry_run = False
    return args


def _post_fatal_command_error_slack(config_path: Path, command_name: str, exc: Exception) -> None:
    try:
        cfg = load_config(config_path)
    except Exception:
        return
    try:
        slack = SlackNotifier(cfg, config_path)
    except Exception:
        return
    try:
        slack.post(
            (
                f":x: Consumer VC fatal error\n"
                f"Command: {command_name}\n"
                f"Error: {str(exc)}"
            )
        )
    except Exception:
        return


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    try:
        if args.command == "run":
            return run_daily(
                config_path=config_path,
                dry_run=False,
                mode=str(getattr(args, "mode", "live") or "live"),
                snapshot_run_id=str(getattr(args, "snapshot_run_id", "") or ""),
                max_items_per_source_override=getattr(args, "max_items_per_source_override", None),
                test_slack_only=bool(getattr(args, "test_slack_only", False)),
            )
        if args.command == "weekly-summary":
            return run_weekly_summary_only(config_path=config_path)
        if args.command == "list-substack-prompts":
            return list_substack_prompts(config_path=config_path)
        if args.command == "replay-node":
            return replay_node_from_checkpoint(
                config_path=config_path,
                checkpoint_run_id=str(args.checkpoint_run_id),
                node_id=str(args.node_id),
                weekly_prompt_name=str(getattr(args, "weekly_prompt_name", "") or ""),
                content_start_date=str(getattr(args, "content_start_date", "") or ""),
                content_end_date=str(getattr(args, "content_end_date", "") or ""),
            )
        raise RuntimeError(f"unknown command: {args.command}")
    except Exception as exc:
        _post_fatal_command_error_slack(config_path, str(args.command), exc)
        raise


_enable_flow_tracing()


if __name__ == "__main__":
    raise SystemExit(main())
