#!/usr/bin/env python3
"""
process_new_records.py

Runtime processor for new LiveEvents and LiveInvestors records.
Runs after primary ingestion. Processes all records where New=True on LiveEvents.

Pipeline per run:
  Phase 1 — Gather (no AI):
    1. Fetch all New=True LiveEvents
    2. Per funding_round with empty investors: fetch source article to verify content
    3. Format investors field: comma → one-per-line (exception-aware)
    4. Single-investor shortcut: lead_investor = that one name (no AI needed)
    5. Create missing LiveInvestors records (New=True)
    6. EDGAR lookup + DDG website discovery + Playwright scrape per new investor
    7. Build all OpenAI Batch API tasks:
         verify_investors  — funding_round events with empty investors
         lead_investor     — funding_round events with 2+ investors
         target_company    — m_and_a_transaction events
         enrich_investor   — new LiveInvestors records with scraped content

  Phase 2 — One OpenAI Batch call (all tasks submitted together):
    8. Submit JSONL to /v1/batches — ONE API call
    9. Poll until complete

  Phase 3 — Apply (no AI):
    10. Apply verify_investors results → update investors field; create any
        newly-found investor records (New=True, enriched next run)
    11. Apply lead_investor results → patch events
    12. Apply target_company results → patch events
    13. Apply enrich_investor results → patch LiveInvestors
        (aliases + portfolio_companies enforced to one-per-line)
    14. Set Investor Link + Linked Investors fields on all new events
    15. Uncheck New on all processed events

Usage:
    python process_new_records.py
"""

import json, re, sys, time, tempfile
from pathlib import Path
from openai import OpenAI
from playwright.sync_api import sync_playwright
from ddgs import DDGS
from urllib.parse import urlparse
import requests

ROOT = Path(__file__).resolve().parent.parent.parent
with open(ROOT / "MGlobal.json", encoding="utf-8-sig") as f:
    mg = json.load(f)
with open(ROOT / "Prompts" / "NLCat.txt", encoding="utf-8") as f:
    NLCAT_PROMPT = f.read().strip()
with open(ROOT / "TGlobal.json", encoding="utf-8-sig") as f:
    tg = json.load(f)

KEY       = mg["airtable"]["api_key"]
BASE      = mg["airtable"]["base_id"]
LI_TABLE  = "tblUvtgYxhCtZlCY6"   # LiveInvestors
LE_TABLE  = "tblj0ghNLRnDWYVkC"   # LiveEvents
AT_HEADS  = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
EFTS_HEADS= {"User-Agent": "ConsumerVC-Research/1.0 research@consumervc.com",
              "Accept": "application/json"}
UA        = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")

oai = OpenAI(api_key=tg["openai_api_key"])

VALID_TYPES = {"VC", "Individual", "Corporate", "Government", "Accelerator"}

LOG_PATH = Path(__file__).parent / "process_new_records.log"
LOG_FILE = open(LOG_PATH, "w", encoding="utf-8", buffering=1)

def log(msg=""):
    LOG_FILE.write(msg + "\n"); LOG_FILE.flush()
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()

# ─────────────────────────────────────────────────────────────────────────────
# Multiline field formatting
# ─────────────────────────────────────────────────────────────────────────────
_PROTECTED_SUFFIXES = [
    r"L\.P\.", r"L\.L\.C\.", r"LLC", r"Inc\.", r"Inc",
    r"Corp\.", r"Corp", r"Ltd\.", r"Ltd", r"N\.A\.",
    r"P\.C\.", r"P\.A\.", r"Co\.", r"Co", r"LP", r"GP",
    r"LLP", r"LLLP", r"S\.A\.", r"B\.V\.", r"GmbH", r"PLC",
]
_PROTECT_RE = re.compile(
    r",\s*(?=" + "|".join(_PROTECTED_SUFFIXES) + r")(?=\b|[A-Z])",
    re.IGNORECASE,
)
_PLACEHOLDER = "\x00COMMA\x00"

def comma_to_linefeed(value: str) -> str:
    """Comma-separated → one per line, protecting legal suffixes."""
    if not value or "\n" in value:
        return value
    hidden = _PROTECT_RE.sub(_PLACEHOLDER, value)
    parts  = re.split(r"[,;]\s*", hidden)
    parts  = [p.replace(_PLACEHOLDER, ", ").strip().strip(",;").strip()
               for p in parts if p.strip()]
    return "\n".join(parts)

def parse_investor_names(raw: str) -> list[str]:
    """Parse investors field (linefeed or comma) into a clean list of names."""
    if not raw or raw.strip() == "N/A":
        return []
    if "\n" in raw:
        names = [n.strip() for n in raw.splitlines() if n.strip()]
    else:
        hidden = _PROTECT_RE.sub(_PLACEHOLDER, raw)
        names  = [p.replace(_PLACEHOLDER, ", ").strip().strip(",;").strip()
                  for p in re.split(r"[,;]\s*", hidden) if p.strip()]
    names = [re.sub(r"\s*\(.*?\)", "", n).strip() for n in names]   # strip (lead)
    names = [re.sub(r"\band\b", "&", n, flags=re.I).strip() for n in names]
    names = [re.sub(r"\s+", " ", n).strip() for n in names]
    return [n for n in names if n]

def strip_md(text: str) -> str:
    """Strip markdown links from a field value, e.g. [Name](url) → Name."""
    return re.sub(r"\[([^\]]+)\]\(.*?\)", r"\1", text).strip()

# ─────────────────────────────────────────────────────────────────────────────
# Playwright
# ─────────────────────────────────────────────────────────────────────────────
def playwright_fetch(url: str, timeout_ms: int = 30000) -> str:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page(user_agent=UA)
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            html    = page.content()
            browser.close()
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>",   " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:6000]
    except Exception as e:
        log(f"    Playwright error: {e}")
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# EDGAR
# ─────────────────────────────────────────────────────────────────────────────
def edgar_search(name: str) -> tuple[str, str]:
    for query in [f'"{name}"', name]:
        try:
            r = requests.get("https://efts.sec.gov/LATEST/search-index",
                params={"q": query, "forms": "D", "size": 10},
                headers=EFTS_HEADS, timeout=15)
            if r.status_code == 200:
                for h in r.json().get("hits", {}).get("hits", []):
                    dn = h["_source"].get("display_names", [""])[0].lower()
                    if name.lower() in dn:
                        ciks = h["_source"].get("ciks", [])
                        if ciks:
                            cik = ciks[0]
                            url = (f"https://www.sec.gov/cgi-bin/browse-edgar"
                                   f"?action=getcompany&CIK={cik}&type=D"
                                   f"&owner=include&count=10")
                            return cik, url
        except Exception:
            pass
        time.sleep(0.3)
    try:
        r = requests.get("https://www.sec.gov/cgi-bin/browse-edgar",
            params={"company": name, "action": "getcompany",
                    "type": "D", "output": "atom"},
            headers=EFTS_HEADS, timeout=15)
        for co, cik in re.findall(
                r"<company-name>(.*?)</company-name>.*?<CIK>(.*?)</CIK>",
                r.text, re.S)[:3]:
            if name.lower() in co.lower():
                cik = cik.strip().zfill(10)
                url = (f"https://www.sec.gov/cgi-bin/browse-edgar"
                       f"?action=getcompany&CIK={cik}&type=D"
                       f"&owner=include&count=10")
                return cik, url
    except Exception:
        pass
    return "", ""

# ─────────────────────────────────────────────────────────────────────────────
# DDG
# ─────────────────────────────────────────────────────────────────────────────
IGNORE_DOMAINS = {
    "crunchbase.com","linkedin.com","twitter.com","x.com","facebook.com",
    "instagram.com","wikipedia.org","pitchbook.com","techcrunch.com",
    "bloomberg.com","reuters.com","wsj.com","forbes.com","fortune.com",
    "businesswire.com","prnewswire.com","globenewswire.com","sec.gov",
    "angel.co","angellist.com","finsmes.com","venturebeat.com","axios.com",
    "dealroom.co","tracxn.com","owler.com","zoominfo.com","yahoo.com",
    "cnbc.com","marketwatch.com","inc.com","nytimes.com","latimes.com",
}

def is_valid_website(url: str) -> bool:
    try:
        d = urlparse(url).netloc.lower().lstrip("www.")
        return bool(d) and not any(ign in d for ign in IGNORE_DOMAINS)
    except:
        return False

def ddg_find_website(name: str) -> str:
    queries = [
        f'"{name}" official site',
        f'"{name}" venture capital',
        f"{name} investor",
    ]
    try:
        with DDGS() as ddgs:
            for q in queries:
                results = list(ddgs.text(q, max_results=5))
                time.sleep(1)
                first = name.lower().split()[0]
                for res in results:
                    url = res.get("href", "")
                    if is_valid_website(url) and \
                       first in (res.get("title","") + res.get("body","")).lower():
                        return url
                for res in results:
                    if is_valid_website(res.get("href", "")):
                        return res["href"]
    except Exception as e:
        log(f"    DDG error: {e}")
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# Airtable helpers
# ─────────────────────────────────────────────────────────────────────────────
def at_get_all(table: str, formula: str, fields: list[str]) -> list[dict]:
    records, offset = [], None
    while True:
        params = {"filterByFormula": formula, "pageSize": 100,
                  "fields[]": fields}
        if offset:
            params["offset"] = offset
        r = requests.get(f"https://api.airtable.com/v0/{BASE}/{table}",
            headers={"Authorization": "Bearer " + KEY},
            params=params, timeout=30)
        d = r.json()
        records.extend(d.get("records", []))
        offset = d.get("offset")
        if not offset:
            break
        time.sleep(0.2)
    return records

def at_get_one(table: str, rec_id: str, fields: list[str]) -> dict:
    r = requests.get(
        f"https://api.airtable.com/v0/{BASE}/{table}/{rec_id}",
        headers={"Authorization": "Bearer " + KEY},
        params={"fields[]": fields}, timeout=15)
    return r.json() if r.status_code == 200 else {}

def at_patch(table: str, rec_id: str, fields: dict) -> bool:
    r = requests.patch(
        f"https://api.airtable.com/v0/{BASE}/{table}/{rec_id}",
        headers=AT_HEADS, json={"fields": fields}, timeout=15)
    return r.status_code == 200

def lookup_investor(name: str) -> dict | None:
    """Exact-match lookup of a LiveInvestors record by name."""
    safe = name.replace('"', '\\"')
    recs = at_get_all(LI_TABLE, f'{{name}}="{safe}"',
                      ["name", "website", "investor_type"])
    for rec in recs:
        if rec["fields"].get("name","").strip().lower() == name.strip().lower():
            return rec
    return None

def create_investor(name: str, event_rec_id: str) -> str:
    """Create a new LiveInvestors record. Returns record ID."""
    r = requests.post(
        f"https://api.airtable.com/v0/{BASE}/LiveInvestors",
        headers=AT_HEADS,
        json={"fields": {"name": name, "New": True,
                         "LiveEvents 2": [event_rec_id]}},
        timeout=15)
    return r.json().get("id", "")

# ─────────────────────────────────────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────────────────────────────────────
def prompt_verify_investors(article_text: str, company: str,
                             title: str, summary: str) -> str:
    clean_summary = re.sub(r"<[^>]+>", " ", summary)
    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()
    return (
        f"This article was ingested as a funding round. Verify whether that is correct.\n\n"
        f"Company: {company}\n"
        f"Title: {title}\n"
        f"Summary: {clean_summary[:600]}\n\n"
        f"Full article content:\n---\n{article_text[:3500]}\n---\n\n"
        "Return JSON only (no fences):\n"
        '{"investors": [], "is_funding_round": true}\n\n'
        "— investors: names of EXTERNAL investors (VCs, angels, funds, banks, "
        "strategic investors) who provided capital TO this company in this round. "
        "Empty array if none are mentioned.\n"
        "— is_funding_round: true ONLY if outside parties provided capital to the "
        "company. Set FALSE if the company is deploying its own capital (renovations, "
        "internal expansion, capex), announcing growth, launching products, or if "
        "this is general industry news. The word 'investment' used to describe a "
        "company spending its own money does NOT make it a funding round.\n"
        "Rules: investor names must be plain names only; no titles or amounts"
    )


def prompt_lead_investor(investors: list[str], company: str,
                         title: str, summary: str) -> str:
    clean_summary = re.sub(r"<[^>]+>", " ", summary)
    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()
    return (
        f"Funding round for: {company}\n"
        f"Title: {title}\n"
        f"Summary: {clean_summary[:800]}\n"
        f"All investors: {', '.join(investors)}\n\n"
        "Which investor LED this round? "
        "Return JSON only (no fences):\n"
        '{"lead_investor": "Name"}\n\n'
        "Return {\"lead_investor\": null} if the lead cannot be determined."
    )

def prompt_target_company(title: str, summary: str) -> str:
    clean_summary = re.sub(r"<[^>]+>", " ", summary)
    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()
    return (
        f"Title: {title}\n"
        f"Summary: {clean_summary[:800]}\n\n"
        "This is an M&A transaction. "
        "What is the name of the TARGET company being acquired?\n"
        "Return JSON only (no fences):\n"
        '{"target_company": "Name"}\n\n'
        "Return {\"target_company\": null} if not determinable."
    )

def prompt_enrich_investor(name: str, content: str) -> str:
    return (
        f"Extract structured data about this investor.\n"
        f"Investor name: {name}\n\n"
        f"Content:\n---\n{content[:5000]}\n---\n\n"
        "Return ONLY valid JSON (no fences):\n"
        '{"website":null,"aliases":null,"contact_email":null,'
        '"primary_contact":null,"geo_focus":null,'
        '"sector_focus":null,"investor_type":null}\n\n'
        "Rules:\n"
        "- website: firm/personal homepage only (not news, directory, sec.gov)\n"
        "- aliases: other known names, newline-separated\n"
        "- contact_email: real email with @ only, no image filenames\n"
        "- primary_contact: first + last name only, no titles\n"
        "- geo_focus: city + state/country e.g. 'Austin, TX'\n"
        "- sector_focus: comma-separated e.g. 'Consumer, HealthTech'\n"
        "- investor_type: VC / Individual / Corporate / Government / Accelerator\n"
        "- Return null for any field you are not confident about\n"
        "- All values must be plain strings, not arrays or objects"
    )

# ─────────────────────────────────────────────────────────────────────────────
# OpenAI Batch API
# ─────────────────────────────────────────────────────────────────────────────
def batch_line(custom_id: str, prompt: str, max_tokens: int = 400) -> dict:
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
    }

def submit_batch(tasks: list[dict]) -> str:
    tmp = Path(tempfile.mktemp(suffix=".jsonl"))
    with open(tmp, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")
    with open(tmp, "rb") as f:
        file_obj = oai.files.create(file=f, purpose="batch")
    tmp.unlink(missing_ok=True)
    batch = oai.batches.create(
        input_file_id=file_obj.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    log(f"  Batch ID: {batch.id}  ({len(tasks)} tasks)")
    return batch.id

def poll_batch(batch_id: str, interval: int = 15, timeout: int = 900) -> dict[str, dict]:
    """Poll until done. Returns {custom_id: parsed_result_dict}."""
    elapsed = 0
    while elapsed < timeout:
        b = oai.batches.retrieve(batch_id)
        done  = b.request_counts.completed if b.request_counts else "?"
        total = b.request_counts.total     if b.request_counts else "?"
        log(f"  [{elapsed:>4}s] status={b.status}  {done}/{total} complete")
        if b.status in ("completed", "failed", "cancelled", "expired"):
            if b.status != "completed":
                log(f"  Batch ended with status: {b.status}")
                return {}
            break
        time.sleep(interval)
        elapsed += interval

    content = oai.files.content(b.output_file_id).text
    results: dict[str, dict] = {}
    for line in content.splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        cid   = entry.get("custom_id", "")
        try:
            raw = entry["response"]["body"]["choices"][0]["message"]["content"].strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            results[cid] = json.loads(raw)
        except Exception as e:
            log(f"  Parse error [{cid}]: {e}")
            results[cid] = {}
    log(f"  Parsed {len(results)} results")
    return results

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log("=" * 70)
    log("process_new_records.py")
    log("=" * 70)

    # ── PHASE 1: GATHER ───────────────────────────────────────────────────────

    log("\n[1] Fetching new LiveEvents (New=True)...")
    new_events = at_get_all(LE_TABLE, "{New}=1", [
        "event_id", "event_type", "company", "investors", "lead_investor",
        "target_company", "source_link", "raw_title", "raw_summary",
        "event_date", "Investor Link",
    ])
    log(f"    {len(new_events)} new events")
    if not new_events:
        log("Nothing to process.")
        return

    batch_tasks: list[dict]  = []
    task_meta:   dict        = {}   # custom_id → context dict

    # investor name → {rec_id, edgar_url, content, event_rec_id, company, event_date}
    new_investor_data: dict  = {}

    log(f"\n[2] Pre-AI processing...")

    for ev in new_events:
        ev_id    = ev["id"]
        f        = ev["fields"]
        ev_type  = f.get("event_type", "")
        company  = strip_md(f.get("company", ""))
        raw_inv  = f.get("investors", "").strip()
        source   = f.get("source_link", "").strip()
        title    = f.get("raw_title", "")
        summary  = f.get("raw_summary", "")

        log(f"\n  ── {f.get('event_id','?')} | {company} | {ev_type} ──")

        # ── STEP: Verify investors field is populated (funding_round only) ──
        # If investors is empty, re-fetch the source article to see if the
        # content was there and just missed during ingestion.
        investors = parse_investor_names(raw_inv)

        if ev_type == "funding_round" and not investors:
            log("    investors empty — verifying against source article...")
            article_text = playwright_fetch(source) if source else ""
            if article_text:
                cid = f"verify_investors|{ev_id}"
                batch_tasks.append(batch_line(
                    cid,
                    prompt_verify_investors(article_text, company, title, summary),
                    max_tokens=200,
                ))
                task_meta[cid] = {"ev_id": ev_id, "company": company,
                                  "ev_type": ev_type, "title": title,
                                  "summary": summary,
                                  "article_text": article_text}
                log(f"    → batch task added: {cid}")
            else:
                # No article content at all — mark field as processed
                at_patch(LE_TABLE, ev_id, {"investors": "N/A"})
                log("    no article content — investors set to N/A")
            # Investor linking for this event deferred to post-batch pass
            continue

        # ── STEP: Format investors field ─────────────────────────────────────
        if raw_inv and "," in raw_inv:
            formatted = comma_to_linefeed(raw_inv)
            if formatted != raw_inv:
                at_patch(LE_TABLE, ev_id, {"investors": formatted})
                raw_inv   = formatted
                investors = parse_investor_names(raw_inv)
                log(f"    investors formatted ({len(investors)} names)")

        log(f"    investors: {investors}")

        # ── STEP: Single investor → lead_investor shortcut (no AI) ───────────
        if ev_type == "funding_round" and len(investors) == 1 \
                and not f.get("lead_investor"):
            at_patch(LE_TABLE, ev_id, {"lead_investor": investors[0]})
            log(f"    lead_investor set (single): {investors[0]}")

        # ── STEP: Lead investor batch task (2+ investors) ────────────────────
        elif ev_type == "funding_round" and len(investors) > 1 \
                and not f.get("lead_investor"):
            cid = f"lead_investor|{ev_id}"
            batch_tasks.append(batch_line(
                cid,
                prompt_lead_investor(investors, company, title, summary),
                max_tokens=80,
            ))
            task_meta[cid] = {"ev_id": ev_id}
            log(f"    → batch task added: {cid}")

        # ── STEP: Target company batch task ──────────────────────────────────
        if ev_type == "m_and_a_transaction" and not f.get("target_company"):
            cid = f"target_company|{ev_id}"
            batch_tasks.append(batch_line(
                cid,
                prompt_target_company(title, summary),
                max_tokens=80,
            ))
            task_meta[cid] = {"ev_id": ev_id}
            log(f"    → batch task added: {cid}")

        # ── STEP: Create missing LiveInvestors + gather enrichment data ───────
        for inv_name in investors:
            existing = lookup_investor(inv_name)
            time.sleep(0.2)
            if existing:
                log(f"    investor exists: {inv_name}")
                continue

            if inv_name in new_investor_data:
                # Already created for a prior event in this run — just link
                log(f"    investor already created this run: {inv_name}")
                continue

            log(f"    new investor: {inv_name} — creating...")
            rec_id = create_investor(inv_name, ev_id)
            if not rec_id:
                log(f"    ERROR: failed to create investor {inv_name}")
                continue
            log(f"    created: {rec_id}")

            # EDGAR
            log(f"    EDGAR: {inv_name}")
            cik, edgar_url = edgar_search(inv_name)
            log(f"    EDGAR result: {cik or 'no match'}")
            time.sleep(0.3)

            # DDG
            log(f"    DDG: {inv_name}")
            website = ddg_find_website(inv_name)
            log(f"    website: {website or 'not found'}")

            # Playwright scrape
            content = ""
            if website:
                log(f"    scraping: {website}")
                content = playwright_fetch(website)
                log(f"    content: {len(content)} chars")
                time.sleep(1)

            new_investor_data[inv_name] = {
                "rec_id":       rec_id,
                "edgar_url":    edgar_url,
                "content":      content,
                "event_rec_id": ev_id,
                "company":      company,
                "event_date":   f.get("event_date", ""),
            }

            if content:
                cid = f"enrich_investor|{rec_id}"
                batch_tasks.append(batch_line(
                    cid,
                    prompt_enrich_investor(inv_name, content),
                    max_tokens=400,
                ))
                task_meta[cid] = {
                    "rec_id":       rec_id,
                    "inv_name":     inv_name,
                    "edgar_url":    edgar_url,
                    "event_rec_id": ev_id,
                    "company":      company,
                    "event_date":   f.get("event_date", ""),
                }
                log(f"    → batch task added: {cid}")
            else:
                # No content — set EDGAR URL only
                if edgar_url:
                    at_patch(LI_TABLE, rec_id, {"website": edgar_url})
                    log(f"    EDGAR URL set directly (no site content)")

    # ── PHASE 2: ONE OpenAI BATCH CALL ───────────────────────────────────────

    results: dict[str, dict] = {}

    if not batch_tasks:
        log("\n[3] No AI tasks — skipping batch")
    else:
        log(f"\n[3] Submitting OpenAI batch ({len(batch_tasks)} tasks)...")
        batch_id = submit_batch(batch_tasks)
        log("    Polling for completion (15s intervals, 15min max)...")
        results = poll_batch(batch_id)

    # ── PHASE 3: APPLY RESULTS ────────────────────────────────────────────────

    log("\n[4] Applying batch results...")

    # Events that received investors from verify step — need investor linking pass
    events_got_investors: list[str] = []

    for cid, result in results.items():
        if not result:
            log(f"  {cid}: empty result")
            continue

        task_type = cid.split("|")[0]
        meta      = task_meta.get(cid, {})

        # ── verify_investors ─────────────────────────────────────────────────
        if task_type == "verify_investors":
            inv_list = result.get("investors") or []
            if not isinstance(inv_list, list):
                inv_list = []
            inv_list = [str(i).strip() for i in inv_list if str(i).strip()]

            is_funding = result.get("is_funding_round", True)

            # Reclassify if AI says this is not actually a funding round
            if not is_funding:
                at_patch(LE_TABLE, meta["ev_id"], {
                    "event_type":    "consumer_industry_news",
                    "investors":     "N/A",
                    "lead_investor": "N/A",
                    "NLCat":         "CB:N",
                })
                log(f"  verify_investors → {meta['ev_id']}: "
                    f"reclassified to consumer_industry_news  NLCat=CB:N")

            elif inv_list:
                formatted = "\n".join(inv_list)
                at_patch(LE_TABLE, meta["ev_id"], {"investors": formatted})
                log(f"  verify_investors → {meta['ev_id']}: {inv_list}")
                events_got_investors.append(meta["ev_id"])

                # Single investor → lead shortcut (post-verify)
                if len(inv_list) == 1:
                    at_patch(LE_TABLE, meta["ev_id"], {"lead_investor": inv_list[0]})
                    log(f"    lead_investor set (single, post-verify): {inv_list[0]}")
                else:
                    log(f"    lead_investor deferred to next run")

                # Create missing LiveInvestors as New=True — enriched next run
                for inv_name in inv_list:
                    if not lookup_investor(inv_name):
                        new_id = create_investor(inv_name, meta["ev_id"])
                        log(f"    created investor (New=True, enrich next run): "
                            f"{inv_name} → {new_id}")
                        time.sleep(0.2)
            else:
                # Confirmed funding round but no investors mentioned in article
                at_patch(LE_TABLE, meta["ev_id"], {"investors": "N/A"})
                log(f"  verify_investors → {meta['ev_id']}: "
                    f"funding round confirmed, no investors in article — set N/A")

        # ── lead_investor ────────────────────────────────────────────────────
        elif task_type == "lead_investor":
            lead = result.get("lead_investor")
            if lead:
                at_patch(LE_TABLE, meta["ev_id"], {"lead_investor": lead})
                log(f"  lead_investor → {meta['ev_id']}: {lead}")
            else:
                at_patch(LE_TABLE, meta["ev_id"], {"lead_investor": "N/A"})
                log(f"  lead_investor → {meta['ev_id']}: not determinable — set N/A")

        # ── target_company ───────────────────────────────────────────────────
        elif task_type == "target_company":
            target = result.get("target_company")
            if target:
                at_patch(LE_TABLE, meta["ev_id"], {"target_company": target})
                log(f"  target_company → {meta['ev_id']}: {target}")
            else:
                at_patch(LE_TABLE, meta["ev_id"], {"target_company": "N/A"})
                log(f"  target_company → {meta['ev_id']}: not determinable — set N/A")

        # ── enrich_investor ──────────────────────────────────────────────────
        elif task_type == "enrich_investor":
            rec_id   = meta["rec_id"]
            inv_name = meta.get("inv_name", rec_id)
            fields: dict = {}

            for k, v in result.items():
                if not v:
                    continue
                if isinstance(v, list):
                    v = ", ".join(str(i) for i in v)
                if isinstance(v, dict):
                    v = v.get("name") or str(v)
                fields[k] = v

            # Validate investor_type
            if fields.get("investor_type") not in VALID_TYPES | {None}:
                fields.pop("investor_type", None)

            # Validate email
            email = fields.get("contact_email", "")
            if email and ("@" not in email or
                          re.search(r"\.(png|jpg|gif|svg|webp)", email, re.I)):
                fields.pop("contact_email", None)

            # EDGAR fallback website
            if not fields.get("website") and meta.get("edgar_url"):
                fields["website"] = meta["edgar_url"]

            # Enforce one-per-line on multiline fields
            for mf in ("aliases", "portfolio_companies"):
                if fields.get(mf):
                    fields[mf] = comma_to_linefeed(fields[mf])

            # Event context fields
            if meta.get("company") and not fields.get("portfolio_companies"):
                fields["portfolio_companies"] = meta["company"]
            if meta.get("event_date"):
                fields["last_deal_date"] = meta["event_date"]
            if "deal_count" not in fields:
                fields["deal_count"] = 1

            # Event backlink
            if meta.get("event_rec_id") and meta.get("company"):
                fields["Event"] = (
                    f"[{meta['company']}](https://airtable.com/{BASE}"
                    f"/{LE_TABLE}/{meta['event_rec_id']})"
                )

            ok = at_patch(LI_TABLE, rec_id, fields)
            log(f"  enrich_investor → {inv_name}: "
                f"{'OK' if ok else 'FAIL'}  {list(fields.keys())}")

    # ── Step: Set Investor Link + Linked Investors on new events ─────────────
    log("\n[5] Setting Investor Link + Linked Investors fields...")

    # All new events plus any that got investors from verify step
    all_ev_ids = list({ev["id"] for ev in new_events} | set(events_got_investors))

    for ev_id in all_ev_ids:
        ev = at_get_one(LE_TABLE, ev_id,
                        ["investors", "Investor Link", "Linked Investors"])
        raw_inv  = (ev.get("fields") or {}).get("investors", "")
        investors = parse_investor_names(raw_inv)
        if not investors:
            continue

        linked_ids:    list[str] = []
        markdown_lines: list[str] = []

        for inv_name in investors:
            rec = lookup_investor(inv_name)
            time.sleep(0.15)
            if rec:
                linked_ids.append(rec["id"])
                markdown_lines.append(
                    f"[{inv_name}](https://airtable.com/{BASE}"
                    f"/{LI_TABLE}/{rec['id']})"
                )

        if linked_ids:
            ok = at_patch(LE_TABLE, ev_id, {
                "Investor Link":     linked_ids,
                "Linked Investors":  "\n".join(markdown_lines),
            })
            log(f"  {ev_id}: linked {len(linked_ids)} — {'OK' if ok else 'FAIL'}")

    # ── Step: Uncheck New on all processed events ─────────────────────────────
    log("\n[6] Clearing New flag on processed events...")
    for ev in new_events:
        # Only clear if this event is not waiting on a next-run enrichment pass.
        # Events that received investors from verify and have 2+ investors need
        # lead_investor on next run — leave New=True so they get re-processed.
        ev_id = ev["id"]
        if ev_id in events_got_investors:
            n_inv = len(parse_investor_names(
                at_get_one(LE_TABLE, ev_id, ["investors"])
                    .get("fields", {}).get("investors", "")
            ))
            if n_inv > 1 and ev["fields"].get("event_type") == "funding_round":
                log(f"  {ev['fields'].get('event_id','?')}: "
                    f"keeping New=True (lead_investor pending next run)")
                continue

        ok = at_patch(LE_TABLE, ev_id, {"New": False})
        log(f"  {ev['fields'].get('event_id','?')}: New=False — {'OK' if ok else 'FAIL'}")

    log(f"\nDone. Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
