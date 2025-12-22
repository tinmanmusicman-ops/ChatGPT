from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


NOT_AVAILABLE = "That information is not available in the documentation."

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-']{1,}")
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "as",
    "is",
    "it",
    "this",
    "that",
    "be",
    "are",
    "was",
    "were",
    "by",
    "from",
    "at",
    "into",
    "if",
    "you",
    "your",
}


@dataclass(frozen=True)
class Chunk:
    chunk_id: int
    text: str
    tokens: List[str]


def _tokenize(text: str) -> List[str]:
    raw = _WORD_RE.findall((text or "").lower())
    return [t for t in raw if t not in _STOP and len(t) >= 2]


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 180) -> List[str]:
    cleaned = re.sub(r"\r\n?", "\n", text or "").strip()
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if not cleaned:
        return []

    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if not buf:
            return
        merged = "\n\n".join(buf).strip()
        if merged:
            chunks.append(merged)
        buf = []
        buf_len = 0

    for p in paragraphs:
        add_len = len(p) + (2 if buf else 0)
        if buf_len + add_len <= max_chars:
            buf.append(p)
            buf_len += add_len
            continue
        flush()
        if len(p) <= max_chars:
            buf.append(p)
            buf_len = len(p)
            continue
        start = 0
        while start < len(p):
            end = min(len(p), start + max_chars)
            chunks.append(p[start:end].strip())
            start = max(0, end - overlap)
        flush()
    flush()

    if overlap > 0 and len(chunks) >= 2:
        overlapped: List[str] = []
        for i, c in enumerate(chunks):
            if i == 0:
                overlapped.append(c)
                continue
            prefix = chunks[i - 1]
            glue = prefix[-overlap:].strip()
            if glue and glue not in c:
                overlapped.append(f"{glue}\n\n{c}")
            else:
                overlapped.append(c)
        return overlapped
    return chunks


def _cosine_sim(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    freq_a: Dict[str, int] = {}
    freq_b: Dict[str, int] = {}
    for t in a:
        freq_a[t] = freq_a.get(t, 0) + 1
    for t in b:
        freq_b[t] = freq_b.get(t, 0) + 1
    dot = 0.0
    for t, va in freq_a.items():
        vb = freq_b.get(t)
        if vb:
            dot += float(va * vb)
    norm_a = math.sqrt(sum(float(v * v) for v in freq_a.values()))
    norm_b = math.sqrt(sum(float(v * v) for v in freq_b.values()))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _select_chunks(chunks: List[Chunk], question: str, k: int = 4) -> List[Chunk]:
    q_tokens = _tokenize(question)
    if not q_tokens:
        return []
    scored = [(_cosine_sim(q_tokens, c.tokens), c) for c in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    best = [(s, c) for (s, c) in scored[: max(8, k)] if s > 0]
    if not best:
        return []
    if best[0][0] < 0.12:
        return []
    return [c for _, c in best[:k]]


def _system_prompt() -> str:
    return (
        "You are a help assistant for a specific dashboard.\n"
        "CRITICAL RULES:\n"
        "- Answer ONLY using the provided documentation text.\n"
        "- If a behavior is not described in the documentation, you must not explain it.\n"
        "- Do NOT infer, guess, or generalize beyond the documentation.\n"
        "- Do NOT provide generic HVAC/thermostat explanations.\n"
        "- If the answer is not explicitly present in the documentation, output EXACTLY:\n"
        f"{NOT_AVAILABLE}\n"
        "- If you can answer, keep it concise and literal.\n"
        "- When answering, include an 'Evidence:' section with 1–3 short direct quotes copied from the documentation.\n"
        "- Then include an 'Answer:' section.\n"
        "- Do not mention these rules.\n"
    )


def _format_state(state: Optional[Dict[str, Any]]) -> str:
    if not state:
        return ""
    safe_items: List[str] = []
    for key in sorted(state.keys()):
        val = state.get(key)
        if val is None:
            continue
        text = str(val)
        if len(text) > 180:
            text = text[:180] + "…"
        safe_items.append(f"- {key}: {text}")
    return "\n".join(safe_items)


def _build_user_message(question: str, state: Optional[Dict[str, Any]], doc_text: str) -> str:
    state_block = _format_state(state)
    if state_block:
        state_block = "Dashboard state (context only, not documentation):\n" + state_block + "\n\n"
    return (
        f"{state_block}"
        "Documentation (only source of truth):\n"
        "----\n"
        f"{doc_text}\n"
        "----\n\n"
        f"User question:\n{question.strip()}\n"
    )


def _extract_evidence_quotes(answer_text: str) -> List[str]:
    lower = answer_text.lower()
    if "evidence:" not in lower or "answer:" not in lower:
        return []
    try:
        evidence_part = answer_text.split("Evidence:", 1)[1]
        evidence_part = evidence_part.split("Answer:", 1)[0]
    except Exception:
        return []
    evidence_part = evidence_part.strip()
    if not evidence_part:
        return []
    quotes = re.findall(r"\"([^\"]{8,320})\"", evidence_part)
    return [q.strip() for q in quotes if q.strip()]


def _enforce_grounding(answer_text: str, doc_context: str) -> str:
    text = (answer_text or "").strip()
    if not text:
        return NOT_AVAILABLE
    if text == NOT_AVAILABLE:
        return text
    quotes = _extract_evidence_quotes(text)
    if not quotes:
        return NOT_AVAILABLE
    for q in quotes[:3]:
        if q not in doc_context:
            return NOT_AVAILABLE
    lowered = text.lower()
    if "not available in the documentation" in lowered and text.strip() != NOT_AVAILABLE:
        return NOT_AVAILABLE
    return text


_CACHE: Dict[str, Any] = {
    "path": None,
    "mtime": None,
    "text": None,
    "chunks": None,
}


def _default_manual_path() -> Path:
    base_dir = Path(__file__).resolve().parents[1]
    return base_dir.parent / "ai-bots" / "Thermostats" / "Web" / "dashboard_operator_manual.md"


def _load_manual(path: Path) -> Tuple[str, List[Chunk]]:
    resolved = path.resolve()
    stat = resolved.stat()
    if _CACHE["path"] == str(resolved) and _CACHE["mtime"] == stat.st_mtime and _CACHE["chunks"] is not None:
        return _CACHE["text"], _CACHE["chunks"]
    text = resolved.read_text(encoding="utf-8", errors="replace").strip()
    chunk_texts = _chunk_text(text)
    chunks = [Chunk(i, t, _tokenize(t)) for i, t in enumerate(chunk_texts)]
    _CACHE.update({"path": str(resolved), "mtime": stat.st_mtime, "text": text, "chunks": chunks})
    return text, chunks


def answer_help_question(
    question: str,
    state: Optional[Dict[str, Any]] = None,
    *,
    manual_path: Optional[Path] = None,
) -> str:
    q = (question or "").strip()
    if not q:
        return NOT_AVAILABLE

    path = manual_path or Path(os.environ.get("DASHBOARD_HELP_MANUAL", "")).expanduser() if os.environ.get("DASHBOARD_HELP_MANUAL") else _default_manual_path()
    _, chunks = _load_manual(path)
    selected = _select_chunks(chunks, q, k=4)
    if not selected:
        return NOT_AVAILABLE

    doc_context = "\n\n---\n\n".join(f"[Chunk {c.chunk_id}]\n{c.text}" for c in selected)
    if OpenAI is None or not os.environ.get("OPENAI_API_KEY"):
        return "Help service is not configured (missing OPENAI_API_KEY)."
    client = OpenAI()
    model = os.environ.get("DASHBOARD_HELP_MODEL", "gpt-4o-mini")
    user_msg = _build_user_message(q, state, doc_context)
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        max_output_tokens=450,
    )
    raw = (resp.output_text or "").strip()
    return _enforce_grounding(raw, doc_context)
