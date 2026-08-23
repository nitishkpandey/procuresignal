"""Subject request endpoints.

Who may ask on whose behalf is the whole of this file. The right of access belongs to the
person, so no role is needed for their own data; an admin may ask for a colleague because
subject requests arrive by email to the company rather than through the product; and
nobody may ask about somebody in another organization.
"""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import (
    AuditLog,
    Base,
    ChatMessage,
    Membership,
    Organization,
    Role,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.main import app


@pytest.fixture()
def privacy_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        identities: dict[str, AuthenticatedUser] = {}
        async with maker() as session:
            for slug in ("acme", "globex"):
                organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
                session.add(organization)
                await session.flush()
                for role in (Role.ADMIN, Role.MEMBER):
                    user = User(
                        public_id=f"user-{slug}-{role.value}",
                        email=f"{role.value}@{slug}.example",
                        password_hash="argon2-secret",
                        is_active=True,
                    )
                    session.add(user)
                    await session.flush()
                    session.add(
                        Membership(organization_id=organization.id, user_id=user.id, role=role)
                    )
                    session.add(
                        ChatMessage(
                            user_id=user.public_id,
                            conversation_id=f"conv-{slug}-{role.value}",
                            role="user",
                            content=f"{slug} {role.value} asked something",
                        )
                    )
                    identities[f"{slug}-{role.value}"] = AuthenticatedUser(
                        id=user.id,
                        public_id=user.public_id,
                        email=user.email,
                        organization_id=organization.id,
                        organization_public_id=organization.public_id,
                        role=role,
                    )
            await session.commit()
        return maker, identities

    maker, identities = asyncio.run(prepare())
    caller = {"identity": identities["acme-admin"]}

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: caller["identity"]

    with TestClient(app) as http:
        yield http, caller, identities, maker

    app.dependency_overrides.clear()


def test_anyone_can_ask_for_their_own_data(privacy_env) -> None:
    """No role required. The right of access belongs to the person, not to their
    employer's administrator."""

    http, caller, identities, _maker = privacy_env
    caller["identity"] = identities["acme-member"]

    response = http.get("/api/privacy/me/export")

    assert response.status_code == 200
    body = response.json()
    assert body["subject"]["public_id"] == "user-acme-member"
    assert body["tables"]["chat_messages"][0]["content"] == "acme member asked something"


def test_an_export_never_carries_a_credential(privacy_env) -> None:
    http, _caller, _identities, _maker = privacy_env

    body = http.get("/api/privacy/me/export").text

    assert "argon2-secret" not in body


def test_an_admin_can_ask_on_behalf_of_a_colleague(privacy_env) -> None:
    """Subject requests arrive by email to the company far more often than through the
    product, and the person handling them is not the subject."""

    http, _caller, _identities, _maker = privacy_env

    response = http.get("/api/privacy/users/user-acme-member/export")

    assert response.status_code == 200
    assert response.json()["subject"]["public_id"] == "user-acme-member"


def test_a_member_cannot_ask_about_a_colleague(privacy_env) -> None:
    http, caller, identities, _maker = privacy_env
    caller["identity"] = identities["acme-member"]

    response = http.get("/api/privacy/users/user-acme-admin/export")

    assert response.status_code == 403


def test_another_organizations_person_is_a_404(privacy_env) -> None:
    """404 rather than 403: confirming an account exists is how a directory gets
    enumerated, and the identifier here is a fact about a person."""

    http, _caller, _identities, _maker = privacy_env

    response = http.get("/api/privacy/users/user-globex-member/export")

    assert response.status_code == 404


def test_an_unknown_person_is_a_404(privacy_env) -> None:
    http, _caller, _identities, _maker = privacy_env

    assert http.get("/api/privacy/users/nobody/export").status_code == 404


def test_a_disclosure_is_recorded(privacy_env) -> None:
    """What was disclosed, to whom, and when. The part a regulator asks for after the
    fact, and the reason an export endpoint is not simply a read."""

    http, _caller, identities, maker = privacy_env

    http.get("/api/privacy/users/user-acme-member/export")

    async def entries():
        async with maker() as session:
            rows = await session.execute(
                select(AuditLog).where(AuditLog.action == "privacy.subject_export")
            )
            return list(rows.scalars().all())

    logged = asyncio.run(entries())
    assert len(logged) == 1
    assert logged[0].actor_email == identities["acme-admin"].email
    assert logged[0].resource_id == "user-acme-member"
    assert logged[0].detail["on_behalf_of_another"] is True


def test_the_audit_record_counts_rows_rather_than_copying_them(privacy_env) -> None:
    """The log must show that a disclosure happened without becoming a second copy of
    the disclosure — which would put the same personal data somewhere erasure cannot
    reach."""

    http, _caller, _identities, maker = privacy_env

    http.get("/api/privacy/me/export")

    async def entry():
        async with maker() as session:
            rows = await session.execute(
                select(AuditLog).where(AuditLog.action == "privacy.subject_export")
            )
            return rows.scalars().one()

    logged = asyncio.run(entry())
    assert logged.detail["row_counts"]["chat_messages"] == 1
    assert "asked something" not in str(logged.detail)


def test_the_export_reports_when_it_was_made(privacy_env) -> None:
    http, _caller, _identities, _maker = privacy_env

    body = http.get("/api/privacy/me/export").json()

    assert datetime.fromisoformat(body["generated_at"])
