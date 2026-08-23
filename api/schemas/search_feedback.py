"""Schemas for relevance feedback."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Constrained rather than free text. These values are read back a year later by whoever
# builds the ranker, and a column holding both "not_useful" and "notUseful" is a column
# nobody can group by.
Signal = Literal["click", "useful", "not_useful"]
SearchMode = Literal["hybrid", "lexical", "degraded"]


class SearchFeedbackCreate(BaseModel):
    """One statement about one result of one search."""

    query: str = Field(..., min_length=1, max_length=200)
    article_id: int = Field(..., ge=1)
    # 1-based, matching what the user saw. Position is half the signal: without it,
    # a click on the first result and a click on the ninth are indistinguishable.
    rank_position: int = Field(..., ge=1, le=100)
    signal: Signal
    # Which retrievers produced the result being judged. A click under `lexical` says
    # nothing about how a `hybrid` ranking performed.
    mode: SearchMode


class SearchFeedbackRecorded(BaseModel):
    recorded: bool
    query_fingerprint: str


class SearchFeedbackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    query_text: str
    query_fingerprint: str
    article_id: int
    rank_position: int
    signal: str
    mode: str
    created_at: datetime


class SearchFeedbackListResponse(BaseModel):
    items: list[SearchFeedbackItem]
    total: int
