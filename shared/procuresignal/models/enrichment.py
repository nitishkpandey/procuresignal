"""Persistent enrichment cache model."""

from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class EnrichmentCacheEntry(BaseModel):
    """A validated enrichment reusable for one versioned cache identity."""

    __tablename__ = "enrichment_cache"

    content_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    original_method: Mapped[str] = mapped_column(String(20), nullable=False)
    hit_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "content_fingerprint",
            "policy_version",
            "taxonomy_version",
            name="uq_enrichment_cache_identity",
        ),
        CheckConstraint(
            "original_method IN ('deterministic', 'llm')",
            name="ck_enrichment_cache_original_method",
        ),
        Index("idx_enrichment_cache_fingerprint", "content_fingerprint"),
    )
