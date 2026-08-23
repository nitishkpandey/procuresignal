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
