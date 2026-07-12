"""Risk event API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskEventStatus = Literal["new", "reviewed", "dismissed"]


class RiskEventItem(BaseModel):
    """A procurement risk event returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    processed_article_id: int
    risk_type: str
    severity: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    affected_suppliers: list[str] = Field(default_factory=list)
    affected_locations: list[str] = Field(default_factory=list)
    affected_categories: list[str] = Field(default_factory=list)
    evidence_snippet: str
    recommendation: str
    source_name: str
    source_url: str | None = None
    published_at: datetime
    status: RiskEventStatus
    rank_score: float = Field(..., ge=0.0, le=1.0)


class RiskEventResponse(BaseModel):
    """Paged risk events for one user."""

    user_id: str
    events: list[RiskEventItem]
    total_count: int = Field(..., ge=0)
    generated_at: datetime


class RiskEventStatusUpdate(BaseModel):
    """Requested review status for a risk event."""

    status: RiskEventStatus
