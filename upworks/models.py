from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class ParsedJobEmail:
    imap_uid: str
    message_id: str
    timestamp_utc: str
    job_url: str
    job_description: str
    short_description: str
    subject: str


@dataclass(frozen=True)
class AIDecision:
    should_pursue: bool
    total_score: float
    skill_alignment: float
    budget_alignment: float
    scope_clarity: float
    strategic_value: float
    reason: str
    complexity: Literal["low", "medium", "high"]
    confidence: int
    job_url: str
    full_job_description: str


class AIDecisionPayload(BaseModel):
    should_pursue: bool
    total_score: float
    skill_alignment: float
    budget_alignment: float
    scope_clarity: float
    strategic_value: float
    reason: str = Field(min_length=1)
    complexity: Literal["low", "medium", "high"]
    confidence: int = Field(ge=0, le=100)
    job_url: str = Field(min_length=1)
    full_job_description: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", strict=True)
