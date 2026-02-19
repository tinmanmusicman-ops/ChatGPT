#!/usr/bin/env python3
"""
Upwork visible-job capture for human-driven browser sessions.

Hotkey wrapper is expected to run this script in fail-fast mode.
Success output: two lines (json path, markdown path).
Failure output: single line prefixed with FAIL-FAST.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

try:
    from playwright.sync_api import sync_playwright
except Exception:
    print("FAIL-FAST: Playwright is not installed. Install with: pip install playwright")
    sys.exit(1)


DEFAULT_CDP_URL = "http://127.0.0.1:9222"
PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR
JOB_CARD_SELECTOR = "article.job-tile, .job-tile, [data-test*='job-tile'], [data-test*='jobTile']"


def fail(message: str, code: int = 1) -> int:
    print(f"FAIL-FAST: {message}")
    return code


def cdp_launch_help() -> str:
    return (
        f"Cannot attach to browser CDP at {DEFAULT_CDP_URL}. "
        "If you use Firefox, launch Microsoft Edge with --remote-debugging-port=9222. "
        "On Google Chrome 136+ default-profile CDP is blocked by design; use Edge default profile "
        "or a non-default Chrome --user-data-dir."
    )


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_low_signal_description(value: str) -> bool:
    text = clean_text(value).lower()
    if not text:
        return True
    if text in {"vague description", "clear description", "good description"}:
        return True
    if text.startswith("this client paid to post their job and reach freelancers like you"):
        return True
    return False


def looks_like_misplaced_description(value: str) -> bool:
    text = clean_text(value)
    if len(text) < 120:
        return False
    if text.count(" ") < 16:
        return False
    return bool(re.search(r"[.!?]", text))


def active_window_title() -> str:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return clean_text(buffer.value)


def choose_upwork_page(browser: Any, foreground_title: str):
    pages = []
    for context in browser.contexts:
        pages.extend(context.pages)
    if not pages:
        return None

    upwork_pages = [p for p in pages if "upwork.com" in (p.url or "").lower()]
    if not upwork_pages:
        return None

    title_lc = foreground_title.lower()
    if title_lc:
        for page in upwork_pages:
            try:
                page_title = clean_text(page.title()).lower()
            except Exception:
                page_title = ""
            if page_title and (page_title in title_lc or title_lc in page_title):
                return page

    for page in upwork_pages:
        url_lc = (page.url or "").lower()
        if (
            "/search/jobs" in url_lc
            or "/nx/search/jobs" in url_lc
            or "/nx/find-work/" in url_lc
        ):
            return page
    return upwork_pages[0]


def capture_visible_jobs(page: Any) -> dict[str, Any]:
    page.wait_for_load_state("domcontentloaded", timeout=10000)
    return page.evaluate(
        """
        () => {
          const loginSelectors = [
            'a[href*="/ab/account-security/login"]',
            'a[href*="/nx/signup/"]',
            'button[data-test="UpLink Login"]',
            'a[data-test="UpLink Login"]'
          ];
          const userSelectors = [
            'button[data-test*="nav-user-dropdown"]',
            '[data-test*="user-menu"]',
            'img[alt*="Profile"]',
            'img[alt*="profile"]'
          ];

          const hasLoginUi = loginSelectors.some((sel) => !!document.querySelector(sel));
          const hasUserUi = userSelectors.some((sel) => !!document.querySelector(sel));
          const isLoggedInLikely = hasUserUi || !hasLoginUi;

          const seen = new Set();
          const jobs = [];

          const isRenderable = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (!style || style.display === "none" || style.visibility === "hidden") return false;
            const rect = el.getBoundingClientRect();
            if (!rect || rect.width <= 1 || rect.height <= 1) return false;
            return true;
          };

          const toAbs = (href) => {
            try {
              return new URL(href, window.location.href).toString();
            } catch (_) {
              return String(href || "").trim();
            }
          };

          const normalizeText = (value) =>
            String(value || "")
              .replace(/\\s+/g, " ")
              .trim();

          const isDescriptionNoise = (value) => {
            const text = normalizeText(value);
            if (!text) return true;
            if (text.length < 20) return true;
            if (/^vague description$/i.test(text)) return true;
            if (/^clear description$/i.test(text)) return true;
            if (/^good description$/i.test(text)) return true;
            if (/^this client paid to post their job and reach freelancers like you\\.?$/i.test(text)) return true;
            if (/^(skills?|skip skills|previous skills|next skills|update list)\\b/i.test(text)) return true;
            if (/^(proposals?|payment verified|rating is|spent)\\b/i.test(text)) return true;
            if (/^(hourly|fixed(?:-price)?|budget|posted)\\b/i.test(text)) return true;
            if (/^(less than|more than)\\b/i.test(text)) return true;
            return false;
          };

          const extractDescription = (card, cardLines, title) => {
            const titleNorm = normalizeText(title).toLowerCase();

            const candidateNodes = card.querySelectorAll(
              '[data-test="job-description-text"], [data-test*="job-description"], [data-test*="description"], [data-qa*="description"], p'
            );
            const nodeCandidates = [];
            for (const node of Array.from(candidateNodes)) {
              const text = normalizeText(node.textContent || "");
              if (!text) continue;
              if (text.toLowerCase() === titleNorm) continue;
              if (isDescriptionNoise(text)) continue;
              nodeCandidates.push(text);
            }
            if (nodeCandidates.length > 0) {
              nodeCandidates.sort((a, b) => b.length - a.length);
              return nodeCandidates[0];
            }

            const lineCandidates = [];
            for (const rawLine of cardLines) {
              const line = normalizeText(rawLine);
              if (!line) continue;
              if (line.toLowerCase() === titleNorm) continue;
              if (isDescriptionNoise(line)) continue;
              if (/^\\$/.test(line)) continue;
              if (/^https?:\\/\\//i.test(line)) continue;
              lineCandidates.push(line);
            }
            if (lineCandidates.length > 0) {
              return lineCandidates.slice(0, 3).join(" ");
            }

            return "";
          };

          const cardSelectors = [
            'section[data-ev-label="visible_job_tile_impression"]',
            '[data-test*="job-tile"]',
            '[data-test*="jobTile"]',
            '[data-ev-label*="job"]',
            '[data-qa*="job"]',
            '.job-tile',
            '.air3-card-section',
            '.up-card-section',
            'article'
          ];

          const cardCandidates = [];
          for (const sel of cardSelectors) {
            for (const el of Array.from(document.querySelectorAll(sel))) {
              if (!el || seen.has(el)) continue;
              seen.add(el);
              cardCandidates.push(el);
            }
          }

          // Fallback: derive cards from job links when direct card selectors miss.
          if (cardCandidates.length === 0) {
            const hrefLinks = Array.from(document.querySelectorAll('a[href*="/jobs/"], a[href*="/freelance-jobs/"]'));
            for (const link of hrefLinks) {
              const card = link.closest('[data-test*="job"], article, section, .air3-card-section, .up-card-section')
                || link.parentElement;
              if (!card || seen.has(card)) continue;
              seen.add(card);
              cardCandidates.push(card);
            }
          }

          for (const card of cardCandidates) {
            if (!isRenderable(card)) continue;

            const primaryTitleLinks = card.querySelectorAll('h2 a[href*="/jobs/"], h3 a[href*="/jobs/"]');
            // Skip non-job containers and parent wrappers that include multiple tiles.
            if (primaryTitleLinks.length === 0 || primaryTitleLinks.length > 1) continue;

            const link =
              card.querySelector('h2 a[href*="/jobs/"], h3 a[href*="/jobs/"], a[data-test*="job-title"], a[href*="/jobs/"]')
              || null;
            const titleNode = link || card.querySelector('h2 a, h3 a, a.up-n-link');
            const title = (titleNode ? titleNode.textContent : "").trim();
            if (!title) continue;
            const url = toAbs(
              (titleNode && titleNode.getAttribute("href"))
              || (link && link.getAttribute("href"))
              || ""
            );
            if (!/\\/jobs\\//i.test(url)) continue;

            const cardTextRaw = (card.innerText || "").replace(/\\r/g, "");
            const cardLines = cardTextRaw
              .split("\\n")
              .map((line) => line.trim())
              .filter(Boolean);
            const cardText = cardLines.join("\\n");

            let type = "";
            if (/hourly/i.test(cardText)) type = "hourly";
            else if (/fixed|fixed-price/i.test(cardText)) type = "fixed";

            let rate = "";
            let match =
              cardText.match(/\\$\\s?\\d[\\d,]*(?:\\.\\d+)?\\s*(?:-\\s*\\$\\s?\\d[\\d,]*(?:\\.\\d+)?)?\\s*\\/\\s*hr/i) ||
              cardText.match(/(?:Budget|Fixed-price|Hourly)\\s*[:\\-]?\\s*\\$[^\\n]+/i) ||
              cardText.match(/\\$\\s?\\d[\\d,]*(?:\\.\\d+)?(?:\\s*[Kk])?/);
            if (match) {
              rate = match[0].trim();
            }

            const description = extractDescription(card, cardLines, title);

            const tagNodes = Array.from(
              card.querySelectorAll('[data-test*="token"], .air3-token, .up-skill-badge, a[href*="/skills/"]')
            );
            const tags = [];
            for (const node of tagNodes) {
              const value = (node.textContent || "").trim();
              if (!value) continue;
              if (!tags.includes(value)) tags.push(value);
            }

            const postedNode = card.querySelector('[data-test*="posted"], time, small');
            let posted = (postedNode ? postedNode.textContent : "").trim();
            if (!posted) {
              const postedLine = cardLines.find((line) => /posted|hour|minute|day|week|month/i.test(line));
              posted = (postedLine || "").trim();
            }

            const companyNode = card.querySelector(
              '[data-test*="client-name"], [data-qa*="client-name"], .client-name'
            );
            let company = (companyNode ? companyNode.textContent : "").trim();
            if (!company) {
              const companyLine = cardLines.find((line) =>
                /(?:Inc\\.|LLC|Ltd|Corp|Company|Technologies|Solutions|Studio)/i.test(line)
              );
              company = (companyLine || "").trim();
            }

            jobs.push({
              title,
              company,
              rate,
              type,
              description,
              tags,
              posted,
              url
            });
          }

          const pageUrlObj = new URL(window.location.href);
          const urlPageRaw = pageUrlObj.searchParams.get("page");
          const urlPageNum = Number.parseInt(urlPageRaw || "1", 10);

          let currentPage = Number.isFinite(urlPageNum) && urlPageNum > 0 ? urlPageNum : 1;
          let totalPages = 1;

          const bodyText = (document.body && document.body.innerText) ? document.body.innerText : "";
          const pageOfMatch = bodyText.match(/Current\\s+page\\s+(\\d+)\\s+of\\s+(\\d+)/i);
          if (pageOfMatch) {
            const parsedCurrent = Number.parseInt(pageOfMatch[1], 10);
            const parsedTotal = Number.parseInt(pageOfMatch[2], 10);
            if (Number.isFinite(parsedCurrent) && parsedCurrent > 0) currentPage = parsedCurrent;
            if (Number.isFinite(parsedTotal) && parsedTotal > 0) totalPages = parsedTotal;
          }

          const pageLinkNums = Array.from(document.querySelectorAll('a[href*="page="]'))
            .map((a) => {
              try {
                const u = new URL(a.href, window.location.href);
                const n = Number.parseInt(u.searchParams.get("page") || "", 10);
                return Number.isFinite(n) && n > 0 ? n : null;
              } catch (_) {
                return null;
              }
            })
            .filter((n) => n !== null);
          if (pageLinkNums.length > 0) {
            totalPages = Math.max(totalPages, ...pageLinkNums);
          }

          const loadMoreButton = Array.from(document.querySelectorAll('button')).find((btn) => {
            const text = (btn.innerText || btn.textContent || "").trim();
            return /load more jobs|load more/i.test(text);
          });

          return {
            pageUrl: window.location.href,
            pageTitle: document.title || "",
            hasLoginUi,
            hasUserUi,
            isLoggedInLikely,
            currentPage,
            totalPages,
            hasLoadMoreButton: !!loadMoreButton,
            loadMoreDisabled: loadMoreButton ? !!loadMoreButton.disabled || loadMoreButton.getAttribute("aria-disabled") === "true" : null,
            jobs
          };
        }
        """
    )


def with_page_number(url: str, page_number: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if page_number <= 1:
        query.pop("page", None)
    else:
        query["page"] = [str(page_number)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def parse_max_pages() -> int | None:
    raw = os.environ.get("UPWORK_MAX_PAGES", "").strip()
    if raw == "":
        return None
    try:
        value = int(raw)
    except Exception:
        raise ValueError(f"UPWORK_MAX_PAGES must be an integer. Received: '{raw}'")
    if value < 1:
        raise ValueError(f"UPWORK_MAX_PAGES must be >= 1. Received: '{raw}'")
    return value


def wait_for_jobs_surface(page: Any, timeout_ms: int = 20000) -> bool:
    try:
        page.wait_for_selector(JOB_CARD_SELECTOR, timeout=timeout_ms, state="attached")
        return True
    except Exception:
        no_results = page.evaluate(
            """
            () => /no jobs|no results|try different filters/i.test((document.body && document.body.innerText) || "")
            """
        )
        if no_results:
            return False
        raise RuntimeError(
            f"Job cards did not load before timeout ({timeout_ms} ms). URL: {page.url}"
        )


def click_load_more(page: Any) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const btn = Array.from(document.querySelectorAll('button')).find((el) => {
                const text = (el.innerText || el.textContent || '').trim();
                return /load more jobs|load more/i.test(text);
              });
              if (!btn) return false;
              if (btn.disabled) return false;
              if (btn.getAttribute('aria-disabled') === 'true') return false;
              btn.click();
              return true;
            }
            """
        )
    )


def normalize_jobs(raw_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_jobs:
        title = clean_text(item.get("title"))
        url = clean_text(item.get("url"))
        key = f"{title}|{url}"
        if not title:
            continue
        if key in seen:
            continue
        seen.add(key)
        tags = [clean_text(tag) for tag in (item.get("tags") or []) if clean_text(tag)]
        company = clean_text(item.get("company"))
        description = clean_text(item.get("description"))

        if is_low_signal_description(description) and looks_like_misplaced_description(company):
            description = company
            company = ""

        normalized.append(
            {
                "title": title,
                "company": company,
                "rate": clean_text(item.get("rate")),
                "type": clean_text(item.get("type")),
                "description": description,
                "tags": tags,
                "posted": clean_text(item.get("posted")),
                "url": url,
            }
        )
    return normalized


def render_markdown(timestamp: str, jobs: list[dict[str, Any]]) -> str:
    lines = [f"## Upwork Capture - {timestamp}", ""]
    for job in jobs:
        lines.extend(
            [
                "### JOB",
                f"Title: {job['title']}",
                f"Company: {job['company']}",
                f"Rate: {job['rate']}",
                f"Type: {job['type']}",
                f"Posted: {job['posted']}",
                f"Tags: {', '.join(job['tags']) if job['tags'] else ''}",
                f"URL: {job['url']}",
                f"Description: {job['description']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    foreground_title = active_window_title()
    if "upwork" not in foreground_title.lower():
        return fail(
            f"Active window is not an Upwork tab. Foreground title: '{foreground_title or 'unknown'}'"
        )

    cdp_url = os.environ.get("UPWORK_CDP_URL", DEFAULT_CDP_URL).strip() or DEFAULT_CDP_URL
    try:
        max_pages = parse_max_pages()
    except ValueError as exc:
        return fail(str(exc))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=10000)
            except Exception:
                return fail(cdp_launch_help())

            page = choose_upwork_page(browser, foreground_title)
            if page is None:
                browser.close()
                return fail("Upwork tab not detected in attached browser session.")

            page_url = (page.url or "").lower()
            if "upwork.com" not in page_url:
                browser.close()
                return fail(f"Active captured tab is not Upwork. URL: {page.url}")
            if (
                "/search/jobs" not in page_url
                and "/nx/search/jobs" not in page_url
                and "/nx/find-work/" not in page_url
            ):
                browser.close()
                return fail(f"Upwork detected, but not on jobs search page. URL: {page.url}")

            first_page_url = with_page_number(page.url, 1)
            page.goto(first_page_url, wait_until="domcontentloaded", timeout=30000)
            jobs_surface_exists = wait_for_jobs_surface(page)
            payload = capture_visible_jobs(page)

            all_raw_jobs = list(payload.get("jobs") or [])
            if not payload.get("isLoggedInLikely") and not all_raw_jobs:
                browser.close()
                return fail("Upwork user session appears logged out.")
            if not jobs_surface_exists and not all_raw_jobs:
                browser.close()
                return fail(f"No jobs available on page 1. URL: {page.url}")

            current_page = int(payload.get("currentPage") or 1)
            total_pages = int(payload.get("totalPages") or 1)
            if current_page < 1 or total_pages < 1 or current_page > total_pages:
                browser.close()
                return fail(
                    f"Invalid pagination metadata. currentPage={current_page}, totalPages={total_pages}"
                )

            has_load_more = bool(payload.get("hasLoadMoreButton"))
            if total_pages > 1:
                last_page = total_pages
                if max_pages is not None:
                    last_page = min(total_pages, max_pages)

                for page_number in range(current_page + 1, last_page + 1):
                    page.goto(
                        with_page_number(first_page_url, page_number),
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    jobs_surface_exists = wait_for_jobs_surface(page)
                    page_payload = capture_visible_jobs(page)
                    page_jobs = list(page_payload.get("jobs") or [])
                    if not jobs_surface_exists and not page_jobs:
                        browser.close()
                        return fail(f"No jobs available on page {page_number}. URL: {page.url}")
                    if not page_jobs:
                        browser.close()
                        return fail(f"No jobs detected on page {page_number}. URL: {page.url}")
                    all_raw_jobs.extend(page_jobs)
            elif has_load_more:
                # Treat each successful click as one page-equivalent batch.
                load_round = 1
                while True:
                    if max_pages is not None and load_round >= max_pages:
                        break
                    before_unique = len(normalize_jobs(all_raw_jobs))
                    clicked = click_load_more(page)
                    if not clicked:
                        break
                    grew = False
                    page_payload = {}
                    # Give the UI time to append items; stop cleanly if nothing new arrives.
                    for _ in range(8):
                        page.wait_for_timeout(800)
                        jobs_surface_exists = wait_for_jobs_surface(page)
                        page_payload = capture_visible_jobs(page)
                        page_jobs = list(page_payload.get("jobs") or [])
                        if not jobs_surface_exists and not page_jobs:
                            continue
                        if page_jobs:
                            all_raw_jobs.extend(page_jobs)
                            after_unique = len(normalize_jobs(all_raw_jobs))
                            if after_unique > before_unique:
                                grew = True
                                break
                    if not grew:
                        break
                    load_round += 1
                    if not bool(page_payload.get("hasLoadMoreButton")):
                        break
                    if bool(page_payload.get("loadMoreDisabled")):
                        break
            browser.close()
    except Exception as exc:
        return fail(f"Capture pipeline crashed: {exc}")

    jobs = normalize_jobs(all_raw_jobs)
    if not jobs:
        return fail("No jobs extracted after pagination.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"upwork_capture_{timestamp}.json"
    md_path = OUTPUT_DIR / f"upwork_capture_{timestamp}.md"

    json_path.write_text(json.dumps(jobs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(timestamp, jobs), encoding="utf-8")

    # Output paths only.
    print(str(json_path))
    print(str(md_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
