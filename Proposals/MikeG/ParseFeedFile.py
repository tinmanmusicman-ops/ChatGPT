from __future__ import annotations

import argparse
from copy import deepcopy
import difflib
from datetime import datetime
from email.utils import parsedate_to_datetime
import html
import hashlib
import importlib.util
import inspect
import json
import re
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen

from lxml import etree
import requests

try:
    import feedparser
except Exception as exc:  # pragma: no cover - fail-fast import guard
    raise RuntimeError(
        "Missing required dependency: feedparser. "
        f"Python={sys.executable}. ImportError={exc!r}"
    ) from exc

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

try:
    from waybackpy import Url as WaybackPyUrl
except Exception:
    WaybackPyUrl = None

try:
    import wayback
except Exception:
    wayback = None


FLOW_LOG_DIR = Path(__file__).resolve().parent / "Logs"
FLOW_LOG_FILE = FLOW_LOG_DIR / "flow.log"
ARTICLE_CACHE_DIR = FLOW_LOG_DIR / "article_cache"
ARTICLE_COOLDOWN_FILE = FLOW_LOG_DIR / "article_fetch_cooldowns.json"
ARTICLE_DOMAIN_COOLDOWN_SECONDS = 3600
FLOW_LOG_DIR.mkdir(parents=True, exist_ok=True)
ARTICLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
URL_CACHE_DIR = FLOW_LOG_DIR / "url_cache"
URL_CACHE_FILE = URL_CACHE_DIR / "url.json"
URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_FLOW_LOG_LOCK = threading.Lock()
_URL_CACHE_LOCK = threading.Lock()
_FLOW_TRACE_STATE = threading.local()


def _flow_safe_text(value: Any) -> str:
    text = str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def _flow_write_line(line: str) -> None:
    if getattr(_FLOW_TRACE_STATE, "writing", False):
        return
    _FLOW_TRACE_STATE.writing = True
    try:
        FLOW_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _FLOW_LOG_LOCK:
            with FLOW_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        progress_hook = getattr(_FLOW_TRACE_STATE, "progress_hook", None)
        if callable(progress_hook) and str(line).startswith("PARSER RETURN"):
            count = int(getattr(_FLOW_TRACE_STATE, "progress_count", 0) or 0) + 1
            _FLOW_TRACE_STATE.progress_count = count
            stride = max(1, int(getattr(_FLOW_TRACE_STATE, "progress_stride", 25) or 25))
            if count % stride == 0:
                try:
                    progress_hook({"parser_returns": count})
                except Exception:
                    pass
    finally:
        _FLOW_TRACE_STATE.writing = False


def _flow_write_separator() -> None:
    with _FLOW_LOG_LOCK:
        with FLOW_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write("\n")


def _flow_format_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts: list[str] = []
    for idx, value in enumerate(args[:4]):
        parts.append(f"arg{idx}={_flow_safe_text(value)}")
    for key, value in list(kwargs.items())[:4]:
        parts.append(f"{key}={_flow_safe_text(value)}")
    if len(args) > 4 or len(kwargs) > 4:
        parts.append("...")
    return " | ".join(parts)


def traceable(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        started_at = time.time()
        depth = int(getattr(_FLOW_TRACE_STATE, "depth", 0))
        call_id = int(getattr(_FLOW_TRACE_STATE, "call_id", 0)) + 1
        _FLOW_TRACE_STATE.call_id = call_id
        arg_text = _flow_format_args(args, kwargs)
        header = f"PARSER ENTER | depth={depth} | call={call_id} | {func.__qualname__}"
        if arg_text:
            header += f" | {arg_text}"
        _flow_write_line(header)
        _FLOW_TRACE_STATE.depth = depth + 1
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _FLOW_TRACE_STATE.depth = depth
            elapsed_seconds = time.time() - started_at
            _flow_write_line(
                f"PARSER RAISE | depth={depth} | call={call_id} | {func.__qualname__} | "
                f"elapsed={elapsed_seconds:.3f}s | {exc.__class__.__name__}: {_flow_safe_text(exc)}"
            )
            _flow_write_separator()
            raise
        _FLOW_TRACE_STATE.depth = depth
        elapsed_seconds = time.time() - started_at
        _flow_write_line(
            f"PARSER RETURN | depth={depth} | call={call_id} | {func.__qualname__} | "
            f"elapsed={elapsed_seconds:.3f}s | result_type={type(result).__name__}"
        )
        _flow_write_separator()
        return result

    wrapper.__flow_traced__ = True
    return wrapper


def _enable_flow_tracing() -> None:
    skip_names = {
        "_safe_text",
        "_flow_safe_text",
        "_flow_write_line",
        "_flow_write_separator",
        "_flow_format_args",
        "traceable",
        "_enable_flow_tracing",
    }
    for name, obj in list(globals().items()):
        if name in skip_names:
            continue
        if inspect.isfunction(obj) and getattr(obj, "__module__", "") == __name__:
            if not getattr(obj, "__flow_traced__", False):
                globals()[name] = traceable(obj)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _replace_company_in_text(text: str, plain_name: str, hyperlink: str) -> str:
    if not plain_name or plain_name == hyperlink:
        return text
    # Only replace plain occurrences — skip when already inside a markdown link [name](url)
    # Trailing \b only works when the name ends with a word character (not e.g. "Inc." or "Corp.")
    end_boundary = r"\b(?!\]\()" if re.search(r"\w$", plain_name) else r"(?!\]\()"
    pattern = r"(?<!\[)\b" + re.escape(plain_name) + end_boundary
    return re.sub(pattern, hyperlink, text)


def _url_cache_read_nolock() -> dict[str, str]:
    try:
        raw = json.loads(URL_CACHE_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _load_url_cache() -> dict[str, str]:
    with _URL_CACHE_LOCK:
        return _url_cache_read_nolock()


def _save_url_cache(new_entries: dict[str, str]) -> None:
    with _URL_CACHE_LOCK:
        current = _url_cache_read_nolock()
        current.update(new_entries)
        URL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        URL_CACHE_FILE.write_text(
            json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _resolve_company_website(company_name: str, openai_settings: dict[str, Any]) -> str:
    if not company_name:
        return ""
    cache = _load_url_cache()
    normalized = company_name.casefold()
    for key, url in cache.items():
        if key.casefold() == normalized:
            return url
    try:
        payload = {
            "model": openai_settings["model"],
            "temperature": 0,
            "max_tokens": 64,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only the official website URL for the company the user names. "
                        "Output a bare URL starting with https:// and nothing else. "
                        "If unknown, output an empty string."
                    ),
                },
                {"role": "user", "content": company_name},
            ],
        }
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_settings['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=max(1, int(openai_settings["timeout_ms"]) // 1000),
        )
        if resp.status_code >= 300:
            return ""
        data = resp.json()
        url = _safe_text(
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        if not (url.startswith("http://") or url.startswith("https://")):
            return ""
        _save_url_cache({company_name: url})
        return url
    except Exception:
        return ""


def _format_company_hyperlink(company_name: str, url: str) -> str:
    if url:
        return f"[{company_name}]({url})"
    return company_name


def _local_name(tag: Any) -> str:
    text = _safe_text(tag)
    if not text:
        return ""
    if "}" in text:
        return text.rsplit("}", 1)[-1]
    if ":" in text:
        return text.rsplit(":", 1)[-1]
    return text


def _entry_value(entry: Any, key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key)
    return getattr(entry, key, None)


def _xml_item_nodes(root: Any) -> list[etree._Element]:
    if not isinstance(root, etree._Element):
        return []
    rss_items = root.xpath(".//*[local-name()='item']")
    if rss_items:
        return rss_items
    return root.xpath(".//*[local-name()='entry']")


def _feed_header_published_fallback(root: Any, parsed: Any) -> str:
    feed = _entry_value(parsed, "feed")
    for key in ("published", "pubDate", "updated", "lastbuilddate", "lastBuildDate"):
        value = _safe_text(_entry_value(feed, key))
        if value:
            return value
    header_paths = (
        "./*[local-name()='channel']/*[local-name()='lastBuildDate']",
        "./*[local-name()='channel']/*[local-name()='pubDate']",
        "./*[local-name()='updated']",
        "./*[local-name()='published']",
    )
    if not isinstance(root, etree._Element):
        return ""
    for path in header_paths:
        nodes = root.xpath(path)
        if not nodes:
            continue
        value = _safe_text("".join(nodes[0].itertext()))
        if value:
            return value
    return ""


def _xml_item_summary(node: etree._Element) -> dict[str, Any]:
    children = [child for child in node if isinstance(child.tag, str)]
    child_tags = [_local_name(child.tag) for child in children]
    fields: dict[str, list[str]] = {}
    for child in children:
        name = _local_name(child.tag)
        value = _safe_text("".join(child.itertext()))
        if not name:
            continue
        fields.setdefault(name, []).append(value[:400])
    return {
        "tag": _local_name(node.tag),
        "child_tags": child_tags,
        "fields": fields,
    }


def _xml_item_has_cdata(node: Any) -> bool:
    if not isinstance(node, etree._Element):
        return False
    try:
        raw_xml = etree.tostring(node, encoding="unicode")
    except Exception:
        return False
    return "<![CDATA[" in _safe_text(raw_xml)


def _entry_content_value(entry: Any) -> str:
    content = _entry_value(entry, "content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                value = _safe_text(block.get("value", ""))
            else:
                value = _safe_text(getattr(block, "value", ""))
            if value:
                return value
    return ""


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


def _parse_html_feed_entries(html_text: str, source_url: str) -> list[dict[str, Any]]:
    anchor_re = re.compile(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    source_url = _safe_text(source_url)
    for href, inner in anchor_re.findall(str(html_text or "")):
        raw_href = html.unescape(_safe_text(href))
        if not raw_href:
            continue
        lowered = raw_href.lower()
        if lowered.startswith("#") or lowered.startswith("javascript:") or lowered.startswith("mailto:") or lowered.startswith("tel:"):
            continue
        resolved_url = _safe_text(urljoin(source_url, raw_href))
        if not (resolved_url.startswith("http://") or resolved_url.startswith("https://")):
            continue
        if source_url and not _same_site_url(source_url, resolved_url):
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
                "description": "",
                "link": resolved_url,
                "published": "",
            }
        )
        if len(out) >= 500:
            break
    return out


def _build_item_xml(rows: list[dict[str, Any]], root_name: str) -> str:
    root = etree.Element(root_name)
    for row in rows:
        if not isinstance(row, dict):
            continue
        xml_item = row.get("xml_item")
        payload = row.get("payload", {})
        if isinstance(xml_item, etree._Element):
            root.append(deepcopy(xml_item))
            continue
        item = etree.SubElement(root, "item")
        if not isinstance(payload, dict):
            continue
        for key in ("title", "link", "description", "published"):
            value = _safe_text(payload.get(key, ""))
            if not value:
                continue
            tag = "pubDate" if key == "published" else key
            node = etree.SubElement(item, tag)
            node.text = value
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def _build_feedparser_xml(filtered_rows: list[dict[str, Any]]) -> str:
    root = etree.Element("feedparser_items")
    for row in filtered_rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        item = etree.SubElement(root, "item")
        title = _safe_text(payload.get("title", ""))
        link = _safe_text(payload.get("link", ""))
        description = _safe_text(payload.get("description", ""))
        published = _safe_text(payload.get("published", ""))
        ai_content = _safe_text(payload.get("AIContent", ""))
        for tag, value in (
            ("title", title),
            ("link", link),
            ("description", description),
            ("pubDate", published),
            ("AIContent", ai_content),
        ):
            if not value:
                continue
            node = etree.SubElement(item, tag)
            node.text = value
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def _build_newspaper3k_xml(filtered_rows: list[dict[str, Any]]) -> str:
    root = etree.Element("newspaper3k_items")
    for row in filtered_rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        item = etree.SubElement(root, "item")
        for tag, key in (
            ("title", "title"),
            ("link", "link"),
            ("description", "description"),
            ("pubDate", "published"),
            ("AIContent", "AIContent"),
            ("article", "article"),
        ):
            value = _safe_text(payload.get(key, ""))
            if not value:
                continue
            node = etree.SubElement(item, tag)
            node.text = value
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def default_openai_config_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "openai_shared_global.json"


def default_global_config_path() -> Path:
    return Path(__file__).resolve().parent / "Global.json"


def _load_consumer_module() -> Any:
    module_path = Path(__file__).resolve().parent / "Consumer_vc.py"
    if not module_path.exists() or not module_path.is_file():
        raise RuntimeError(f"Consumer_vc.py not found: {module_path}")
    spec = importlib.util.spec_from_file_location("consumer_vc_parser_bridge", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Consumer_vc.py: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_airtable_event_field_placeholders(config_path: Path) -> dict[str, Any]:
    consumer_mod = _load_consumer_module()
    cfg = consumer_mod.load_config(config_path)
    airtable = consumer_mod.AirtableStore(cfg)
    table_meta = airtable._table_meta.get(airtable.table_events)
    if not isinstance(table_meta, dict):
        raise RuntimeError(f"Events table metadata missing: {airtable.table_events}")
    fields = table_meta.get("fields", [])
    if not isinstance(fields, list) or not fields:
        raise RuntimeError(f"Events table fields missing: {airtable.table_events}")
    placeholders: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = _safe_text(field.get("name", ""))
        if not name:
            continue
        placeholders[name] = ""
    if not placeholders:
        raise RuntimeError(f"Events table has no usable field names: {airtable.table_events}")
    return placeholders


def load_openai_settings(config_path: Path) -> dict[str, Any]:
    if not config_path.exists() or not config_path.is_file():
        raise RuntimeError(f"OpenAI config not found: {config_path}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"OpenAI config must be an object: {config_path}")
    api_key = _safe_text(raw.get("openai_api_key", ""))
    if not api_key:
        raise RuntimeError(f"required key missing in {config_path}: openai_api_key")
    model = _safe_text(raw.get("openai_model", "")) or "gpt-4o-mini"
    try:
        temperature = float(raw.get("openai_temperature", 0.1))
    except Exception as exc:
        raise RuntimeError(f"invalid openai_temperature in {config_path}") from exc
    try:
        timeout_ms = int(raw.get("openai_timeout_ms", 45000))
    except Exception as exc:
        raise RuntimeError(f"invalid openai_timeout_ms in {config_path}") from exc
    return {
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "timeout_ms": timeout_ms,
        "config_path": str(config_path),
    }


def _extract_openai_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("OpenAI choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenAI response missing message")
    content = _safe_text(message.get("content", ""))
    if not content:
        raise RuntimeError("OpenAI response content is empty")
    return content


def _normalize_published_date(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        pass
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except Exception:
        return ""


def _format_markdown_link(label: str, url: str) -> str:
    safe_label = _safe_text(label)
    safe_url = _safe_text(url)
    if not safe_url:
        return ""
    if not safe_label:
        return safe_url
    escaped_label = safe_label.replace("[", "\\[").replace("]", "\\]")
    return f"[{escaped_label}]({safe_url})"


def _format_slack_link(label: str, url: str) -> str:
    safe_label = _safe_text(label).replace("|", "/").replace("<", "").replace(">", "")
    safe_url = _safe_text(url)
    if not safe_url:
        return ""
    if not safe_label:
        return safe_url
    return f"<{safe_url}|{safe_label}>"


def _convert_markdown_links_to_slack(text: str) -> str:
    return re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f"<{m.group(2)}|{m.group(1)}>",
        text,
    )


def _contains_malformed_slack_tokens(text: str) -> bool:
    value = _safe_text(text)
    lower = value.lower()
    return "|[" in value or "](http://" in lower or "](https://" in lower


def _sanitize_slack_markup(text: str) -> str:
    value = _safe_text(text)
    if not value:
        return ""
    # Corrupted hybrid: <url|[Label>](url2) -> <url|Label>
    value = re.sub(r"<([^|>]+)\|\[([^>\]]+)>\]\([^)]+\)", r"<\1|\2>", value)
    value = _convert_markdown_links_to_slack(value)
    value = value.replace("|[", "|")
    value = re.sub(r"\]\((https?://)", r" (\1", value, flags=re.IGNORECASE)
    return value


def _slack_plaintext_fallback(text: str) -> str:
    value = _safe_text(text)
    if not value:
        return ""
    value = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2 (\1)", value)
    value = re.sub(r"<(https?://[^>]+)>", r"\1", value, flags=re.IGNORECASE)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", value, flags=re.IGNORECASE)
    value = value.replace("|[", "|")
    value = re.sub(r"\]\((https?://)", r" (\1", value, flags=re.IGNORECASE)
    return value


def _prepare_slack_content_for_payload(text: str) -> str:
    sanitized = _sanitize_slack_markup(text)
    if _contains_malformed_slack_tokens(sanitized):
        return _slack_plaintext_fallback(sanitized)
    return sanitized


def _is_not_disclosed_amount(value: Any) -> bool:
    normalized = _normalized_field_key(value)
    return normalized in {
        "notdisclosed",
        "undisclosed",
        "termsnotdisclosed",
        "financialtermsnotdisclosed",
        "amountnotdisclosed",
    }


def _slack_type_code(event_type: Any) -> str:
    normalized = _safe_text(event_type).lower()
    if normalized == "funding":
        return "FND"
    if normalized == "acquisition":
        return "ACQ"
    if normalized == "merger":
        return "MRG"
    return "NWS"


def _article_source_code(value: Any) -> str:
    normalized = _safe_text(value).upper()
    if normalized in {"A", "B", "F", "W"}:
        return normalized
    raise RuntimeError(f"unsupported article source code: {value!r}")


def _normalized_field_key(value: Any) -> str:
    text = _safe_text(value).lower()
    return "".join(ch for ch in text if ch.isalnum())


def _populate_airtable_fields(
    placeholders: dict[str, Any],
    *,
    company: str,
    event_type: str,
    title: str,
    description: str,
    link: str,
    source_name: str,
    published_date: str,
    ai_fields: dict[str, Any],
) -> dict[str, Any]:
    funding = ai_fields.get("funding", {})
    mna = ai_fields.get("mna", {})
    normalized_event_type = _safe_text(event_type).lower()
    funding_amount = _safe_text(funding.get("amount", ""))
    mna_amount = _safe_text(mna.get("amount", ""))
    amount_value = mna_amount if normalized_event_type in {"acquisition", "merger"} and mna_amount else funding_amount
    investors = funding.get("investors", [])
    investors_text = ", ".join(_safe_text(item) for item in investors if _safe_text(item))
    summary_text = _safe_text(ai_fields.get("summary", ""))
    if normalized_event_type == "funding":
        category_value = "Funding"
    elif normalized_event_type in {"acquisition", "merger"}:
        category_value = "M&A"
    else:
        category_value = "News"
    candidate_values: dict[str, Any] = {
        "eventid": "",
        "company": company,
        "category": category_value,
        "eventtype": event_type,
        "amount": amount_value,
        "round": _safe_text(funding.get("round", "")),
        "investors": investors_text,
        "eventdate": published_date,
        "date": published_date,
        "sourcelink": link,
        "sourceurl": link,
        "sourcename": source_name,
        "rawtitle": title,
        "rawsummary": description,
        "summary": summary_text,
        "fingerprint": "",
        "basefingerprint": "",
        "updatedat": "",
        "createdat": "",
        "manualoverride": "",
        "incorrectflag": "",
        "acquirer": _safe_text(mna.get("acquirer", "")),
        "target": _safe_text(mna.get("target", "")),
        "companydescription": _safe_text(ai_fields.get("company_description", "")),
        "companycategory": _safe_text(ai_fields.get("company_category", "")),
        "valuation": _safe_text(funding.get("valuation", "")),
        "targetpriorraise": _safe_text(mna.get("target_prior_raise", "")),
        "targetpriorvaluation": _safe_text(mna.get("target_prior_valuation", "")),
    }
    populated: dict[str, Any] = {}
    for field_name in placeholders:
        normalized_name = _normalized_field_key(field_name)
        populated[field_name] = candidate_values.get(normalized_name, "")
    return populated


def _terminal_period(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return text + "."


def _truncate_slack_detail(value: Any, limit: int = 150) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if len(text) <= limit:
        return text
    clipped = text[:limit].rstrip()
    # If the cut falls inside an incomplete markdown link [label](url..., back up to before [
    last_open = clipped.rfind("[")
    if last_open >= 0:
        suffix = clipped[last_open:]
        if not re.search(r"^\[[^\]]+\]\([^)]+\)", suffix):
            clipped = clipped[:last_open].rstrip()
    return clipped + "..."


def _truncate_article_text(value: Any, limit: int = 12000) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


ARTICLE_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Referer": "https://www.google.com/",
}


def _extract_first_paragraphs_over_min_chars(
    value: Any,
    *,
    min_chars: int = 200,
    max_paragraphs: int = 4,
) -> str:
    text = _safe_text(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    blocks = [segment.strip() for segment in re.split(r"\n\s*\n+", text) if segment.strip()]
    if not blocks:
        blocks = [line.strip() for line in text.split("\n") if line.strip()]
    if not blocks:
        return ""
    threshold = max(1, int(min_chars))
    limit = max(1, int(max_paragraphs))
    selected: list[str] = []
    for block in blocks:
        if len(block) >= threshold:
            selected.append(block)
            if len(selected) >= limit:
                break
    return "\n\n".join(selected)


def _description_article_candidate(description: Any) -> str:
    cleaned = _strip_html_for_matching(description)
    if not cleaned:
        return ""
    candidate = _extract_first_paragraphs_over_min_chars(cleaned, min_chars=200, max_paragraphs=4)
    if not candidate:
        return ""
    return _truncate_article_text(candidate)


def _article_failure_message(reason: Any) -> str:
    raw = _safe_text(reason)
    if not raw:
        raw = "unknown error"
    normalized = re.sub(r"\s+", " ", raw).strip()
    if len(normalized) > 240:
        normalized = normalized[:240].rstrip()
    return f"Failed to get data: {normalized}"


def _is_article_failure(value: Any) -> bool:
    return _safe_text(value).startswith("Failed to get data:")


def _is_supported_article_url(url: Any) -> bool:
    text = _safe_text(url)
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extract_article_text_from_html(url: str, html: str) -> str:
    raw_html = _safe_text(html)
    if not raw_html:
        return ""
    try:
        root = etree.HTML(raw_html)
    except Exception:
        root = None
    if root is None:
        return ""
    for node in root.xpath(".//script|.//style|.//noscript|.//svg|.//iframe|.//template"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    paragraph_nodes = root.xpath(
        ".//*[local-name()='article']//*[local-name()='p'] | "
        ".//*[local-name()='main']//*[local-name()='p'] | "
        ".//*[local-name()='body']//*[local-name()='p']"
    )
    paragraphs: list[str] = []
    seen: set[str] = set()
    for node in paragraph_nodes:
        text = _safe_text(" ".join(part.strip() for part in node.itertext() if _safe_text(part)))
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        paragraphs.append(normalized)
    text = _extract_first_paragraphs_over_min_chars(
        "\n\n".join(paragraphs),
        min_chars=200,
        max_paragraphs=4,
    )
    return _truncate_article_text(text)


def _headers_for_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    headers = dict(ARTICLE_HTTP_HEADERS)
    if parsed.scheme and parsed.netloc:
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def _looks_like_block_page(html: Any) -> bool:
    body = _safe_text(html).lower()
    if not body:
        return True
    article_signals = [
        "application/ld+json",
        "\"articlebody\"",
        "\"headline\"",
        "<main",
        "wp-content",
    ]
    strong_block_markers = [
        "just a moment",
        "cf-challenge",
        "challenge-platform",
        "attention required",
        "access denied",
        "support us by disabling your adblocker",
        "continue without disabling",
    ]
    if any(marker in body for marker in strong_block_markers):
        return True
    if any(signal in body for signal in article_signals):
        return False
    weak_block_markers = [
        "cloudflare",
        "captcha",
    ]
    return any(marker in body for marker in weak_block_markers)


def _download_article_html_urllib(url: str, *, timeout_seconds: int = 30) -> str:
    request = Request(url, headers=_headers_for_url(url))
    with urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
        html_bytes = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        html = html_bytes.decode(charset, errors="replace")
    html = _safe_text(html)
    if not html:
        raise RuntimeError("urllib returned empty HTML")
    if _looks_like_block_page(html):
        raise RuntimeError("urllib returned challenge/block page")
    return html


def _article_cache_key(url: Any) -> str:
    text = _safe_text(url)
    if not text:
        raise RuntimeError("article cache key requires URL")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _article_cache_path(url: Any) -> Path:
    return ARTICLE_CACHE_DIR / f"{_article_cache_key(url)}.json"


def _read_article_cache(url: Any) -> str:
    cache_path = _article_cache_path(url)
    if not cache_path.exists():
        return ""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    cached_url = _safe_text(payload.get("url", ""))
    cached_text = _safe_text(payload.get("text", ""))
    if not cached_url or not cached_text:
        return ""
    if cached_url != _safe_text(url):
        return ""
    if _is_article_failure(cached_text):
        return ""
    return cached_text


def _write_article_cache(url: Any, text: Any) -> None:
    article_url = _safe_text(url)
    article_text = _safe_text(text)
    if not article_url:
        raise RuntimeError("article cache write requires URL")
    if not article_text:
        raise RuntimeError("article cache write requires text")
    if _is_article_failure(article_text):
        raise RuntimeError("article cache write requires successful text")
    payload = {
        "url": article_url,
        "text": article_text,
        "cached_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    _article_cache_path(article_url).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_article_cooldowns() -> dict[str, float]:
    if not ARTICLE_COOLDOWN_FILE.exists():
        return {}
    try:
        payload = json.loads(ARTICLE_COOLDOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    cooldowns: dict[str, float] = {}
    for key, value in payload.items():
        domain = _safe_text(key).lower()
        if not domain:
            continue
        try:
            cooldowns[domain] = float(value)
        except Exception:
            continue
    return cooldowns


def _save_article_cooldowns(cooldowns: dict[str, float]) -> None:
    cleaned: dict[str, float] = {}
    now_ts = time.time()
    for key, value in cooldowns.items():
        domain = _safe_text(key).lower()
        if not domain:
            continue
        try:
            expires_at = float(value)
        except Exception:
            continue
        if expires_at > now_ts:
            cleaned[domain] = expires_at
    ARTICLE_COOLDOWN_FILE.write_text(
        json.dumps(cleaned, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _article_url_domain(url: Any) -> str:
    text = _safe_text(url)
    if not text:
        return ""
    try:
        return _safe_text(urlparse(text).netloc).lower()
    except Exception:
        return ""


def _set_article_domain_cooldown(url: Any, cooldowns: dict[str, float]) -> None:
    domain = _article_url_domain(url)
    if not domain:
        return
    cooldowns[domain] = time.time() + ARTICLE_DOMAIN_COOLDOWN_SECONDS
    _save_article_cooldowns(cooldowns)


def _is_article_domain_in_cooldown(url: Any, cooldowns: dict[str, float]) -> bool:
    domain = _article_url_domain(url)
    if not domain:
        return False
    expires_at = cooldowns.get(domain)
    if expires_at is None:
        return False
    if float(expires_at) <= time.time():
        cooldowns.pop(domain, None)
        _save_article_cooldowns(cooldowns)
        return False
    return True


def _download_article_html_browser(
    url: str,
    *,
    goto_timeout_ms: int = 30000,
    network_idle_timeout_ms: int = 7000,
    click_wait_timeout_ms: int = 1200,
) -> str:
    if sync_playwright is None:
        raise RuntimeError("Playwright not available")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=ARTICLE_HTTP_HEADERS["User-Agent"],
            locale="en-US",
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_extra_http_headers(_headers_for_url(url))
        page.goto(url, wait_until="domcontentloaded", timeout=max(1, int(goto_timeout_ms)))
        try:
            page.wait_for_load_state("networkidle", timeout=max(1, int(network_idle_timeout_ms)))
        except Exception:
            pass
        continue_locator = page.get_by_text("Continue without disabling", exact=False)
        try:
            if continue_locator.count() > 0:
                continue_locator.first.click(timeout=3000)
                try:
                    page.wait_for_load_state("networkidle", timeout=max(1, int(network_idle_timeout_ms)))
                except Exception:
                    pass
                page.wait_for_timeout(max(1, int(click_wait_timeout_ms)))
        except Exception:
            pass
        html = _safe_text(page.content())
        context.close()
        browser.close()
    if not html:
        raise RuntimeError("Playwright returned empty HTML")
    return html


def _download_article_html_selenium(url: str, *, timeout_seconds: int = 30) -> str:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
    except Exception as exc:
        raise RuntimeError(f"Selenium not available: {exc}") from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={ARTICLE_HTTP_HEADERS['User-Agent']}")
    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(max(1, int(timeout_seconds)))
        driver.get(url)
        try:
            candidates = driver.find_elements(By.XPATH, "//*[contains(., 'Continue without disabling')]")
            if candidates:
                candidates[0].click()
        except Exception:
            pass
        html = _safe_text(driver.page_source)
    finally:
        driver.quit()
    if not html:
        raise RuntimeError("Selenium returned empty HTML")
    return html


def _fetch_live_article_text_parallel(
    url: str,
    *,
    fast_fail: bool = False,
) -> tuple[str, str]:
    timeout_seconds = 6 if fast_fail else 30
    methods: list[tuple[str, Any]] = [
        (
            "playwright",
            lambda: _download_article_html_browser(
                url,
                goto_timeout_ms=max(1000, timeout_seconds * 1000),
            ),
        ),
    ]
    errors: list[str] = []
    for method_name, fn in methods:
        _flow_write_line(f"ARTICLE FETCH TRY | method={method_name} | fast_fail={fast_fail} | url={url}")
        try:
            html = fn()
            text = _extract_article_text_from_html(url, html)
            if not text:
                message = f"{method_name} returned no paragraph found with at least 200 characters"
                errors.append(message)
                _flow_write_line(f"ARTICLE FETCH FAIL | method={method_name} | reason={message} | url={url}")
                continue
            _flow_write_line(
                f"ARTICLE FETCH SUCCESS | method={method_name} | text_len={len(text)} | url={url}"
            )
            return text, method_name
        except Exception as exc:
            message = f"{method_name} {exc.__class__.__name__}: {exc}"
            errors.append(message)
            _flow_write_line(f"ARTICLE FETCH FAIL | method={method_name} | reason={_flow_safe_text(message)} | url={url}")
    if errors:
        raise RuntimeError(" | ".join(errors))
    raise RuntimeError("live fetch returned no usable content")


def _download_article_html(
    url: str,
    *,
    fast_fail: bool = False,
) -> str:
    text, _ = _fetch_live_article_text_parallel(url, fast_fail=fast_fail)
    return text


def _fetch_wayback_html_via_waybackpy(url: str) -> str:
    if WaybackPyUrl is None:
        raise RuntimeError("waybackpy not available")
    wb = WaybackPyUrl(url, ARTICLE_HTTP_HEADERS["User-Agent"])
    snapshot = wb.newest()
    archive_url = _safe_text(getattr(snapshot, "archive_url", ""))
    if not archive_url:
        raise RuntimeError("waybackpy returned no archive URL")
    response = requests.get(
        archive_url,
        headers={"User-Agent": ARTICLE_HTTP_HEADERS["User-Agent"]},
        timeout=20,
        allow_redirects=True,
    )
    response.raise_for_status()
    html = _safe_text(response.text)
    if not html:
        raise RuntimeError("waybackpy returned empty HTML")
    return html


def _fetch_wayback_html_via_wayback(url: str) -> str:
    if wayback is None:
        raise RuntimeError("wayback not available")
    client = wayback.WaybackClient()
    try:
        first_record = None
        for record in client.search(url):
            first_record = record
            break
        if first_record is None:
            raise RuntimeError("wayback search returned no snapshots")
        archive_url = (
            _safe_text(getattr(first_record, "memento_url", ""))
            or _safe_text(getattr(first_record, "raw_url", ""))
            or _safe_text(getattr(first_record, "view_url", ""))
        )
        if not archive_url:
            resolved = client.get_memento(url, timestamp=getattr(first_record, "timestamp", None))
            archive_url = (
                _safe_text(getattr(resolved, "memento_url", ""))
                or _safe_text(getattr(resolved, "raw_url", ""))
                or _safe_text(getattr(resolved, "view_url", ""))
            )
        if not archive_url:
            raise RuntimeError("wayback resolved no archive URL")
        response = requests.get(
            archive_url,
            headers={"User-Agent": ARTICLE_HTTP_HEADERS["User-Agent"]},
            timeout=20,
            allow_redirects=True,
        )
        response.raise_for_status()
        html = _safe_text(response.text)
        if not html:
            raise RuntimeError("wayback returned empty HTML")
        return html
    finally:
        client.close()


def _fetch_article_text_from_wayback(url: str) -> str:
    errors: list[str] = []
    for label, fn in (
        ("waybackpy", _fetch_wayback_html_via_waybackpy),
        ("wayback", _fetch_wayback_html_via_wayback),
    ):
        try:
            html = fn(url)
            text = _extract_article_text_from_html(url, html)
            if text:
                return text
            errors.append(f"{label} returned no paragraph found with at least 200 characters")
        except Exception as exc:
            errors.append(f"{label} {exc.__class__.__name__}: {exc}")
    if errors:
        raise RuntimeError(" | ".join(errors))
    raise RuntimeError("wayback returned no usable content")


def _fetch_article_text(
    url: Any,
    *,
    use_wayback_only: bool = False,
    fast_fail_live: bool = False,
) -> tuple[str, str, str]:
    article_url = _safe_text(url)
    if not article_url:
        return _article_failure_message("missing article URL"), "failure", ""
    if not _is_supported_article_url(article_url):
        return _article_failure_message("unsupported or invalid article URL"), "failure", ""
    try:
        text, live_method = _fetch_live_article_text_parallel(article_url, fast_fail=fast_fail_live)
    except Exception as exc:
        return _article_failure_message(f"{exc.__class__.__name__}: {exc}"), "failure", ""
    if not text:
        return _article_failure_message("no paragraph found with at least 200 characters"), "failure", ""
    return text, "live", live_method


def _fetch_article_text_with_cache(
    url: Any,
    *,
    cooldowns: dict[str, float],
    use_wayback_only: bool = False,
    fast_fail_live: bool = False,
) -> tuple[str, str, str, str]:
    article_url = _safe_text(url)
    if not article_url:
        return _article_failure_message("missing article URL"), "missing_url", "failure", ""
    cached_text = _read_article_cache(article_url)
    if cached_text:
        return cached_text, "disk_cache", "live", "disk_cache"
    fetched_text, fetch_source, fetch_method = _fetch_article_text(
        article_url,
        use_wayback_only=use_wayback_only,
        fast_fail_live=fast_fail_live,
    )
    if _is_article_failure(fetched_text):
        return fetched_text, "fetch_failed", "failure", fetch_method
    _write_article_cache(article_url, fetched_text)
    return fetched_text, "fetched", fetch_source, fetch_method


def _strip_html_for_matching(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    no_entities = re.sub(r"&(?:nbsp|amp|quot|apos|lt|gt|#160);", " ", no_tags, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", no_entities).strip()


def _extract_funding_rounds_detail(ai_summary: Any, description: Any) -> str:
    round_count_pattern = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
    for raw_text in (_safe_text(ai_summary), _strip_html_for_matching(description)):
        lowered = _safe_text(raw_text).lower()
        if not lowered:
            continue
        match = re.search(rf"\bacross\s+({round_count_pattern})\s+rounds?\b", lowered)
        if match:
            return f"across {match.group(1)} rounds"
        match = re.search(rf"\bin\s+({round_count_pattern})\s+rounds?\b", lowered)
        if match:
            return f"across {match.group(1)} rounds"
        match = re.search(rf"\bover\s+({round_count_pattern})\s+rounds?\b", lowered)
        if match:
            return f"across {match.group(1)} rounds"
    return ""


UNDISCLOSED_AMOUNT_PATTERNS = [
    r"\b(?:terms?|financial terms?)\s+(?:were\s+)?not disclosed\b",
    r"\bamount\s+(?:was\s+)?not disclosed\b",
    r"\bundisclosed(?:\s+amount)?\b",
    r"\bno financial terms(?:\s+were)? disclosed\b",
]


def _mentions_undisclosed_amount(*texts: Any) -> bool:
    for raw_text in texts:
        normalized = _strip_html_for_matching(raw_text).lower()
        if not normalized:
            continue
        for pattern in UNDISCLOSED_AMOUNT_PATTERNS:
            if re.search(pattern, normalized):
                return True
    return False


def _normalize_mna_amount(
    *,
    event_type: Any,
    current_amount: Any,
    title: Any,
    description: Any,
    article: Any,
    ai_summary: Any,
) -> str:
    normalized_event_type = _safe_text(event_type).lower()
    if normalized_event_type not in {"acquisition", "merger"}:
        return _safe_text(current_amount)
    amount_text = _safe_text(current_amount)
    if amount_text:
        if _is_not_disclosed_amount(amount_text):
            return "Not disclosed"
        return amount_text
    if _mentions_undisclosed_amount(title, description, article, ai_summary):
        return "Not disclosed"
    return ""


def _clean_entity_phrase(value: Any) -> str:
    text = _safe_text(value).strip(" \t\r\n,.;:()[]{}<>\"'")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    tokens = [part for part in text.split(" ") if part]
    noise_leads = {"how", "why", "what", "when", "where", "filings", "analysis", "report"}
    while len(tokens) > 1 and tokens[0].lower() in noise_leads:
        tokens = tokens[1:]
    text = " ".join(tokens).strip()
    return text


NON_COMPANY_TARGET_KEYS = {
    "spain",
    "france",
    "germany",
    "italy",
    "europe",
    "asia",
    "china",
    "india",
    "us",
    "usa",
    "unitedstates",
    "uk",
    "unitedkingdom",
    "canada",
    "mexico",
    "japan",
    "korea",
    "australia",
    "africa",
    "northamerica",
    "southamerica",
    "latinamerica",
    "middleeast",
    "easternwashington",
    "washington",
    "seattle",
    "newyork",
    "california",
}


def _is_valid_investment_target_company(target: Any) -> bool:
    target_text = _clean_entity_phrase(target)
    if not target_text:
        return False
    target_key = _normalized_field_key(target_text)
    if not target_key:
        return False
    if target_key in NON_COMPANY_TARGET_KEYS:
        return False
    return True


def _extract_investment_subject_target(title: Any, description: Any, ai_summary: Any) -> tuple[str, str]:
    candidate_texts = [
        _safe_text(title),
        _strip_html_for_matching(description),
        _safe_text(ai_summary),
    ]
    patterns = [
        r"\b(?P<investor>[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,4})\s+"
        r"(?:invests?|invested|to invest)\b[^.]{0,160}?\b(?:in|into)\s+"
        r"(?P<target>[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,5})\b",
        r"\b(?P<investor>[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,4})['’]s\s+"
        r"(?:\$?\d[\w$.,]*(?:\s+(?i:thousand|million|billion|trillion|k|m|mm|bn|b))?\s+)?"
        r"(?:investment|deal)\s+(?:in|with)\s+"
        r"(?P<target>[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,5})\b",
        r"\b(?P<investor>[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,4})['’]s\s+"
        r"(?:\$?\d[\w$.,]*(?:\s+(?i:thousand|million|billion|trillion|k|m|mm|bn|b))?\s+)?"
        r"(?P<target>[A-Z][A-Za-z0-9&'’.\-]*(?:\s+[A-Z][A-Za-z0-9&'’.\-]*){0,5})\s+"
        r"(?:investment|deal)\b",
    ]
    for text in candidate_texts:
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            investor = _clean_entity_phrase(match.group("investor"))
            target = _clean_entity_phrase(match.group("target"))
            if investor and target and _is_valid_investment_target_company(target):
                return investor, target
    return "", ""


def _resolve_funding_company_from_investment_phrase(
    *,
    company: Any,
    title: Any,
    description: Any,
    ai_summary: Any,
    event_type: Any,
) -> tuple[str, str]:
    if _safe_text(event_type).lower() != "funding":
        return _safe_text(company), ""
    investor, target = _extract_investment_subject_target(title, description, ai_summary)
    company_text = _safe_text(company)
    if not investor or not target or not company_text:
        return company_text, ""
    if _normalized_field_key(company_text) != _normalized_field_key(investor):
        return company_text, ""
    return target, investor


def _is_redundant_slack_detail(primary: Any, detail: Any) -> bool:
    primary_text = _safe_text(primary).rstrip(".!?")
    detail_text = _safe_text(detail).rstrip(".!?")
    if not primary_text or not detail_text:
        return False
    if detail_text.lower() == primary_text.lower():
        return True

    stop_tokens = {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "for",
        "of",
        "by",
        "to",
        "and",
        "with",
        "new",
        "round",
        "funding",
        "led",
    }

    def token_set(value: str) -> set[str]:
        tokens = re.findall(r"[A-Za-z0-9$€£.-]+", value.lower())
        return {token for token in tokens if token and token not in stop_tokens}

    primary_tokens = token_set(primary_text)
    detail_tokens = token_set(detail_text)
    if not primary_tokens or not detail_tokens:
        return False
    if detail_tokens.issubset(primary_tokens):
        return True
    intersection = primary_tokens & detail_tokens
    detail_overlap_ratio = len(intersection) / max(len(detail_tokens), 1)
    primary_overlap_ratio = len(intersection) / max(len(primary_tokens), 1)
    if detail_overlap_ratio >= 0.8 or primary_overlap_ratio >= 0.65:
        return True

    primary_norm = re.sub(r"[^a-z0-9 ]+", " ", primary_text.lower())
    detail_norm = re.sub(r"[^a-z0-9 ]+", " ", detail_text.lower())
    primary_norm = " ".join(primary_norm.split())
    detail_norm = " ".join(detail_norm.split())
    if not primary_norm or not detail_norm:
        return False
    if detail_norm in primary_norm or primary_norm in detail_norm:
        return True
    return difflib.SequenceMatcher(None, primary_norm, detail_norm).ratio() >= 0.72


def _has_material_novel_detail(primary: Any, detail: Any) -> bool:
    primary_text = _safe_text(primary)
    detail_text = _safe_text(detail)
    if not primary_text or not detail_text:
        return False

    stop_tokens = {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "for",
        "of",
        "by",
        "to",
        "and",
        "with",
        "new",
        "round",
        "funding",
        "led",
        "from",
    }

    def token_set(value: str) -> set[str]:
        tokens = re.findall(r"[A-Za-z0-9$€£.-]+", value.lower())
        return {token for token in tokens if token and token not in stop_tokens}

    primary_tokens = token_set(primary_text)
    detail_tokens = token_set(detail_text)
    if not detail_tokens:
        return False
    novel_tokens = detail_tokens - primary_tokens
    if len(novel_tokens) >= 3:
        return True
    return any(any(ch.isdigit() for ch in token) for token in novel_tokens)


SLACK_DETAIL_SUPPRESS_SOURCES = {
    "venturebeat",
    "fooddive",
}


def _suppress_news_detail_for_source(source_name: Any) -> bool:
    return _normalized_field_key(source_name) in SLACK_DETAIL_SUPPRESS_SOURCES


def _split_text_sentences(value: Any) -> list[str]:
    text = _strip_html_for_matching(value)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _is_company_context_sentence(sentence: Any, company: Any) -> bool:
    sentence_text = _safe_text(sentence)
    company_text = _safe_text(company)
    if not sentence_text or not company_text:
        return False
    sentence_key = _normalized_field_key(sentence_text)
    company_key = _normalized_field_key(company_text)
    if not sentence_key or not company_key or company_key not in sentence_key:
        return False
    lowered = sentence_text.lower()
    context_markers = [
        " is ",
        ", a ",
        ", an ",
        "based in",
        "maker",
        "startup",
        "company",
        "brand",
        "platform",
        "develops",
        "offers",
        "provides",
        "builds",
        "operator",
    ]
    return any(marker in lowered for marker in context_markers)


def _extract_company_context_sentence(
    *,
    company: Any,
    title: Any,
    description: Any,
    article: Any,
    summary: Any,
) -> str:
    company_text = _safe_text(company)
    if not company_text:
        return ""
    candidate_texts = [summary, description, article, title]
    for candidate in candidate_texts:
        for sentence in _split_text_sentences(candidate):
            if _is_company_context_sentence(sentence, company_text):
                return _terminal_period(_truncate_slack_detail(sentence))
    company_key = _normalized_field_key(company_text)
    for candidate in candidate_texts:
        for sentence in _split_text_sentences(candidate):
            sentence_key = _normalized_field_key(sentence)
            if sentence_key and company_key and company_key in sentence_key:
                return _terminal_period(_truncate_slack_detail(sentence))
    return ""


def _ensure_company_context_summary(
    *,
    summary: Any,
    company: Any,
    title: Any,
    description: Any,
    article: Any,
) -> str:
    summary_text = _terminal_period(_truncate_slack_detail(summary))
    company_text = _safe_text(company)
    if not company_text:
        return summary_text
    if summary_text and _is_company_context_sentence(summary_text, company_text):
        return summary_text
    context_sentence = _extract_company_context_sentence(
        company=company_text,
        title=title,
        description=description,
        article=article,
        summary=summary_text,
    )
    if not context_sentence:
        return summary_text
    if summary_text:
        summary_key = _normalized_field_key(summary_text)
        context_key = _normalized_field_key(context_sentence)
        if summary_key and context_key and context_key in summary_key:
            return summary_text
        return f"{summary_text} {context_sentence}".strip()
    return context_sentence


def _build_news_slack_content(*, title: str, description: str, link: str, source_name: str) -> str:
    parts: list[str] = []
    title_text = _terminal_period(title)
    description_text = _terminal_period(description)
    if title_text:
        parts.append(title_text)
    if (
        description_text
        and description_text != title_text
        and not _suppress_news_detail_for_source(source_name)
        and not _is_redundant_slack_detail(title_text, description_text)
        and _has_material_novel_detail(title_text, description_text)
    ):
        parts.append(description_text)
    source_link = _format_slack_link(source_name, link)
    body = " ".join(part for part in parts if part).strip()
    if not body and not source_link:
        return ""
    lines: list[str] = []
    if body:
        lines.append(f"• {body}")
    if source_link:
        lines.append(f"Source: {source_link}")
    return "\n".join(lines) + "\n"


def _build_rich_slack_content(*, primary: str, detail: str, link: str, source_name: str, force_detail: bool = False) -> str:
    parts: list[str] = []
    primary_text = _terminal_period(primary)
    detail_text = _terminal_period(_truncate_slack_detail(detail))
    if primary_text:
        parts.append(primary_text)
    if detail_text:
        primary_cmp = primary_text.rstrip(".!?").lower()
        detail_cmp = detail_text.rstrip(".!?").lower()
        if detail_cmp and detail_cmp != primary_cmp and (
            force_detail
            or (
                not _is_redundant_slack_detail(primary_text, detail_text)
                and _has_material_novel_detail(primary_text, detail_text)
            )
        ):
            parts.append(detail_text)
    source_link = _format_slack_link(source_name, link)
    body = " ".join(part for part in parts if part).strip()
    if not body and not source_link:
        return ""
    lines: list[str] = []
    if body:
        lines.append(f"• {body}")
    if source_link:
        lines.append(f"Source: {source_link}")
    return "\n".join(lines) + "\n"


def _build_slack_content(
    *,
    event_type: str,
    company: str,
    title: str,
    description: str,
    link: str,
    source_name: str,
    ai_fields: dict[str, Any],
) -> str:
    ai_summary = _safe_text(ai_fields.get("summary", ""))
    company_description = _safe_text(ai_fields.get("company_description", ""))
    normalized_event_type = _safe_text(event_type).lower()
    normalized_company = _safe_text(company)

    # Integrate company_description into ai_summary as appositive for funding/M&A events
    # Format: "Company, a description of what they do, raised $X..." (like original articles)
    enhanced_summary = ai_summary
    if company_description and ai_summary and normalized_event_type in {"funding", "acquisition", "merger"}:
        # Extract description text (strip company name and "is/are" prefix)
        # Pattern: "[Company](url) is a developer..." → "a developer..."
        desc_match = re.search(r"(?:is|are)\s+(.+?)\.?\s*$", company_description, re.IGNORECASE)
        if desc_match:
            description_text = desc_match.group(1).strip()

            # Find company name at start of ai_summary
            # Pattern: "[Company](url) raised..." or "Company raised..."
            company_match = re.match(r"^(\[[^\]]+\]\([^)]+\)|[A-Z][^\s,]+(?:\s+[A-Z][^\s,]+)*)\s+(.+)", ai_summary)
            if company_match:
                company_part = company_match.group(1)
                rest_of_summary = company_match.group(2)
                # Integrate as appositive: "Company, description, rest"
                enhanced_summary = f"{company_part}, {description_text}, {rest_of_summary}"
            else:
                # Fallback: prepend as separate sentence
                enhanced_summary = f"{company_description} {ai_summary}"
        else:
            # Fallback: prepend as separate sentence
            enhanced_summary = f"{company_description} {ai_summary}"
    elif company_description and not ai_summary:
        enhanced_summary = company_description

    if normalized_event_type in {"funding", "acquisition", "merger"}:
        return _build_rich_slack_content(
            primary=enhanced_summary,
            detail="",
            link=link,
            source_name=source_name,
        )
    if not normalized_company:
        return _build_news_slack_content(
            title=title,
            description=ai_summary,
            link=link,
            source_name=source_name,
        )

    funding = ai_fields.get("funding", {})
    mna = ai_fields.get("mna", {})
    amount = _safe_text(funding.get("amount", ""))
    round_type = _safe_text(funding.get("round", ""))
    investors = funding.get("investors", [])
    lead_investor = ""
    if isinstance(investors, list):
        for item in investors:
            lead_investor = _safe_text(item)
            if lead_investor:
                break

    if normalized_event_type == "funding" and amount:
        investment_subject, investment_target = _extract_investment_subject_target(title, description, ai_summary)
        funding_company = normalized_company
        funding_investor = ""
        if investment_subject and investment_target:
            normalized_company_key = _normalized_field_key(normalized_company)
            subject_key = _normalized_field_key(investment_subject)
            target_key = _normalized_field_key(investment_target)
            if normalized_company_key and normalized_company_key == subject_key:
                funding_company = investment_target
                funding_investor = investment_subject
            elif normalized_company_key and normalized_company_key == target_key:
                funding_company = normalized_company
                funding_investor = investment_subject

        message = f"{funding_company} raised {amount}"
        if round_type:
            message += f" in a {round_type} round"
        else:
            rounds_detail = _extract_funding_rounds_detail(ai_summary, description)
            if rounds_detail:
                message += f" {rounds_detail}"
        if funding_investor:
            message += f" from {funding_investor}"
        elif lead_investor:
            message += f" led by {lead_investor}"

        # Use enhanced_summary (includes company_description) if available
        summary_primary = enhanced_summary if enhanced_summary else message
        return _build_rich_slack_content(
            primary=summary_primary,
            detail="",
            link=link,
            source_name=source_name,
        )

    if normalized_event_type in {"acquisition", "merger"}:
        acquirer = _safe_text(mna.get("acquirer", ""))
        target = _safe_text(mna.get("target", ""))
        deal_amount = _safe_text(mna.get("amount", ""))
        if acquirer and target:
            primary = f"{acquirer} acquired {target}"
            if deal_amount:
                if _is_not_disclosed_amount(deal_amount):
                    primary += " for an undisclosed amount"
                else:
                    primary += f" for {deal_amount}"
            # Use enhanced_summary (includes company_description) if available
            summary_primary = enhanced_summary if enhanced_summary else primary
            return _build_rich_slack_content(
                primary=summary_primary,
                detail="",
                link=link,
                source_name=source_name,
            )

    plain_name_match = re.match(r"\[([^\]]+)\]", normalized_company)
    plain_company_name = plain_name_match.group(1) if plain_name_match else normalized_company
    enriched_title = _replace_company_in_text(title, plain_company_name, normalized_company)
    return _build_news_slack_content(
        title=enriched_title,
        description=ai_summary,
        link=link,
        source_name=source_name,
    )


def _normalize_slack_content(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    return (
        text.replace("â€¢ ", "\u2022 ")
        .replace("• ", "\u2022 ")
        .replace("Ã¢â‚¬Â¢ ", "\u2022 ")
    )


def _is_structured_airtable_event_ready(
    *,
    event_type: str,
    company: str,
    ai_fields: dict[str, Any],
) -> bool:
    normalized_company = _safe_text(company)
    if event_type == "funding":
        funding = ai_fields.get("funding", {})
        amount = _safe_text(funding.get("amount", ""))
        round_name = _safe_text(funding.get("round", ""))
        investors_raw = funding.get("investors", [])
        investors_list = investors_raw if isinstance(investors_raw, list) else []
        investors = [_safe_text(item) for item in investors_list if _safe_text(item)]
        return bool(normalized_company and (amount or round_name or investors))
    if event_type in {"acquisition", "merger"}:
        mna = ai_fields.get("mna", {})
        acquirer = _safe_text(mna.get("acquirer", ""))
        target = _safe_text(mna.get("target", ""))
        return bool(normalized_company and acquirer and target)
    return False


def _coerce_event_type_for_required_fields(
    *,
    event_type: str,
    company: str,
    ai_fields: dict[str, Any],
) -> str:
    normalized_event_type = _safe_text(event_type).lower() or "consumer_industry_news"
    normalized_company = _safe_text(company)
    if not normalized_company:
        return "consumer_industry_news"
    if normalized_event_type == "funding":
        funding = ai_fields.get("funding", {})
        amount = _safe_text(funding.get("amount", ""))
        round_name = _safe_text(funding.get("round", ""))
        investors_raw = funding.get("investors", [])
        investors_list = investors_raw if isinstance(investors_raw, list) else []
        investors = [_safe_text(item) for item in investors_list if _safe_text(item)]
        summary = _safe_text(ai_fields.get("summary", ""))
        has_funding_detail = bool(amount or round_name or investors)
        has_investment_summary = "investment" in summary.lower()
        return "funding" if (has_funding_detail or has_investment_summary) else "consumer_industry_news"
    if normalized_event_type in {"acquisition", "merger"}:
        mna = ai_fields.get("mna", {})
        acquirer = _safe_text(mna.get("acquirer", ""))
        target = _safe_text(mna.get("target", ""))
        return normalized_event_type if acquirer and target else "consumer_industry_news"
    return "consumer_industry_news"


def _validate_ai_event_fields(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI content must be an object")
    required = ["company", "company_description", "summary", "funding", "mna"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"OpenAI content missing keys: {', '.join(missing)}")
    funding = payload.get("funding")
    if not isinstance(funding, dict):
        raise RuntimeError("OpenAI content funding must be an object")
    mna = payload.get("mna")
    if not isinstance(mna, dict):
        raise RuntimeError("OpenAI content mna must be an object")
    investors = funding.get("investors", [])
    if not isinstance(investors, list):
        raise RuntimeError("OpenAI content funding.investors must be an array")
    cleaned_investors = [_safe_text(item) for item in investors if _safe_text(item)]
    return {
        "company": _safe_text(payload.get("company", "")),
        "company_description": _safe_text(payload.get("company_description", "")),
        "company_category": _safe_text(payload.get("company_category", "")),
        "summary": _safe_text(payload.get("summary", "")),
        "funding": {
            "amount": _safe_text(funding.get("amount", "")),
            "valuation": _safe_text(funding.get("valuation", "")),
            "round": _safe_text(funding.get("round", "")),
            "investors": cleaned_investors,
        },
        "mna": {
            "acquirer": _safe_text(mna.get("acquirer", "")),
            "target": _safe_text(mna.get("target", "")),
            "amount": _safe_text(mna.get("amount", "")),
            "target_prior_raise": _safe_text(mna.get("target_prior_raise", "")),
            "target_prior_valuation": _safe_text(mna.get("target_prior_valuation", "")),
        },
    }


def _batch_item_index(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    try:
        return int(value.get("index"))
    except Exception:
        return None


def _recover_batch_items_by_index(
    items: list[Any],
    expected_indices: list[int],
) -> list[dict[str, Any]] | None:
    if not isinstance(items, list):
        return None
    by_index: dict[int, dict[str, Any]] = {}
    for item in items:
        idx = _batch_item_index(item)
        if idx is None:
            continue
        if idx in by_index:
            continue
        by_index[idx] = item
    missing = [idx for idx in expected_indices if idx not in by_index]
    if missing:
        return None
    return [by_index[idx] for idx in expected_indices]


def _validate_ai_event_fields_batch(
    payload: dict[str, Any],
    expected_count: int,
    expected_indices: list[int] | None = None,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI batch content must be an object")
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("OpenAI batch content missing items array")
    expected_index_values = list(expected_indices or list(range(expected_count)))
    if len(expected_index_values) != expected_count:
        raise RuntimeError("OpenAI batch expected_indices length mismatch")
    if len(items) != expected_count:
        recovered = _recover_batch_items_by_index(items, expected_index_values)
        if recovered is None:
            raise RuntimeError(f"OpenAI batch item count mismatch: expected {expected_count}, got {len(items)}")
        _flow_write_line(
            "AI BATCH RECOVER | mode=count_mismatch "
            f"| expected={expected_count} | got={len(items)}"
        )
        items = recovered
    else:
        has_index_mismatch = False
        for idx, item in enumerate(items):
            returned_index = _batch_item_index(item)
            if returned_index != expected_index_values[idx]:
                has_index_mismatch = True
                break
        if has_index_mismatch:
            recovered = _recover_batch_items_by_index(items, expected_index_values)
            if recovered is None:
                raise RuntimeError("OpenAI batch item index mismatch and recovery failed")
            _flow_write_line(
                "AI BATCH RECOVER | mode=index_mismatch "
                f"| expected={expected_count} | got={len(items)}"
            )
            items = recovered
    normalized_categories = [item for item in (categories or []) if _safe_text(item)]
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise RuntimeError(f"OpenAI batch item {idx} must be an object")
        returned_index = _batch_item_index(item)
        if returned_index is None:
            raise RuntimeError(f"OpenAI batch item {idx} missing valid index")
        if returned_index != expected_index_values[idx]:
            raise RuntimeError(
                f"OpenAI batch item index mismatch at position {idx}: expected {expected_index_values[idx]}, got {returned_index}"
            )
        validated = _validate_ai_event_fields(item)
        validated["company_category"] = _coerce_company_category(
            raw_value=validated.get("company_category", ""),
            company=validated.get("company", ""),
            categories=normalized_categories,
        )
        out.append(validated)
    return out


_FALLBACK_CATEGORIES = [
    "Consumer Tech / Apps",
    "B2B",
    "VMS",
    "Consumer Hardware",
    "Travel & Hospitality",
    "Beauty & Personal Care",
    "Entertainment & Media",
    "General Consumer / Other",
    "Food & Beverage",
    "Retail / Four Wall",
    "Pet",
    "Home & Living",
    "Fitness",
    "Health Tech",
    "Apparel & Accessories",
    "FinTech",
    "Retail & Commerce Enablement",
]


def _canonical_company_categories(settings: dict[str, Any]) -> list[str]:
    cats = settings.get("company_categories", [])
    if not isinstance(cats, list) or not cats:
        cats = _FALLBACK_CATEGORIES
    out: list[str] = []
    seen: set[str] = set()
    for candidate in cats:
        text = _safe_text(candidate)
        if not text:
            continue
        key = _normalized_field_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _coerce_company_category(
    *,
    raw_value: Any,
    company: Any,
    categories: list[str],
) -> str:
    canonical_by_key: dict[str, str] = {}
    canonical_by_signature: dict[str, str] = {}
    for category in categories:
        key = _normalized_field_key(category)
        if key and key not in canonical_by_key:
            canonical_by_key[key] = category
        signature = _category_signature(category)
        if signature and signature not in canonical_by_signature:
            canonical_by_signature[signature] = category
    raw_text = _safe_text(raw_value)
    if not raw_text:
        return ""
    raw_text = re.sub(r"^\s*category\s*[:\-]\s*", "", raw_text, flags=re.IGNORECASE).strip()
    raw_key = _normalized_field_key(raw_text)
    if raw_key and raw_key in canonical_by_key:
        return canonical_by_key[raw_key]
    raw_signature = _category_signature(raw_text)
    if raw_signature and raw_signature in canonical_by_signature:
        return canonical_by_signature[raw_signature]
    return ""


def _category_tokens(value: Any) -> list[str]:
    text = _safe_text(value).lower()
    if not text:
        return []
    normalized = text.replace("&", " and ").replace("/", ",").replace("|", ",").replace("+", ",")
    normalized = re.sub(r"\band\b", ",", normalized, flags=re.IGNORECASE)
    parts = [part.strip() for part in re.split(r"[;,]", normalized) if part.strip()]
    tokens: list[str] = []
    if parts:
        for part in parts:
            token = _normalized_field_key(part)
            if token and token not in tokens:
                tokens.append(token)
        return tokens
    token = _normalized_field_key(normalized)
    return [token] if token else []


def _category_signature(value: Any) -> str:
    tokens = sorted(set(_category_tokens(value)))
    if not tokens:
        return ""
    return "|".join(tokens)


def _build_category_rule(settings: dict[str, Any]) -> str:
    cats = _canonical_company_categories(settings)
    cats_str = ", ".join(cats)
    has_not_consumer = any(c.strip().lower() == "not consumer" for c in cats)
    if has_not_consumer:
        no_match_instruction = (
            "Use 'Not Consumer' when the company is clearly not a consumer-facing business "
            "(e.g., enterprise software, B2B infrastructure, defense, government). "
            "Use '' (empty string) when there is no identifiable company or category cannot be determined confidently from explicit text."
        )
    else:
        no_match_instruction = (
            "Use '' (empty string) when category cannot be determined confidently from explicit source text "
            "or when there is no identifiable company."
        )
    return (
        f"company_category must be one of: {cats_str}. "
        f"{no_match_instruction} "
        "Choose the best fit from explicit source text. "
        "Preserve the exact label format from the allowed list (including separators like '/', '&', or ',')."
    )


def derive_ai_event_fields(
    *,
    title: str,
    description: str,
    article: str,
    link: str,
    published: str,
    source_name: str,
    event_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "model": settings["model"],
        "temperature": settings["temperature"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a deterministic Consumer VC analyst. "
                    "Evaluate items like venture deal-flow screening: prioritize factual entity resolution, "
                    "transaction direction, named funding participants, and explicit evidence only. "
                    "Normalize this feed item into event fields. "
                    "Return strict JSON only with keys: company, company_description, summary, funding, mna. "
                    "Use empty strings for missing scalar values and an empty array for missing investors. "
                    "Do not add other keys. "
                    "DO NOT speculate. DO NOT invent facts. "
                    "DO NOT output markdown or commentary. "
                    "DO NOT use a PERSON as company. "
                    "DO NOT treat an investor as the funded company unless explicitly stated. "
                    + (
                        "For consumer_industry_news: Extract a clear, substantive summary (2-3 sentences) of the main points "
                        "and key industry insights from the article. Focus on what the article reveals about trends, companies, or market movements. "
                        "Use direct facts from the content only."
                        if event_type == "consumer_industry_news"
                        else ""
                    )
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "event_type": event_type,
                        "title": title,
                        "description": description,
                        "AIContent": article,
                        "article": article,
                        "link": link,
                        "published": published,
                        "source_name": source_name,
                        "required_schema": {
                            "company": "string",
                            "company_description": "string",
                            "company_category": "string",
                            "summary": "string",
                            "funding": {
                                "amount": "string",
                                "valuation": "string",
                                "round": "string",
                                "investors": ["string"],
                            },
                            "mna": {
                                "acquirer": "string",
                                "target": "string",
                                "amount": "string",
                                "target_prior_raise": "string",
                                "target_prior_valuation": "string",
                            },
                        },
                        "rules": [
                            "COMPANY EXTRACTION RULES (CRITICAL):",
                            "  1. DO NOT extract articles or particles as company names: 'The', 'This', 'That', 'A', 'An', 'These', 'Those'.",
                            "  2. DO NOT extract single common words as company names: 'Company', 'Inc', 'Ltd', 'Corp', 'Group', 'Organization'.",
                            "  3. Extract company from EXPLICIT ORGANIZATION ENTITIES ONLY - proper names of actual companies/orgs mentioned in the content.",
                            "  4. Prioritize company names that appear in financial/transaction context (e.g., 'for [Company Name]', '[Company] raised', '[Company] acquired').",
                            "  5. Search the FULL AIContent for company entity, not just the first capitalized word.",
                            "  6. If title/description mentions a company name, cross-verify it appears in AIContent context.",
                            "  7. If company entity is ambiguous or could be a generic phrase, return empty string instead of guessing.",
                            "Use the explicit company or organization from the feed item.",
                            "company_description must be a 1-2 sentence description of what the company does. Use explicit text from AIContent when available. If not explicit in AIContent, infer from company name, context, or category. Only use empty string if truly unknown.",
                            "summary must be 1-2 factual sentences and include the most specific explicit transaction details available.",
                            "If company is non-empty, summary must include one factual sentence about what the company is or does using explicit source text only.",
                            "Use AIContent as the primary source for summary and transaction details when AIContent is available.",
                            "If AIContent starts with 'Failed to get data:', treat AIContent as unavailable.",
                            "Do not prefer title + description over AIContent when AIContent is available.",
                            "When AIContent is available, write the 1-2 sentence factual summary from AIContent and preserve the fullest explicit transaction detail available.",
                            "If event_type is funding, populate funding fields when stated; otherwise leave them empty.",
                            "If event_type is funding and the amount is stated, include the amount in summary.",
                            "If event_type is funding and the round is stated, include the round in summary.",
                            "If event_type is funding and one or more investors are explicitly named, include ALL named investors (lead and other backers) in the investors array.",
                            "For funding items, prefer the most complete explicit funding sentence from AIContent, including named investors or consortium members when stated.",
                            "If event_type is funding and a post-money valuation is explicitly stated, populate funding.valuation with the valuation string.",
                            "If event_type is acquisition or merger, populate mna fields when stated; otherwise leave them empty.",
                            "If event_type is acquisition or merger and the target company's prior funding raise is explicitly stated, populate mna.target_prior_raise.",
                            "If event_type is acquisition or merger and the target company's prior valuation is explicitly stated, populate mna.target_prior_valuation.",
                            _build_category_rule(settings),
                            "Do not infer unsupported values beyond what is explicit in the feed item.",
                            "Do NOT speculate or rewrite with promotional language.",
                            "Do NOT choose a PERSON entity as company when an ORGANIZATION exists.",
                            "Do NOT map an investor entity to company unless the text explicitly says that entity raised funding.",
                            "Do NOT fabricate amount, round, investors, acquirer, or target.",
                        ],
                    },
                    ensure_ascii=False,
                    indent=0,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "feed_item_normalized_fields",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "company": {"type": "string"},
                        "company_description": {"type": "string"},
                        "company_category": {"type": "string"},
                        "summary": {"type": "string"},
                        "funding": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "amount": {"type": "string"},
                                "valuation": {"type": "string"},
                                "round": {"type": "string"},
                                "investors": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["amount", "valuation", "round", "investors"],
                        },
                        "mna": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "acquirer": {"type": "string"},
                                "target": {"type": "string"},
                                "amount": {"type": "string"},
                                "target_prior_raise": {"type": "string"},
                                "target_prior_valuation": {"type": "string"},
                            },
                            "required": ["acquirer", "target", "amount", "target_prior_raise", "target_prior_valuation"],
                        },
                    },
                    "required": ["company", "company_description", "company_category", "summary", "funding", "mna"],
                },
            },
        },
    }
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=max(1, int(settings["timeout_ms"]) // 1000),
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {str(resp.text or '')[:500]}")
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"OpenAI response is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("OpenAI response must be an object")
    content = _extract_openai_content(data)
    try:
        parsed = json.loads(content)
    except Exception as exc:
        raise RuntimeError(f"OpenAI content is not valid JSON: {exc}") from exc
    validated = _validate_ai_event_fields(parsed)
    validated["company_category"] = _coerce_company_category(
        raw_value=validated.get("company_category", ""),
        company=validated.get("company", ""),
        categories=_canonical_company_categories(settings),
    )
    # Simple fallback: if AI couldn't extract description, use category as description
    if not validated.get("company_description") and validated.get("company_category"):
        category = validated.get("company_category", "")
        company = validated.get("company", "")
        if category and company:
            validated["company_description"] = f"{company} operates in {category}."
    return validated


def derive_ai_event_fields_batch(*, items: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    payload = {
        "model": settings["model"],
        "temperature": settings["temperature"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a deterministic Consumer VC analyst. "
                    "Evaluate items like venture deal-flow screening: prioritize factual entity resolution, "
                    "transaction direction, named funding participants, and explicit evidence only. "
                    "Normalize these feed items into event fields. "
                    "Return strict JSON only with one top-level key: items. "
                    "items must be an array with the same length and same order as the input. "
                    "Each item must include keys: index, company, company_description, summary, funding, mna. "
                    "Use empty strings for missing scalar values and an empty array for missing investors. "
                    "Do not add other keys. "
                    "DO NOT speculate. DO NOT invent facts. "
                    "DO NOT output markdown or commentary. "
                    "DO NOT use a PERSON as company. "
                    "DO NOT treat an investor as the funded company unless explicitly stated."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "items": items,
                        "required_schema": {
                            "items": [
                                {
                                    "index": "integer",
                                    "company": "string",
                                    "company_description": "string",
                                    "company_category": "string",
                                    "summary": "string",
                                    "funding": {
                                        "amount": "string",
                                        "valuation": "string",
                                        "round": "string",
                                        "investors": ["string"],
                                    },
                                    "mna": {
                                        "acquirer": "string",
                                        "target": "string",
                                        "amount": "string",
                                        "target_prior_raise": "string",
                                        "target_prior_valuation": "string",
                                    },
                                }
                            ]
                        },
                        "rules": [
                            "Preserve item order exactly.",
                            "Return one output item for every input item.",
                            "Use the explicit company or organization from each feed item.",
                            "company_description must be a 1-2 sentence description of what the company does. Use explicit text from AIContent when available. If not explicit in AIContent, infer from company name, context, or category. Only use empty string if truly unknown.",
                            "summary must be 1-2 factual sentences for each item and include the most specific explicit transaction details available.",
                            "If company is non-empty for an item, summary for that item must include one factual sentence about what the company is or does using explicit source text only.",
                            "Use each item's AIContent as the primary source for summary and transaction details when AIContent is available.",
                            "If AIContent starts with 'Failed to get data:', treat AIContent as unavailable.",
                            "Do not prefer title + description over AIContent when AIContent is available.",
                            "When AIContent is available, write the 1-2 sentence factual summary from AIContent for that item and preserve the fullest explicit transaction detail available.",
                            "If event_type is funding, populate funding fields when stated; otherwise leave them empty.",
                            "If event_type is funding and the amount is stated, include the amount in summary.",
                            "If event_type is funding and the round is stated, include the round in summary.",
                            "If event_type is funding and one or more investors are explicitly named, include ALL named investors (lead and other backers) in the investors array.",
                            "For funding items, prefer the most complete explicit funding sentence from AIContent, including named investors or consortium members when stated.",
                            "If event_type is funding and a post-money valuation is explicitly stated, populate funding.valuation with the valuation string.",
                            "If event_type is acquisition or merger, populate mna fields when stated; otherwise leave them empty.",
                            "If event_type is acquisition or merger and the target company's prior funding raise is explicitly stated, populate mna.target_prior_raise.",
                            "If event_type is acquisition or merger and the target company's prior valuation is explicitly stated, populate mna.target_prior_valuation.",
                            _build_category_rule(settings),
                            "Do not infer unsupported values beyond what is explicit in each feed item.",
                            "Do NOT speculate or rewrite with promotional language.",
                            "Do NOT choose a PERSON entity as company when an ORGANIZATION exists.",
                            "Do NOT map an investor entity to company unless the text explicitly says that entity raised funding.",
                            "Do NOT fabricate amount, round, investors, acquirer, or target.",
                        ],
                    },
                    ensure_ascii=False,
                    indent=0,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "feed_item_normalized_fields_batch",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "index": {"type": "integer"},
                                    "company": {"type": "string"},
                                    "company_description": {"type": "string"},
                                    "company_category": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "funding": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "amount": {"type": "string"},
                                            "valuation": {"type": "string"},
                                            "round": {"type": "string"},
                                            "investors": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": ["amount", "valuation", "round", "investors"],
                                    },
                                    "mna": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "acquirer": {"type": "string"},
                                            "target": {"type": "string"},
                                            "amount": {"type": "string"},
                                            "target_prior_raise": {"type": "string"},
                                            "target_prior_valuation": {"type": "string"},
                                        },
                                        "required": ["acquirer", "target", "amount", "target_prior_raise", "target_prior_valuation"],
                                    },
                                },
                                "required": ["index", "company", "company_description", "company_category", "summary", "funding", "mna"],
                            },
                        }
                    },
                    "required": ["items"],
                },
            },
        },
    }
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=max(1, int(settings["timeout_ms"]) // 1000),
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {str(resp.text or '')[:500]}")
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"OpenAI response is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("OpenAI response must be an object")
    content = _extract_openai_content(data)
    try:
        parsed = json.loads(content)
    except Exception as exc:
        raise RuntimeError(f"OpenAI content is not valid JSON: {exc}") from exc
    expected_indices = [int(item.get("index", idx)) for idx, item in enumerate(items)]
    return _validate_ai_event_fields_batch(
        parsed,
        len(items),
        expected_indices=expected_indices,
        categories=_canonical_company_categories(settings),
    )


FUNDING_KEYWORDS = [
    "raises",
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

ACQUISITION_KEYWORDS = [
    "acquires",
    "acquired",
    "acquisition",
    "buying",
    "buys",
    "sold to",
    "purchase",
    "purchased",
    "to acquire",
]

MERGER_KEYWORDS = [
    "merge",
    "merger",
    "combining with",
    "joining forces",
    "merging with",
    "merge with",
    "merged with",
]

# Keywords in TITLE that indicate article mentions M&A in context, not as main topic
# These suppress M&A classification when found in title
NONMNA_CONTEXT_KEYWORDS = [
    "interview",
    "founder on",
    "return to",
    "back on",
    "podcast",
    "video episode",
    "video:",
    "featured on",
    "appears on",
    "q&a",
    "qa:",
    "talks about",
    "discusses",
    "speaking",
]

INDUSTRY_PREQUAL_KEYWORDS = [
    "ipo",
    "valuation",
    "launches",
    "expands",
    "partnership",
]

# Articles matching ANY of these phrases are dropped unless a hard deal signal is present.
# Covers government/cyber-attack noise, military/defense, macro-data, buybacks, and pure PR.
NEGATIVE_PREQUAL_KEYWORDS = [
    # Nation-state / government hacking operations
    "government hackers",
    "government hacker",
    "state-sponsored",
    "nation-state",
    "russian hackers",
    "russian spies",
    "chinese hackers",
    "iranian hackers",
    "north korean hackers",
    "hacking campaign",
    "hacking toolkit",
    "spies warn",
    "spy agency",
    "intelligence agency warn",
    "dutch spies",
    # Military / defence / espionage
    "military contractor",
    "defense contractor",
    "defence contractor",
    "pentagon",
    "nato",
    "warfare",
    "spy tool",
    "spyware",
    "iphone hacking",
    "android hacking",
    # Cyber-incident focused (not company news)
    "ransomware attack",
    "ransomware gang",
    "phishing campaign",
    "malware campaign",
    "zero-day exploit",
    "zero day exploit",
    "cyberattack on",
    "cyber attack on",
    # Share repurchase — not VC-relevant
    "share buyback",
    "buyback program",
    "stock repurchase",
    "share repurchase",
    "repurchase shares",
    "repurchase program",
    # Pure macro / earnings releases
    "quarterly earnings",
    "q4 earnings",
    "q3 earnings",
    "q2 earnings",
    "q1 earnings",
    "earnings per share",
    "beats analyst",
    "misses analyst",
    "beats expectations",
    "misses expectations",
    "same-store sales",
    "comparable store sales",
    "gdp growth",
    "gdp report",
    "inflation rate",
    "cpi report",
    "cpi data",
    "fed rate",
    "federal reserve",
    "interest rate decision",
    # Government / legal / regulatory noise
    "senate hearing",
    "congressional hearing",
    "law enforcement operation",
    "criminal charges",
    "indicted for",
    "arrested for",
    "fbi operation",
    # Trade show presence only (no deal)
    "exhibiting at",
    "booth at",
    "at the show",
    # Job postings
    "is hiring",
    "now hiring",
    "job opening",
    "open position",
]

# Industry-news items must also contain at least one consumer-sector keyword to pass.
CONSUMER_SECTOR_KEYWORDS = [
    # Category terms
    "consumer", "retail", "e-commerce", "ecommerce", "direct-to-consumer", "d2c", "dtc",
    "marketplace", "brand", "brands",
    # Food & beverage
    "food", "beverage", "drink", "snack", "nutrition", "supplement", "grocery",
    "restaurant", "dining", "meal", "cpg", "consumer packaged goods",
    # Beauty / personal care
    "beauty", "skincare", "skin care", "cosmetic", "cosmetics", "personal care",
    "haircare", "hair care", "fragrance", "grooming",
    # Health & wellness
    "wellness", "health", "fitness", "workout", "gym", "mental health",
    # Fashion & apparel
    "fashion", "apparel", "clothing", "footwear", "shoe", "sneaker", "luxury",
    "streetwear", "activewear",
    # Home & living
    "home goods", "furniture", "kitchenware", "home decor", "household",
    # Pet
    "pet food", "pet care", "pet",
    # Travel & hospitality
    "travel", "hospitality", "hotel", "vacation", "tourism",
    # Entertainment & media
    "entertainment", "streaming", "gaming", "content creator", "media platform",
    # Consumer fintech
    "fintech", "neobank", "payments", "payment app", "buy now pay later", "bnpl",
    "lending", "insurance", "personal finance",
    # Shopping / retail signals
    "shoppers", "consumers", "customers", "store", "shops", "brick-and-mortar",
    "subscription", "membership",
    # Startup / VC context
    "startup", "venture", "series a", "series b", "series c", "seed round",
]

FINANCIAL_SCALE_TERMS = [
    "transaction volume",
    "total transaction volume",
    "volume",
    "valuation",
    "revenue",
    "arr",
    "aov",
    "gmv",
    "tpv",
    "assets under management",
    "aum",
    "bookings",
]

FINANCIAL_THRESHOLD_VERBS = [
    "crosses",
    "crossed",
    "exceeds",
    "exceeded",
    "reaches",
    "reached",
    "hits",
    "hit",
]

MONEY_SIGNAL_PATTERN = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?[kmb])?|\b\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|thousand|million|billion)\b)",
    flags=re.IGNORECASE,
)

AI_BATCH_CHUNK_SIZE = 8


def _has_financial_scale_signal(text: str) -> bool:
    haystack = _safe_text(text).lower()
    if not haystack:
        return False
    if not MONEY_SIGNAL_PATTERN.search(haystack):
        return False
    if any(term in haystack for term in FINANCIAL_SCALE_TERMS):
        return True
    if any(verb in haystack for verb in FINANCIAL_THRESHOLD_VERBS):
        return True
    return False


def _has_hard_deal_signal(text: str) -> bool:
    haystack = _safe_text(text).lower()
    if not haystack:
        return False
    # M&A phrases are generally unambiguous.
    if any(keyword in haystack for keyword in ACQUISITION_KEYWORDS + MERGER_KEYWORDS):
        return True

    # Funding needs stricter gating than raw keyword matches to avoid noise like
    # "state-backed" and "series of attacks".
    has_funding_verb = any(
        keyword in haystack
        for keyword in [
            "raised",
            "raises",
            "raising",
            "raise",
            "secured",
            "secures",
            "close",
            "closes",
            "closed",
            "closing",
        ]
    )
    has_funding_context = any(
        keyword in haystack
        for keyword in [
            "funding",
            "fundraise",
            "fundraising",
            "investment round",
            "seed round",
            "series a",
            "series b",
            "series c",
            "series d",
            "series e",
            "series f",
            "series g",
            "series h",
            "pre-seed",
            "round",
            "valuation",
        ]
    )
    if has_funding_verb and (has_funding_context or MONEY_SIGNAL_PATTERN.search(haystack)):
        return True
    if re.search(r"\bseries\s+[a-h]\b", haystack):
        return True
    if re.search(r"\b(seed|pre-seed)\s+round\b", haystack):
        return True
    return False


def _passes_prequal(*, title: str, description: str) -> bool:
    haystack = _safe_text(f"{title} {description}").lower()
    if not haystack:
        return False
    has_hard_deal_signal = _has_hard_deal_signal(haystack)
    if any(keyword in haystack for keyword in NEGATIVE_PREQUAL_KEYWORDS) and not has_hard_deal_signal:
        return False
    if has_hard_deal_signal:
        return True
    has_industry_signal = (
        any(keyword in haystack for keyword in INDUSTRY_PREQUAL_KEYWORDS)
        or _has_financial_scale_signal(haystack)
    )
    if not has_industry_signal:
        return False
    return any(keyword in haystack for keyword in CONSUMER_SECTOR_KEYWORDS)


def _url_filter_keys(url: str) -> set[str]:
    text = _safe_text(url)
    if not text:
        return set()
    keys: set[str] = {text}
    parsed = urlparse(text)
    host = _safe_text(parsed.netloc).lower().removeprefix("www.")
    path = _safe_text(parsed.path)
    path_no_trailing = path.rstrip("/") or path
    if host and path_no_trailing:
        keys.add(f"{host}{path_no_trailing}")
        keys.add(f"http://{host}{path_no_trailing}")
        keys.add(f"https://{host}{path_no_trailing}")
    return keys


def classify_event_type(*, title: str, description: str) -> str:
    """Classify event type from title and description.

    Strategy: M&A keywords must appear in TITLE to classify as acquisition/merger.
    If M&A keywords only appear in description (not title), they're usually context,
    not the main topic. This prevents false positives like "Founder Interview" that
    happens to mention a past acquisition.

    For funding: Distinguish between specific company funding events vs. industry
    analysis/trend articles. Articles mentioning multiple companies or using broad
    industry language (trends, pipeline, landscape, data) are classified as NEWS.
    """
    title_lower = _safe_text(title).lower()
    haystack = _safe_text(f"{title} {description}").lower()

    if not haystack:
        return "industry_news"

    # Check if title suggests interview/feature context (article is NOT about the M&A event itself)
    has_context_keyword = any(keyword in title_lower for keyword in NONMNA_CONTEXT_KEYWORDS)

    # M&A classification requires keywords in TITLE (not just description)
    if has_context_keyword:
        # If title has context keyword like "interview", don't classify as acquisition/merger
        # even if description mentions them - check funding instead
        if any(keyword in haystack for keyword in FUNDING_KEYWORDS):
            return "funding"
        return "industry_news"

    # No context keyword - apply standard M&A classification
    if any(keyword in title_lower for keyword in MERGER_KEYWORDS):
        return "merger"
    if any(keyword in title_lower for keyword in ACQUISITION_KEYWORDS):
        return "acquisition"

    # For funding, check if this is an INDUSTRY ANALYSIS article vs. specific company funding
    if any(keyword in haystack for keyword in FUNDING_KEYWORDS):
        # Check for industry analysis keywords that indicate this is about trends/landscape
        # not a specific company's funding announcement
        industry_analysis_keywords = [
            "trend", "pipeline", "data:", "analysis", "diversified", "landscape",
            "round count", "funding count", "average", "market", "sector", "category"
        ]
        has_industry_analysis_signal = any(keyword in title_lower for keyword in industry_analysis_keywords)

        # If title contains broad industry language, this is NEWS not a specific funding event
        if has_industry_analysis_signal:
            return "industry_news"

        # Otherwise it's a specific company funding announcement
        return "funding"

    return "industry_news"


def build_normalized_ai_block(
    *,
    title: str,
    description: str,
    article: str,
    link: str,
    published: str,
    source_name: str,
    openai_settings: dict[str, Any],
    airtable_placeholders: dict[str, Any] | None = None,
    article_source_code: str = "A",
) -> dict[str, Any]:
    event_type = classify_event_type(
        title=title,
        description=article or description,
    )
    ai_fields = derive_ai_event_fields(
        title=title,
        description=description,
        article=article,
        link=link,
        published=published,
        source_name=source_name,
        event_type=event_type,
        settings=openai_settings,
    )
    return _assemble_normalized_ai_block(
        title=title,
        description=description,
        article=article,
        link=link,
        published=published,
        source_name=source_name,
        airtable_placeholders=airtable_placeholders,
        event_type=event_type,
        ai_fields=ai_fields,
        article_source_code=article_source_code,
        openai_settings=openai_settings,
    )


def build_normalized_ai_blocks_batch(
    *,
    items: list[dict[str, Any]],
    source_name: str,
    openai_settings: dict[str, Any],
    airtable_placeholders: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_placeholders = dict(airtable_placeholders or {})
    compact_items: list[dict[str, Any]] = []
    entry_payloads: list[dict[str, Any]] = []
    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"batch item {idx} must be an object")
        title = _safe_text(raw_item.get("title", ""))
        link = _safe_text(raw_item.get("link", ""))
        description = _safe_text(raw_item.get("description", ""))
        ai_content = _safe_text(raw_item.get("AIContent", "") or raw_item.get("article", ""))
        article = ai_content
        published = _safe_text(raw_item.get("published", ""))
        event_type = classify_event_type(
            title=title,
            description=ai_content or description,
        )
        compact_items.append(
            {
                "index": idx,
                "event_type": event_type,
                "title": title,
                "description": description,
                "AIContent": ai_content,
                "article": article,
                "link": link,
                "published": published,
                "source_name": source_name,
                "article_source_code": _article_source_code(raw_item.get("article_source_code", "A")),
            }
        )
        entry_payloads.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "AIContent": ai_content,
                "article": article,
                "published": published,
                "event_type": event_type,
                "article_source_code": _article_source_code(raw_item.get("article_source_code", "A")),
            }
        )
    batched_ai_fields: list[dict[str, Any]] = []
    if compact_items:
        for start in range(0, len(compact_items), AI_BATCH_CHUNK_SIZE):
            chunk = compact_items[start : start + AI_BATCH_CHUNK_SIZE]
            try:
                chunk_fields = derive_ai_event_fields_batch(
                    items=chunk,
                    settings=openai_settings,
                )
            except RuntimeError as exc:
                # Recover from occasional batch-shape anomalies by retrying per item.
                _flow_write_line(
                    "AI BATCH FALLBACK | "
                    f"source={_flow_safe_text(source_name)} | "
                    f"chunk_start={start} | chunk_size={len(chunk)} | "
                    f"reason={_flow_safe_text(exc)}"
                )
                chunk_fields = []
                for local_idx, chunk_item in enumerate(chunk):
                    try:
                        chunk_fields.append(
                            derive_ai_event_fields(
                                title=_safe_text(chunk_item.get("title", "")),
                                description=_safe_text(chunk_item.get("description", "")),
                                article=_safe_text(chunk_item.get("AIContent", "") or chunk_item.get("article", "")),
                                link=_safe_text(chunk_item.get("link", "")),
                                published=_safe_text(chunk_item.get("published", "")),
                                source_name=_safe_text(chunk_item.get("source_name", "")) or source_name,
                                event_type=_safe_text(chunk_item.get("event_type", "")) or "consumer_industry_news",
                                settings=openai_settings,
                            )
                        )
                    except Exception as item_exc:
                        raise RuntimeError(
                            f"AI single-item fallback failed at chunk_offset={start + local_idx}: {item_exc}"
                        ) from item_exc
            batched_ai_fields.extend(chunk_fields)
    out: list[dict[str, Any]] = []
    for idx, entry_payload in enumerate(entry_payloads):
        out.append(
            _assemble_normalized_ai_block(
                title=entry_payload["title"],
                description=entry_payload["description"],
                article=entry_payload["article"],
                link=entry_payload["link"],
                published=entry_payload["published"],
                source_name=source_name,
                airtable_placeholders=normalized_placeholders,
                event_type=entry_payload["event_type"],
                ai_fields=batched_ai_fields[idx],
                article_source_code=entry_payload["article_source_code"],
                openai_settings=openai_settings,
            )
        )
    return out


def _assemble_normalized_ai_block(
    *,
    title: str,
    description: str,
    article: str,
    link: str,
    published: str,
    source_name: str,
    airtable_placeholders: dict[str, Any] | None,
    event_type: str,
    ai_fields: dict[str, Any],
    article_source_code: str,
    openai_settings: dict[str, Any],
) -> dict[str, Any]:
    normalized_placeholders = dict(airtable_placeholders or {})
    funding_company, funding_investor = _resolve_funding_company_from_investment_phrase(
        company=ai_fields.get("company", ""),
        title=title,
        description=description,
        ai_summary=ai_fields.get("summary", ""),
        event_type=event_type,
    )
    resolved_company = funding_company if funding_company else _safe_text(ai_fields.get("company", ""))
    company_description = _safe_text(ai_fields.get("company_description", ""))
    if not company_description:
        company_description = _extract_company_context_sentence(
            company=resolved_company,
            title=title,
            description=description,
            article=article,
            summary=ai_fields.get("summary", ""),
        )
    company_description = _terminal_period(_truncate_slack_detail(company_description))
    resolved_funding = dict(ai_fields.get("funding", {}) if isinstance(ai_fields.get("funding", {}), dict) else {})
    resolved_mna = dict(ai_fields.get("mna", {}) if isinstance(ai_fields.get("mna", {}), dict) else {})
    investors_raw = resolved_funding.get("investors", [])
    investors_list = investors_raw if isinstance(investors_raw, list) else []
    investors_clean = [_safe_text(item) for item in investors_list if _safe_text(item)]
    if funding_investor and all(_normalized_field_key(name) != _normalized_field_key(funding_investor) for name in investors_clean):
        investors_clean.insert(0, funding_investor)
    resolved_funding["investors"] = investors_clean
    resolved_mna["amount"] = _normalize_mna_amount(
        event_type=event_type,
        current_amount=resolved_mna.get("amount", ""),
        title=title,
        description=description,
        article=article,
        ai_summary=ai_fields.get("summary", ""),
    )
    plain_company = resolved_company
    company_url = _resolve_company_website(resolved_company, openai_settings)
    resolved_company = _format_company_hyperlink(resolved_company, company_url)
    ai_summary = _replace_company_in_text(
        _safe_text(ai_fields.get("summary", "")), plain_company, resolved_company
    )
    company_description = _replace_company_in_text(company_description, plain_company, resolved_company)
    # Fallback: also replace the base name (without legal suffix like Inc., Corp., Ltd.)
    # so e.g. "Dataiku" gets linked when the resolved company is "Dataiku Inc."
    _base_company = re.sub(
        r"\s+(?:Inc|Corp|Ltd|LLC|PBC|AG|GmbH|SA|SAS|BV|NV|Plc)\.$",
        "", plain_company, flags=re.IGNORECASE
    ).strip()
    if _base_company and _base_company != plain_company:
        ai_summary = _replace_company_in_text(ai_summary, _base_company, resolved_company)
        company_description = _replace_company_in_text(company_description, _base_company, resolved_company)
    resolved_ai_fields = {
        "company": resolved_company,
        "company_description": company_description,
        "company_category": _safe_text(ai_fields.get("company_category", "")),
        "summary": ai_summary,
        "funding": resolved_funding,
        "mna": resolved_mna,
    }
    if event_type in {"acquisition", "merger"}:
        plain_acquirer = _safe_text(resolved_mna.get("acquirer", ""))
        if plain_acquirer:
            acquirer_url = _resolve_company_website(plain_acquirer, openai_settings)
            acquirer_hyperlink = _format_company_hyperlink(plain_acquirer, acquirer_url)
            resolved_ai_fields["company"] = acquirer_hyperlink
            resolved_ai_fields["summary"] = _replace_company_in_text(
                resolved_ai_fields["summary"], plain_acquirer, acquirer_hyperlink
            )
    effective_event_type = _coerce_event_type_for_required_fields(
        event_type=event_type,
        company=resolved_ai_fields["company"],
        ai_fields=resolved_ai_fields,
    )
    published_date = _normalize_published_date(published)
    event_flag = (
        "Y"
        if _is_structured_airtable_event_ready(
            event_type=effective_event_type,
            company=resolved_ai_fields["company"],
            ai_fields=resolved_ai_fields,
        )
        else "N"
    )
    airtable_payload = _populate_airtable_fields(
        normalized_placeholders,
        company=resolved_ai_fields["company"],
        event_type=effective_event_type,
        title=title,
        description=description,
        link=link,
        source_name=source_name,
        published_date=published_date,
        ai_fields=resolved_ai_fields,
    )
    slack_content = _normalize_slack_content(
        _build_slack_content(
            event_type=effective_event_type,
            company=resolved_ai_fields["company"],
            title=title,
            description=description,
            link=link,
            source_name=source_name,
            ai_fields=resolved_ai_fields,
        )
    )
    if not slack_content:
        fallback_source = _format_slack_link(source_name, link)
        if fallback_source:
            slack_content = f"Source: {fallback_source}\n"
        else:
            slack_content = "\u2022 Update.\n"
    airtable_payload["SlackContent"] = _prepare_slack_content_for_payload(slack_content)
    airtable_target_table = "events" if event_flag == "Y" else "news"
    return {
        "company": resolved_ai_fields["company"],
        "company_description": resolved_ai_fields["company_description"],
        "event_type": effective_event_type,
        "AIContent": article,
        "AIsummary": resolved_ai_fields["summary"],
        "article": article,
        "event": {
            "headline": title,
            "summary": resolved_ai_fields["summary"],
            "published_date": published_date,
        },
        "source": {
            "name": source_name,
            "url": _format_markdown_link(source_name, link),
        },
        "funding": resolved_ai_fields["funding"],
        "mna": resolved_ai_fields["mna"],
        "Event Flag": event_flag,
        "Article Source Code": _article_source_code(article_source_code),
        "AirtableTargetTable": airtable_target_table,
        "airtable": airtable_payload,
    }


def parse_feed_file(
    input_path: Path,
    *,
    openai_settings: dict[str, Any],
    airtable_placeholders: dict[str, Any],
    max_items: int | None = None,
    source_name_override: str = "",
    source_url_override: str = "",
    apply_prequal: bool = True,
    article_fetch_progress_hook: Any | None = None,
    allowed_urls: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if max_items is not None:
        max_items = int(max_items)
        if max_items < 0:
            raise RuntimeError("max_items must be >= 0")
    apply_prequal = bool(apply_prequal)
    apply_allowed_url_filter = allowed_urls is not None
    allowed_url_keys: set[str] = set()
    if apply_allowed_url_filter:
        for allowed_url in list(allowed_urls or []):
            allowed_url_keys.update(_url_filter_keys(str(allowed_url)))
    xml_bytes = input_path.read_bytes()
    parser = etree.XMLParser(recover=True, remove_comments=False, strip_cdata=False)
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except Exception:
        root = None
    parsed = feedparser.parse(xml_bytes)
    entries = list(getattr(parsed, "entries", []) or [])
    if root is None and not entries:
        html_entries = _parse_html_feed_entries(
            xml_bytes.decode("utf-8", errors="ignore"),
            _safe_text(source_url_override),
        )
        if not html_entries:
            raise RuntimeError("source response is neither XML feed nor parseable HTML listing")
        entries = html_entries
        root = etree.Element("html_feed")
    if root is None:
        root = etree.Element("feed")

    namespaces = {
        (key or ""): value
        for key, value in getattr(root, "nsmap", {}).items()
        if value
    }
    xml_items = _xml_item_nodes(root)
    source_name = _safe_text(source_name_override) or _safe_text(getattr(parsed.feed, "title", ""))
    if not source_name:
        source_name = _safe_text(urlparse(_safe_text(source_url_override)).netloc.removeprefix("www."))

    item_count = max(len(entries), len(xml_items))
    if max_items is not None:
        item_count = min(item_count, int(max_items))
    article_phase_total = 0
    for scan_idx in range(item_count):
        scan_entry = entries[scan_idx] if scan_idx < len(entries) else {}
        scan_link = _safe_text(_entry_value(scan_entry, "link"))
        if apply_allowed_url_filter:
            scan_keys = _url_filter_keys(scan_link)
            if not scan_keys or scan_keys.isdisjoint(allowed_url_keys):
                continue
        scan_title = _safe_text(_entry_value(scan_entry, "title"))
        scan_description_raw = _safe_text(_entry_value(scan_entry, "description"))
        scan_summary_raw = _safe_text(_entry_value(scan_entry, "summary"))
        scan_description = scan_description_raw or scan_summary_raw
        if (not apply_prequal) or _passes_prequal(title=scan_title, description=scan_description):
            article_phase_total += 1
    article_phase_current = 0
    if callable(article_fetch_progress_hook) and article_phase_total > 0:
        try:
            article_fetch_progress_hook(
                {
                    "attempted": 0,
                    "record_index": 0,
                    "record_total": article_phase_total,
                    "source_name": source_name_override,
                    "url": "",
                }
            )
        except Exception:
            pass
    feed_header_published = _feed_header_published_fallback(root, parsed)
    prequal_discarded = 0
    article_fetch_success = 0
    article_fetch_failed = 0
    article_fetch_cache_hits = 0
    article_fetch_disk_cache_hits = 0
    article_fetch_domain_cooldown_skips = 0
    article_fetch_skipped_by_event_gate = 0
    article_cdata_used = 0
    article_fetch_attempted = 0
    article_description_fallback_used = 0
    article_summary_fallback_used = 0
    article_title_fallback_used = 0
    skipped_not_in_allowed_urls = 0
    article_fetch_method_counts = {
        "selenium": 0,
        "playwright": 0,
        "urllib": 0,
        "wayback": 0,
        "disk_cache": 0,
    }
    article_cache: dict[str, str] = {}
    article_source_cache: dict[str, str] = {}
    article_method_cache: dict[str, str] = {}
    article_cooldowns = _load_article_cooldowns()
    use_wayback_flag = "N"
    article_retrieval_disabled_flag = "N"
    first_live_probe_completed = False
    filtered_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    for idx in range(item_count):
        _flow_write_line(
            f"## Now Processing Record {idx + 1:02d} "
            f"{'-' * 109}"
        )
        entry = entries[idx] if idx < len(entries) else {}
        xml_item = xml_items[idx] if idx < len(xml_items) else None
        title = _safe_text(_entry_value(entry, "title"))
        link = _safe_text(_entry_value(entry, "link"))
        description_raw = _safe_text(_entry_value(entry, "description"))
        summary_raw = _safe_text(_entry_value(entry, "summary"))
        description = description_raw or summary_raw
        likely_event_type = classify_event_type(title=title, description=description)
        published = _safe_text(
            _entry_value(entry, "published")
            or _entry_value(entry, "pubDate")
            or _entry_value(entry, "updated")
            or feed_header_published
        )
        if apply_allowed_url_filter:
            link_keys = _url_filter_keys(link)
            if not link_keys or link_keys.isdisjoint(allowed_url_keys):
                skipped_not_in_allowed_urls += 1
                excluded_rows.append(
                    {
                        "source_index": idx,
                        "entry": entry,
                        "xml_item": xml_item,
                        "payload": {
                            "title": title,
                            "link": link,
                            "description": description,
                            "published": published,
                            "skip_reason": "already_seen_or_not_in_current_batch",
                        },
                    }
                )
                continue
        if apply_prequal and (not _passes_prequal(title=title, description=description)):
            prequal_discarded += 1
            excluded_rows.append(
                {
                    "source_index": idx,
                    "entry": entry,
                    "xml_item": xml_item,
                    "payload": {
                        "title": title,
                        "link": link,
                        "description": description,
                        "published": published,
                    },
                }
            )
            continue
        if callable(article_fetch_progress_hook) and article_phase_total > 0:
            article_phase_current += 1
            try:
                article_fetch_progress_hook(
                    {
                        "attempted": article_phase_current,
                        "record_index": idx + 1,
                        "record_total": article_phase_total,
                        "source_name": source_name,
                        "url": link,
                    }
                )
            except Exception:
                pass
        article_source_code = "A"
        article_fetch_method = ""
        if link in article_cache:
            ai_content = article_cache[link]
            article_source_code = _article_source_code(article_source_cache.get(link, "A"))
            article_fetch_method = _safe_text(article_method_cache.get(link, "memory_cache"))
            article_fetch_cache_hits += 1
        else:
            has_cdata = _xml_item_has_cdata(xml_item)
            fetched_content = ""
            fetch_outcome = ""
            should_fetch_article = likely_event_type in {"funding", "acquisition", "merger"}
            cached_disk_content = _read_article_cache(link)
            if cached_disk_content:
                fetched_content = cached_disk_content
                fetch_outcome = "disk_cache"
                article_fetch_disk_cache_hits += 1
                article_source_code = "A"
                article_fetch_method = "disk_cache"
            elif article_retrieval_disabled_flag == "Y":
                fetched_content = _article_failure_message("article retrieval disabled after first-record failure")
                fetch_outcome = "article_fetch_disabled"
                article_source_code = "B"
            elif not should_fetch_article:
                fetched_content = _article_failure_message(
                    f"article fetch skipped for event type {likely_event_type}"
                )
                fetch_outcome = "event_gate_skip"
                article_fetch_skipped_by_event_gate += 1
                article_source_code = "B"
            elif _is_article_domain_in_cooldown(link, article_cooldowns):
                fetched_content = _article_failure_message("domain cooldown active")
                fetch_outcome = "domain_cooldown"
                article_fetch_domain_cooldown_skips += 1
                article_source_code = "F"
            else:
                article_fetch_attempted += 1
                live_probe_active = use_wayback_flag != "Y"
                fast_fail_live = live_probe_active and not first_live_probe_completed
                fetched_content, fetch_outcome, fetch_source, fetch_method = _fetch_article_text_with_cache(
                    link,
                    cooldowns=article_cooldowns,
                    use_wayback_only=(use_wayback_flag == "Y"),
                    fast_fail_live=fast_fail_live,
                )
                article_fetch_method = _safe_text(fetch_method)
                if fetch_outcome == "disk_cache":
                    article_fetch_disk_cache_hits += 1
                    article_source_code = "A"
                    article_fetch_method = "disk_cache"
                elif fetch_outcome == "domain_cooldown":
                    article_fetch_domain_cooldown_skips += 1
                    article_source_code = "F"
                elif fetch_source == "wayback":
                    article_source_code = "W"
                elif fetch_source == "live":
                    article_source_code = "A"
                if live_probe_active and not first_live_probe_completed:
                    first_live_probe_completed = True
                    if fetch_source == "wayback":
                        use_wayback_flag = "Y"
                    elif fetch_source == "failure":
                        article_retrieval_disabled_flag = "Y"
            if _is_article_failure(fetched_content):
                cdata_fallback = _safe_text(description_raw or _entry_content_value(entry) or summary_raw)
                if has_cdata and cdata_fallback:
                    ai_content = cdata_fallback
                    article_cdata_used += 1
                    if article_source_code != "B":
                        article_source_code = "F"
                else:
                    description_fallback = _truncate_article_text(_strip_html_for_matching(description_raw))
                    summary_fallback = _truncate_article_text(_strip_html_for_matching(summary_raw))
                    if description_fallback:
                        ai_content = description_fallback
                        article_description_fallback_used += 1
                        if article_source_code != "B":
                            article_source_code = "F"
                    elif summary_fallback:
                        ai_content = summary_fallback
                        article_summary_fallback_used += 1
                        if article_source_code != "B":
                            article_source_code = "F"
                    elif title:
                        ai_content = _truncate_article_text(title)
                        article_title_fallback_used += 1
                        if article_source_code != "B":
                            article_source_code = "F"
                    else:
                        ai_content = fetched_content
                        if article_source_code != "B":
                            article_source_code = "F"
            else:
                ai_content = fetched_content
                if article_source_code not in {"A", "W"}:
                    article_source_code = "A"
            if article_fetch_method in article_fetch_method_counts:
                article_fetch_method_counts[article_fetch_method] += 1
            article_cache[link] = ai_content
            article_source_cache[link] = _article_source_code(article_source_code)
            article_method_cache[link] = article_fetch_method
        if _is_article_failure(ai_content):
            article_fetch_failed += 1
        else:
            article_fetch_success += 1
        entry_payload = {
            "title": title,
            "link": link,
            "description": description,
            "AIContent": ai_content,
            "article": ai_content,
            "published": published,
            "article_source_code": _article_source_code(article_source_code),
            "article_fetch_method": article_fetch_method,
        }
        filtered_rows.append(
            {
                "source_index": idx,
                "entry": entry,
                "xml_item": xml_item,
                "payload": entry_payload,
            }
        )
    feed_items = [row["payload"] for row in filtered_rows]
    ai_blocks = build_normalized_ai_blocks_batch(
        items=feed_items,
        source_name=source_name,
        openai_settings=openai_settings,
        airtable_placeholders=airtable_placeholders,
    )
    item_details: list[dict[str, Any]] = []
    for idx, row in enumerate(filtered_rows):
        source_idx = int(row["source_index"])
        entry = row["entry"]
        xml_item = row["xml_item"]
        keys = sorted(list(entry.keys())) if isinstance(entry, dict) else sorted(list(entry.keys()))
        entry_payload = row["payload"]
        ai_block = ai_blocks[idx]
        item_details.append(
            {
                "index": source_idx,
                "ai": ai_block,
                "feedparser": {
                    "keys": keys,
                    "title": entry_payload["title"],
                    "link": entry_payload["link"],
                    "description": entry_payload["description"],
                    "AIContent": entry_payload["AIContent"],
                    "published": entry_payload["published"],
                    "article_fetch_method": entry_payload["article_fetch_method"],
                    "id": _safe_text(_entry_value(entry, "id") or _entry_value(entry, "guid")),
                },
                "xml": _xml_item_summary(xml_item) if xml_item is not None else {},
            }
        )

    return {
        "source_file": str(input_path),
        "feedparser_xml": _build_feedparser_xml(filtered_rows),
        "newspaper3k_xml": _build_newspaper3k_xml(filtered_rows),
        "EcludedFromRun": _build_item_xml(excluded_rows, "excluded_from_run_items"),
        "raw_bytes": len(xml_bytes),
        "lxml": {
            "root_tag": _local_name(root.tag),
            "namespaces": namespaces,
            "item_node_count": len(xml_items),
        },
        "feedparser": {
            "bozo": bool(getattr(parsed, "bozo", False)),
            "bozo_exception": _safe_text(getattr(parsed, "bozo_exception", "")),
            "openai_config_path": str(openai_settings["config_path"]),
            "openai_model": str(openai_settings["model"]),
            "feed": {
                "title": _safe_text(getattr(parsed.feed, "title", "")),
                "link": _safe_text(getattr(parsed.feed, "link", "")),
                "description": _safe_text(
                    getattr(parsed.feed, "description", "") or getattr(parsed.feed, "subtitle", "")
                ),
            },
            "entry_count": len(entries),
            "max_items_applied": item_count,
            "allowed_url_count": len(allowed_url_keys) if apply_allowed_url_filter else 0,
            "skipped_not_in_allowed_urls": skipped_not_in_allowed_urls,
            "prequal_discarded": prequal_discarded,
            "prequal_passed": len(feed_items),
            "ai_evaluated_count": len(feed_items),
            "article_fetch_success": article_fetch_success,
            "article_fetch_failed": article_fetch_failed,
            "article_fetch_cache_hits": article_fetch_cache_hits,
            "article_fetch_disk_cache_hits": article_fetch_disk_cache_hits,
            "article_fetch_domain_cooldown_skips": article_fetch_domain_cooldown_skips,
            "article_fetch_skipped_by_event_gate": article_fetch_skipped_by_event_gate,
            "article_cdata_used": article_cdata_used,
            "article_fetch_attempted": article_fetch_attempted,
            "article_description_fallback_used": article_description_fallback_used,
            "article_summary_fallback_used": article_summary_fallback_used,
            "article_title_fallback_used": article_title_fallback_used,
            "article_fetch_method_counts": article_fetch_method_counts,
            "UseWayback": use_wayback_flag,
            "ArticleRetrievalDisabled": article_retrieval_disabled_flag,
        },
        "items": item_details,
    }


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_parsed_inspect.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a local XML news feed file with feedparser and lxml, then write an inspection JSON file."
    )
    parser.add_argument("input_file", nargs="?", help="Path to the local XML feed file")
    parser.add_argument(
        "--output",
        help="Optional output JSON path. Default: <input_stem>_parsed_inspect.json next to the input file.",
        default="",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Optional cap on the number of feed records to process from the XML file.",
    )
    parser.add_argument(
        "--openai-config",
        help="Optional OpenAI config JSON path. Default: Proposals/MikeG/config/openai_shared_global.json",
        default="",
    )
    parser.add_argument(
        "--global-config",
        help="Optional Global.json path for Airtable metadata. Default: Proposals/MikeG/Global.json",
        default="",
    )
    args = parser.parse_args()

    if not _safe_text(args.input_file):
        print("FAIL-FAST: missing input_file", file=sys.stderr)
        print("Drag an .xml feed file onto this script, or run:", file=sys.stderr)
        print(
            "python ParseFeedFile.py \"C:\\path\\to\\feed.xml\"",
            file=sys.stderr,
        )
        return 2

    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.exists() or not input_path.is_file():
        raise RuntimeError(f"Input file not found: {input_path}")
    if input_path.suffix.lower() != ".xml":
        raise RuntimeError(f"Input file must be an .xml file: {input_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if _safe_text(args.output)
        else default_output_path(input_path)
    )
    openai_config_path = (
        Path(args.openai_config).expanduser().resolve()
        if _safe_text(args.openai_config)
        else default_openai_config_path()
    )
    global_config_path = (
        Path(args.global_config).expanduser().resolve()
        if _safe_text(args.global_config)
        else default_global_config_path()
    )
    openai_settings = load_openai_settings(openai_config_path)
    airtable_placeholders = load_airtable_event_field_placeholders(global_config_path)

    payload = parse_feed_file(
        input_path,
        openai_settings=openai_settings,
        airtable_placeholders=airtable_placeholders,
        max_items=getattr(args, "max_items", None),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    feedparser_xml = payload.get("feedparser_xml")
    if not isinstance(feedparser_xml, str) or not feedparser_xml.strip():
        raise RuntimeError("parse_feed_file missing required feedparser_xml")
    feedparser_xml_path = output_path.with_name("feedparser.xml")
    feedparser_xml_path.write_text(feedparser_xml, encoding="utf-8")
    print(str(output_path))
    return 0


_enable_flow_tracing()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL-FAST: {exc}", file=sys.stderr)
        raise
