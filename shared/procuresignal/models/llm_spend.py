"""Durable LLM spend accounting."""

from datetime import date

from sqlalchemy import Date, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class LlmSpend(BaseModel):
    """One tenant's LLM usage for one day.

    Dated rows rather than a counter plus a scheduled reset: the reset is implicit in
    the date, so there is no job that can fail and leave a tenant capped forever.
    """

    __tablename__ = "llm_spend"

    # The organization's public id, or the shared bucket for work with no known tenant.
    tenant: Mapped[str] = mapped_column(String(64), nullable=False)
    spend_date: Mapped[date] = mapped_column(Date, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant", "spend_date", name="uq_llm_spend_tenant_day"),
        Index("idx_llm_spend_day", "spend_date"),
    )
