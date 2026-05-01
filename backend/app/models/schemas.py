"""Pydantic schemas for Guardian AI's review pipeline."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------- Core enums ----------

class Severity(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"


CriticName = Literal[
    "fcc_enforcer",
    "brand_guardian",
    "persona_simulator",
    "technical_lead",
    "ops_strategist",
]

# Channel is kept as free-form str (normalized in intake) so we accept aliases
# like 'Landing Page', 'Press_Release', etc. coming from the eval samples.
Channel = str


# ---------- Violation ----------

class Violation(BaseModel):
    rule_id: str
    severity: Severity
    description: str
    span: str | None = Field(None, description="Excerpt of offending text")
    suggestion: str | None = Field(None, description="Recommended fix")
    source: str | None = None  # rule source citation


# ---------- Critic verdict ----------

class CriticVerdict(BaseModel):
    agent: CriticName
    verdict: Verdict
    summary: str
    violations: list[Violation] = Field(default_factory=list)
    iteration: int = 0


# ---------- Tool call trace (audit log) ----------

class ToolCallTrace(BaseModel):
    agent: str
    tool: str
    input: dict[str, Any]
    output: Any
    iteration: int
    ts: datetime = Field(default_factory=datetime.utcnow)


# ---------- Intake parsed metadata ----------

class IntakeMetadata(BaseModel):
    channel: Channel = "unknown"
    audience: str | None = None
    offer_id: str | None = None
    extracted_claims: list[str] = Field(default_factory=list)


# ---------- Review state (LangGraph state) ----------

class IterationRecord(BaseModel):
    iteration: int
    content: str
    verdicts: list[CriticVerdict] = Field(default_factory=list)
    revised_content: str | None = None
    changelog: str | None = None


class ReviewRequest(BaseModel):
    content: str
    channel: Channel | None = None
    audience: str | None = None
    offer_id: str | None = None


class ReviewResponse(BaseModel):
    final_content: str
    converged: bool
    iterations: list[IterationRecord]
    intake: IntakeMetadata
    audit_trail: list[ToolCallTrace] = Field(default_factory=list)
