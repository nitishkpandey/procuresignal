"""Identity, tenancy, and session models."""

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Role(StrEnum):
    """Membership roles, declared strongest first so comparisons can rank them."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Organization(BaseModel):
    """A tenant. Users reach data through a membership in one."""

    __tablename__ = "organizations"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class User(BaseModel):
    """A person. `public_id` is the value domain tables store in their `user_id` column."""

    __tablename__ = "users"

    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    # Null for placeholder users created by the identity backfill; they cannot log in.
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bumping this invalidates every outstanding access token for the user.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("idx_users_email", "email"),)


class Membership(BaseModel):
    """Binds a user to an organization with a role."""

    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default=Role.MEMBER, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
        Index("idx_membership_user", "user_id"),
    )


class RefreshToken(BaseModel):
    """One issued refresh token, stored as a hash so a database leak yields no sessions."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Rotation family: presenting an already-rotated token revokes every member of its family.
    family_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("idx_refresh_user", "user_id"),
        Index("idx_refresh_family", "family_id"),
    )


class OrganizationInvitation(BaseModel):
    """An admin's offer to let one address join their organization.

    Registration no longer joins a tenant on the strength of a matching email domain,
    because nothing at that point proves the registrant owns the mailbox. An invitation
    is the evidence: somebody already inside the organization named this address.
    """

    __tablename__ = "organization_invitations"

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=Role.MEMBER, nullable=False)
    # Only the hash is stored, as with refresh tokens: a database leak must not yield
    # usable invitations into a customer's tenant.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_invitation_email", "email"),
        Index("idx_invitation_organization", "organization_id"),
    )
