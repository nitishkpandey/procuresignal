"""Models for Phase 4: signals and related tables."""

from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    article_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(20))
    impact_areas: Mapped[list] = mapped_column(ARRAY(String))
    raw_signal: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default=func.now(), onupdate=func.now()
    )


class SignalMetadata(Base):
    __tablename__ = "signal_metadata"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    signal_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())


class SignalSupplyChainImpact(Base):
    __tablename__ = "signal_supply_chain_impact"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    signal_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    affected_entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    relationship_type: Mapped[str] = mapped_column(String(100))
    impact_score: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, server_default=func.now())
