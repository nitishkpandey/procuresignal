"""Schemas for supplier analyses and the decisions made about them."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalysisRequest(BaseModel):
    supplier_public_id: str = Field(..., min_length=1, max_length=64)


class DecisionRequest(BaseModel):
    # Why somebody agreed or declined is the part that is useful a year later; the
    # status alone says a decision happened, not what it was based on.
    note: str = Field(default="", max_length=2000)


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    title: str
    rationale: str
    # Risk event keys that survived verification against what the tools actually
    # returned. A recommendation is never shown without them.
    evidence_event_keys: list[str]
    status: str
    decided_at: datetime | None = None
    decision_note: str | None = None


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    kind: str
    tool_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    supplier_public_id: str
    status: str
    model: str
    step_count: int
    prompt_tokens: int
    completion_tokens: int
    started_at: datetime
    finished_at: datetime | None = None
    failure_reason: str | None = None
    recommendation_count: int = 0


class AnalysisDetail(AnalysisSummary):
    steps: list[StepOut] = Field(default_factory=list)
    recommendations: list[RecommendationOut] = Field(default_factory=list)


class AnalysisListResponse(BaseModel):
    items: list[AnalysisSummary]
    total: int
