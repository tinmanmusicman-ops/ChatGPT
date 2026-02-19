from __future__ import annotations

from typing import Any

import requests

from .errors import LeadGenError


class FirecrawlClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def scrape_markdown(self, website_url: str) -> str:
        if not website_url:
            raise LeadGenError("E04_WEBSITE_DISCOVERY_FAILED", "Missing website URL for scrape call")

        url = f"{self.base_url}/v1/scrape"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"url": website_url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=60,
        )
        if response.status_code >= 400:
            raise LeadGenError(
                "E05_FIRECRAWL_HTTP_ERROR",
                f"Firecrawl HTTP {response.status_code}: {response.text[:500]}",
            )

        data: dict[str, Any] = response.json()
        scraped = str(
            data.get("data", {}).get("markdown")
            or data.get("data", {}).get("content")
            or data.get("markdown")
            or data.get("content")
            or ""
        ).strip()
        if not scraped:
            raise LeadGenError("E05_FIRECRAWL_FAILED", "Firecrawl returned empty scrape content")
        return scraped
