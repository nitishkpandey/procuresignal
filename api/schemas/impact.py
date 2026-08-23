"""Schemas for supplier impact scoring."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ImpactDriver(BaseModel):
    """One event and what it contributed to the score.

    Shipped with every score rather than behind a second request: a buyer defending a
    sourcing decision needs the evidence in the same breath as the number.
    """

    model_config = ConfigDict(from_attributes=True)

    event_key: str
    risk_type: str
    severity: str
    confidence: float
    published_at: datetime
    contribution: float
    evidence_snippet: str
    source_name: str


class SupplierImpactResponse(BaseModel):
    supplier_public_id: str
    supplier_name: str
    value: float = Field(..., ge=0.0, le=1.0)
    # none, low, elevated or severe. An active sanctions designation forces the top band
    # whatever the value says, so the two are not redundant.
    band: str
    drivers: list[ImpactDriver]


class ImpactListResponse(BaseModel):
    items: list[SupplierImpactResponse]
    total: int
