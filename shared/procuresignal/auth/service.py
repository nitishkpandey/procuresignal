"""Registration, sign-in, and session lifecycle."""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import Membership, Organization, RefreshToken, Role, User

from .passwords import hash_password, verify_password
from .tokens import (
    AccessClaims,
    encode_access_token,
    hash_refresh_token,
    mint_refresh_token,
    refresh_token_expiry,
)

# Mailboxes here belong to individuals, not companies. Grouping by domain would otherwise
# drop every consumer-mailbox signup into one shared tenant, which is a data breach rather
# than a convenience.
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "outlook.com",
        "hotmail.com",
        "hotmail.co.uk",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "gmx.com",
        "gmx.de",
        "gmx.net",
        "web.de",
        "proton.me",
        "protonmail.com",
        "mail.com",
        "zoho.com",
        "yandex.com",
        "fastmail.com",
        "tutanota.com",
        "posteo.de",
    }
)


class EmailAlreadyRegisteredError(Exception):
    """Raised when an address already has an account."""


class InvalidCredentialsError(Exception):
    """Raised for every failed sign-in, whatever the underlying reason."""


@dataclass(frozen=True)
class IssuedSession:
    """What a successful sign-in hands back."""

    user: User
    organization: Organization
    role: Role
    access_token: str
    refresh_token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _domain(email: str) -> str:
    return email.rpartition("@")[2]


def _organization_name(domain: str) -> str:
    label = domain.rpartition(".")[0] or domain
    return label.replace("-", " ").replace(".", " ").title() or domain


async def _organization_for(session: AsyncSession, email: str) -> tuple[Organization, Role]:
    """Find or create the organization this address should join.

    A company domain groups colleagues together, and the first of them owns the tenant.
    A public mailbox provider always gets a fresh single-person organization.
    """

    domain = _domain(email)
    if domain and domain not in PUBLIC_EMAIL_DOMAINS:
        existing = (
            await session.execute(select(Organization).where(Organization.slug == domain))
        ).scalar_one_or_none()
        if existing is not None:
            return existing, Role.MEMBER

        organization = Organization(
            public_id=uuid4().hex, name=_organization_name(domain), slug=domain
        )
    else:
        public_id = uuid4().hex
        organization = Organization(
            public_id=public_id, name=email, slug=f"{public_id[:12]}.personal"
        )

    session.add(organization)
    await session.flush()
    return organization, Role.OWNER


async def _issue(
    session: AsyncSession,
    user: User,
    organization: Organization,
    role: Role,
    *,
    family_id: str | None = None,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> IssuedSession:
    plaintext, digest = mint_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            family_id=family_id or uuid4().hex,
            expires_at=refresh_token_expiry(),
            user_agent=user_agent[:300] if user_agent else None,
            client_ip=client_ip,
        )
    )
    access_token = encode_access_token(
        AccessClaims(
            subject=user.public_id,
            organization=organization.public_id,
            role=str(role),
            token_version=user.token_version,
            jti=uuid4().hex,
        )
    )
    return IssuedSession(
        user=user,
        organization=organization,
        role=role,
        access_token=access_token,
        refresh_token=plaintext,
    )


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> IssuedSession:
    """Create an account and sign it in.

    An address that already exists is refused rather than silently succeeding. Silent
    success is the anti-enumeration answer, but it needs a confirmation email to tell the
    genuine registrant what happened, and there is no mail transport yet. Until Phase 4
    adds one, a clear conflict beats a user who believes they have an account and cannot
    sign in.
    """

    address = normalize_email(email)
    existing = (
        await session.execute(select(User).where(User.email == address))
    ).scalar_one_or_none()
    if existing is not None:
        raise EmailAlreadyRegisteredError(address)

    organization, role = await _organization_for(session, address)
    user = User(
        public_id=uuid4().hex,
        email=address,
        password_hash=hash_password(password),
        full_name=full_name,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    session.add(Membership(user_id=user.id, organization_id=organization.id, role=role))
    await session.flush()

    return await _issue(
        session, user, organization, role, user_agent=user_agent, client_ip=client_ip
    )


async def authenticate(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> IssuedSession:
    """Sign in, or raise `InvalidCredentialsError` for any reason at all."""

    address = normalize_email(email)
    user = (await session.execute(select(User).where(User.email == address))).scalar_one_or_none()

    # Always verify, even with no user, so absent and wrong take the same time.
    if not verify_password(password, user.password_hash if user else None):
        raise InvalidCredentialsError()
    if user is None or not user.is_active:
        raise InvalidCredentialsError()

    row = (
        await session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.user_id == user.id)
            .order_by(Membership.id)
        )
    ).first()
    if row is None:
        raise InvalidCredentialsError()

    membership, organization = row
    user.last_login_at = datetime.utcnow()
    return await _issue(
        session,
        user,
        organization,
        Role(membership.role),
        user_agent=user_agent,
        client_ip=client_ip,
    )


async def rotate_refresh_token(
    session: AsyncSession,
    *,
    presented: str,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> IssuedSession:
    """Exchange a refresh token for a fresh pair.

    Presenting a token that was already rotated means it leaked: the legitimate client
    would be holding its replacement. Every token in that family is revoked, which signs
    the attacker and the victim out together rather than leaving the thief a live session.
    """

    digest = hash_refresh_token(presented)
    stored = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == digest))
    ).scalar_one_or_none()
    if stored is None:
        raise InvalidCredentialsError()

    now = datetime.utcnow()
    if stored.revoked_at is not None:
        await revoke_family(session, stored.family_id, now=now)
        raise InvalidCredentialsError()
    if stored.expires_at <= now:
        raise InvalidCredentialsError()

    user = (
        await session.execute(select(User).where(User.id == stored.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise InvalidCredentialsError()

    row = (
        await session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.user_id == user.id)
            .order_by(Membership.id)
        )
    ).first()
    if row is None:
        raise InvalidCredentialsError()

    stored.revoked_at = now
    membership, organization = row
    return await _issue(
        session,
        user,
        organization,
        Role(membership.role),
        family_id=stored.family_id,
        user_agent=user_agent,
        client_ip=client_ip,
    )


async def revoke_family(session: AsyncSession, family_id: str, *, now: datetime | None) -> None:
    """Revoke every unrevoked token descended from one sign-in."""

    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now or datetime.utcnow())
    )


async def revoke_token(session: AsyncSession, presented: str) -> bool:
    """Revoke one presented refresh token. Returns whether it existed and was live."""

    stored = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(presented))
        )
    ).scalar_one_or_none()
    if stored is None or stored.revoked_at is not None:
        return False

    stored.revoked_at = datetime.utcnow()
    return True


async def revoke_all_sessions(session: AsyncSession, user_id: int) -> None:
    """End every session for a user, including access tokens that have not expired.

    Bumping `token_version` is what reaches the access tokens: they are self-contained, so
    there is nothing to delete, and the per-request version check is what rejects them.
    """

    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.utcnow())
    )
    await session.execute(
        update(User).where(User.id == user_id).values(token_version=User.token_version + 1)
    )
