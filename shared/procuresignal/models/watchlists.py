"""Organization-scoped supplier watchlists."""

from typing import Optional

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Watchlist(BaseModel):
    """A named set of suppliers an organization is watching together.

    Scoped to the organization rather than the user. A procurement team watches a
    supplier collectively, and per-user lists fragment exactly the thing they are
    trying to share — as well as meaning a departing colleague takes the list with them.
    """

    __tablename__ = "watchlists"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Kept for provenance and nulled rather than cascaded, so a list survives the
    # person who made it leaving.
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        # Per organization, not global: "Tier 1" is what everybody calls it, and one
        # team having two lists by that name means nobody can tell which one alerts.
        UniqueConstraint("organization_id", "normalized_name", name="uq_watchlist_org_name"),
        Index("idx_watchlist_organization", "organization_id"),
    )


class WatchlistEntry(BaseModel):
    """One supplier on one watchlist.

    References the canonical supplier. A free-text entry would reinherit every miss the
    supplier registry exists to remove.
    """

    __tablename__ = "watchlist_entries"

    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    added_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        # Adding twice is a no-op rather than a duplicate row.
        UniqueConstraint("watchlist_id", "supplier_id", name="uq_watchlist_entry"),
        Index("idx_watchlist_entry_supplier", "supplier_id"),
    )
