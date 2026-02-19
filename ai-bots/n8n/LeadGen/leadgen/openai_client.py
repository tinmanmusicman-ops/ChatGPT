from __future__ import annotations

from typing import Any

import requests

from .errors import LeadGenError
from .parser import extract_output_text, extract_website_from_text


class OpenAIClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _post_responses(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/responses"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if response.status_code >= 400:
            raise LeadGenError("E06_OPENAI_HTTP_ERROR", f"OpenAI HTTP {response.status_code}: {response.text[:500]}")
        return response.json()

    def discover_website(self, company: str, industry: str, country: str) -> str:
        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": "Return only the official company website URL. If unknown return UNKNOWN."},
                {"role": "user", "content": f"Company: {company}\nIndustry: {industry}\nCountry: {country}"},
            ],
            "max_output_tokens": 80,
        }
        result = self._post_responses(body)
        text = extract_output_text(result)
        return extract_website_from_text(text)

    def evaluate(self, prompt_system: str, prompt_user: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": f"{prompt_system} Use only provided evidence."},
                {"role": "user", "content": prompt_user},
            ],
            "max_output_tokens": 900,
        }
        return self._post_responses(body)
