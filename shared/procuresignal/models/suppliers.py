"""Supplier master data."""

from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Supplier(BaseModel):
    """One canonical legal entity."""

    __tablename__ = "suppliers"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # Keeps the legal form, so "Siemens AG" and "Siemens Energy AG" are separate rows.
    # The legal-form-stripped spelling lives in supplier_aliases instead.
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    lei: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (Index("idx_suppliers_normalized", "normalized_name"),)


class SupplierAlias(BaseModel):
    """Every spelling that resolves to a supplier, including its own canonical form.

    `normalized_alias` is unique across the whole table. Two suppliers claiming one
    alias is a question only a person can answer, so it surfaces as a constraint
    violation at registration rather than resolving to whichever row was found first.
    """

    __tablename__ = "supplier_aliases"

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    # "canonical", "derived" (legal-form variant), "manual", or "lei".
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)

    __table_args__ = (
        Index("idx_alias_normalized", "normalized_alias"),
        Index("idx_alias_supplier", "supplier_id"),
    )


class ArticleSupplierMention(BaseModel):
    """A supplier named by an article.

    `supplier_id` is null when the name did not resolve. The mention is still stored:
    it is the evidence telling an operator which alias is missing, and dropping it
    would make registry coverage unmeasurable.
    """

    __tablename__ = "article_supplier_mentions"

    processed_article_id: Mapped[int] = mapped_column(nullable=False)
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    surface_form: Mapped[str] = mapped_column(String(300), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    __table_args__ = (
        # Makes re-running enrichment over an article a no-op rather than a duplicate.
        UniqueConstraint("processed_article_id", "surface_form", name="uq_mention_article_surface"),
        Index("idx_mention_supplier", "supplier_id"),
        Index("idx_mention_article", "processed_article_id"),
    )
