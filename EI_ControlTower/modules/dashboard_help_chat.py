from __future__ import annotations

import math
import os
import re
import difflib
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
    "what",
    "do",
    "does",
    "did",
    "how",
    "why",
    "when",
    "where",
    "which",
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
    normalized: List[str] = []
    for t in raw:
        if t in _STOP or len(t) < 2:
            continue
        # Light normalization: plural -> singular (charts -> chart).
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        normalized.append(t)
    return normalized


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
    vocab = set()
    for c in chunks:
        vocab.update(c.tokens)
    # Fix small typos in query tokens by mapping to nearest vocab term.
    fixed_tokens: List[str] = []
    for t in q_tokens:
        if t in vocab:
            fixed_tokens.append(t)
            continue
        candidates = difflib.get_close_matches(t, vocab, n=1, cutoff=0.84)
        fixed_tokens.append(candidates[0] if candidates else t)
    q_tokens = fixed_tokens
    scored = [(_cosine_sim(q_tokens, c.tokens), c) for c in chunks]
    scored.sort(key=lambda x: x[0], reverse=True)
    best = [(s, c) for (s, c) in scored[: max(8, k)] if s > 0]
    if not best:
        best = []
    # For very short queries (1-2 tokens), accept low-similarity matches so the
    # model can still answer using quoted evidence from retrieved chunks.
    if best and best[0][0] < 0.08 and len(q_tokens) <= 2:
        return [c for _, c in best[:k]]
    # Heuristic fallback for broad questions (e.g., "what do the charts do").
    # Still safe because the model must quote evidence verbatim from provided chunks.
    if not best or best[0][0] < 0.08:
        lowered = (question or "").lower()
        key_terms = []
        if "chart" in lowered:
            key_terms.extend(["history chart", "usage chart", "charts"])
        if "display" in lowered or "view" in lowered or "mode" in lowered:
            key_terms.extend(["display modes", "tv mode", "small mode", "view mode", "tv-mode"])
        if "cassette" in lowered or "transport" in lowered or "tape" in lowered:
            key_terms.extend(["cassette", "transport", "tape", "archive"])
        if "tv" in lowered or "full" in lowered:
            key_terms.extend(["tv mode", "full-screen", "tv"])
        if key_terms:
            matches: List[Chunk] = []
            for c in chunks:
                hay = c.text.lower()
                if any(term in hay for term in key_terms):
                    matches.append(c)
                if len(matches) >= k:
                    break
            if matches:
                return matches[:k]
        return []
    return [c for _, c in best[:k]]


def _system_prompt() -> str:
    return (
        "You are a help assistant for a thermostat dashboard.\n"
        "\n"
        "Your role:\n"
        "- Answer user questions about how the dashboard works.\n"
        "- Explain charts, controls, interactions, and behaviors in plain language.\n"
        "- Help users understand what they are seeing and how to use it.\n"
        "\n"
        "Source of truth:\n"
        "- The provided dashboard documentation text is the authoritative source.\n"
        "- All answers must be grounded in that documentation.\n"
        "\n"
        "Interpretation rules (IMPORTANT):\n"
        "You MAY:\n"
        "- Summarize information across multiple sections.\n"
        "- Rephrase technical descriptions into plain, human language.\n"
        "- Interpret common user phrasing (e.g., 'charts', 'hours', 'timeline', 'how it works').\n"
        "- Connect related concepts that are clearly described in the documentation.\n"
        "\n"
        "You MAY NOT:\n"
        "- Invent features, behaviors, or controls.\n"
        "- Describe actions not present in the documentation.\n"
        "- Rely on general HVAC knowledge or assumptions.\n"
        "- Guess when information is missing.\n"
        "\n"
        "If the documentation does not describe a concept directly or indirectly, respond EXACTLY with:\n"
        f"{NOT_AVAILABLE}\n"
        "\n"
        "Output format:\n"
        "- Write in Markdown.\n"
        "- Include an 'Evidence:' section with 1-3 short direct quotes copied from the documentation.\n"
        "- Each Evidence line MUST be wrapped in double quotes and must match the documentation exactly.\n"
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
    quotes = [q.strip() for q in re.findall(r"\"([^\"]{8,320})\"", evidence_part) if q.strip()]
    if quotes:
        return quotes
    # Fallback: accept bullet/line evidence if it appears verbatim in documentation.
    lines = []
    for line in evidence_part.splitlines():
        t = line.strip()
        if not t:
            continue
        t = re.sub(r"^[-*>\u2022\u203A]\s*", "", t)
        t = re.sub(r"^`(.+)`$", r"\1", t)
        t = t.strip()
        if 8 <= len(t) <= 320:
            lines.append(t)
    return lines[:3]


def _extract_answer_text(answer_text: str) -> str:
    text = (answer_text or "").strip()
    if not text or text == NOT_AVAILABLE:
        return text
    if "Answer:" not in text:
        return text
    return text.split("Answer:", 1)[1].strip() or text


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
    return _extract_answer_text(text)


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

    path = (
        manual_path
        or Path(os.environ.get("DASHBOARD_HELP_MANUAL", "")).expanduser()
        if os.environ.get("DASHBOARD_HELP_MANUAL")
        else _default_manual_path()
    )
    manual_text, chunks = _load_manual(path)

    # Deterministic FAQs (answer from documentation without relying on model formatting).
    lowered = q.lower()
    if lowered in {"display", "display mode", "display modes", "view", "view mode", "view modes"}:
        excerpt_lines: List[str] = []
        in_section = False
        for line in manual_text.splitlines():
            if line.strip() == "## 7. Display Modes":
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section:
                excerpt_lines.append(line.rstrip())
        excerpt = "\n".join(excerpt_lines).strip()
        if excerpt:
            small_mode = "Default. Most components visible."
            tv_mode_enabled = "Enabled by adding `tv-mode` to `<body>`."
            tv_mode_behavior = (
                "In TV mode, CSS hides many small-mode elements and shows TV overlays/bottom bar."
            )
            if all(s in excerpt for s in (small_mode, tv_mode_enabled, tv_mode_behavior)):
                return "\n".join(
                    [
                        "- **Small mode:** Default. Most components visible.",
                        "- **TV mode:** Enabled by adding `tv-mode` to `<body>`. In TV mode, CSS hides many small-mode elements and shows TV overlays/bottom bar.",
                    ]
                )
    if "chart" in lowered:
        intent = lowered.replace("chartrs", "charts").replace("chartr", "chart")
        intent_compact = re.sub(r"\s+", " ", intent).strip()
        wants_chart_overview = (
            intent_compact in {"chart", "charts", "the chart", "the charts"}
            or "what do the chart" in intent_compact
            or "what do chart" in intent_compact
            or "charts do" in intent_compact
        )
        if wants_chart_overview:
            excerpt_lines: List[str] = []
            in_section = False
            for line in manual_text.splitlines():
                normalized = line.strip().replace("“", "\"").replace("”", "\"")
                if normalized.startswith('### 5.11 Quick answer: "What do the charts do?"'):
                    in_section = True
                    continue
                if in_section and line.startswith("### "):
                    break
                if in_section:
                    excerpt_lines.append(line.rstrip())
            excerpt = "\n".join(excerpt_lines).strip()
            if excerpt:
                bullet_lines: List[str] = []
                for ln in excerpt.splitlines():
                    t = ln.strip()
                    if t.startswith("- "):
                        bullet_lines.append(t)
                if bullet_lines:
                    evidence = "\n".join(f"\"{b}\"" for b in bullet_lines[:3])
                    answer = "\n".join(bullet_lines[:3])
                    return _enforce_grounding(f"Evidence:\n{evidence}\n\nAnswer:\n{answer}", excerpt)
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
