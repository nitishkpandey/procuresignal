"""Schemas for subject requests."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SubjectExportResponse(BaseModel):
    """Everything held about one person, table by table.

    Machine-readable on purpose: Article 20 asks for a portable format, and this is what
    a lawyer forwards rather than what a person reads.
    """

    subject: dict[str, Any]
    generated_at: datetime
    # Included even where erasure will never remove them. Access and erasure are
    # different rights.
    tables: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class ErasureRequest(BaseModel):
    # Why the erasure happened, for the receipt. A record saying only that data was
    # deleted cannot be tied back to the request that asked for it.
    reason: str = Field(default="", max_length=500)


class ErasureReceiptResponse(BaseModel):
    """What was done, table by table.

    `retained` is what keeps this honest: it names the rows that survive and how many,
    rather than implying erasure was total when one table refuses.
    """

    subject_public_id: str
    erased_at: datetime
    reason: str
    deleted: dict[str, int] = Field(default_factory=dict)
    anonymised: dict[str, int] = Field(default_factory=dict)
    retained: dict[str, int] = Field(default_factory=dict)
