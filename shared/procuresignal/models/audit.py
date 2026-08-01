"""Append-only audit trail."""

from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class AuditLog(BaseModel):
    """One recorded action. Rows are inserted and never updated or deleted."""

    __tablename__ = "audit_log"

    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized so the trail still names the actor after the account is deleted.
    actor_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("idx_audit_org_created", "organization_id", "created_at"),
        Index("idx_audit_actor", "actor_user_id"),
        Index("idx_audit_action", "action"),
    )
