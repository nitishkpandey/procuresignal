"""Durable retrieval-run audit models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class NewsRetrievalRun(BaseModel):
    __tablename__ = "news_retrieval_runs"

    run_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    registry_version: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    fetched_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    inserted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    outcomes: Mapped[list["NewsRetrievalSourceOutcome"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    __table_args__ = (Index("idx_retrieval_run_status_lease", "status", "lease_expires_at"),)


class NewsRetrievalSourceOutcome(BaseModel):
    __tablename__ = "news_retrieval_source_outcomes"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("news_retrieval_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    fetched_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    inserted_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    duplicate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    within_run_duplicate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    database_duplicate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    response_bytes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    outcome_detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    run: Mapped[NewsRetrievalRun] = relationship(back_populates="outcomes")
    __table_args__ = (
        UniqueConstraint("run_id", "source_id", name="uq_retrieval_outcome_run_source"),
        Index("idx_retrieval_outcome_source_started", "source_id", "started_at"),
    )


class NewsRetrievalCircuit(BaseModel):
    __tablename__ = "news_retrieval_circuits"

    source_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    failure_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    open_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    probe_owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    probe_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
