"""Watchlist request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class WatchedSupplier(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    canonical_name: str
    country: Optional[str] = None


class WatchlistSummary(BaseModel):
    public_id: str
    name: str
    supplier_count: int
    created_at: Optional[datetime] = None


class WatchlistDetail(BaseModel):
    public_id: str
    name: str
    # Named, not just identified. A list of opaque ids is not something a buyer can
    # check against what they meant to watch.
    suppliers: list[WatchedSupplier]
    created_at: Optional[datetime] = None


class WatchlistListResponse(BaseModel):
    items: list[WatchlistSummary]
    total_count: int
