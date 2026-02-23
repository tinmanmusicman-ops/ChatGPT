from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from models import AIDecision, AIDecisionPayload, ParsedJobEmail


class AIError(RuntimeError):
    pass


def load_prompt_template(prompt_path: Path) -> str:
    template = prompt_path.read_text(encoding="utf-8").strip()
    if "{job_url}" not in template or "{job_description}" not in template:
        raise AIError("Prompt template must include {job_url} and {job_description} placeholders")
    return template


def evaluate_job(
    client: OpenAI,
    prompt_template: str,
    model: str,
    temperature: float,
    timeout_seconds: int,
    max_tokens: int,
    job_email: ParsedJobEmail,
) -> AIDecision:
    prompt = (
        prompt_template.replace("{job_url}", job_email.job_url).replace(
            "{job_description}", job_email.job_description
        )
    )

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "upwork_eval",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "should_pursue": {"type": "boolean"},
                    "total_score": {"type": "number"},
                    "skill_alignment": {"type": "number"},
                    "budget_alignment": {"type": "number"},
                    "scope_clarity": {"type": "number"},
                    "strategic_value": {"type": "number"},
                    "reason": {"type": "string"},
                    "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "job_url": {"type": "string"},
                    "full_job_description": {"type": "string"},
                },
                "required": [
                    "should_pursue",
                    "total_score",
                    "skill_alignment",
                    "budget_alignment",
                    "scope_clarity",
                    "strategic_value",
                    "reason",
                    "complexity",
                    "confidence",
                    "job_url",
                    "full_job_description",
                ],
            },
        },
    }

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
            response_format=response_format,
            messages=[
                {"role": "system", "content": "You evaluate freelance jobs. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise AIError(f"OpenAI request failed ({type(exc).__name__}: {exc})") from exc

    if not response.choices:
        raise AIError("OpenAI returned no choices")
    message = response.choices[0].message
    content = (message.content or "").strip() if message else ""
    if not content:
        raise AIError("OpenAI returned empty content")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIError(f"Invalid AI JSON: {exc}") from exc

    try:
        parsed = AIDecisionPayload.model_validate(payload)
    except ValidationError as exc:
        raise AIError(f"AI JSON schema validation failed: {exc}") from exc

    return AIDecision(
        should_pursue=parsed.should_pursue,
        total_score=parsed.total_score,
        skill_alignment=parsed.skill_alignment,
        budget_alignment=parsed.budget_alignment,
        scope_clarity=parsed.scope_clarity,
        strategic_value=parsed.strategic_value,
        reason=parsed.reason.strip(),
        complexity=parsed.complexity,
        confidence=parsed.confidence,
        job_url=parsed.job_url.strip(),
        full_job_description=parsed.full_job_description.strip(),
    )
