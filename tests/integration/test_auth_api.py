"""Integration tests for the authentication endpoints."""

import asyncio
from collections.abc import Coroutine, Iterator

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import AuditLog, Base, Membership, Organization, Role, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_session
from api.main import app

PASSWORD = "a-sufficiently-long-password"
REFRESH_COOKIE = "procuresignal_refresh"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key-that-is-long-enough-32")

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    async def _session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    # https, because the refresh cookie is Secure and would not be sent back over http.
    # Testing the production flag beats disabling it for the tests.
    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.session_maker = maker  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def run(coroutine: Coroutine):
    """Drive a coroutine from a sync test, matching the pattern in test_api.py."""
    return asyncio.run(coroutine)


def register(client: TestClient, email: str = "buyer@acme.com") -> dict:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "A Buyer"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _rows(client: TestClient, model):
    async with client.session_maker() as session:  # type: ignore[attr-defined]
        return list((await session.execute(select(model))).scalars().all())


# --- registration ---------------------------------------------------------------


def test_registration_returns_a_token_and_sets_a_refresh_cookie(client: TestClient) -> None:
    body = register(client)

    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "buyer@acme.com"
    assert "password" not in str(body)
    assert REFRESH_COOKIE in client.cookies


def test_refresh_cookie_is_httponly_and_absent_from_the_body(client: TestClient) -> None:
    response = client.post("/api/auth/register", json={"email": "x@acme.com", "password": PASSWORD})

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.replace("samesite=lax", "SameSite=lax")
    assert "refresh" not in response.json()


def test_first_user_of_a_domain_owns_the_organization(client: TestClient) -> None:
    body = register(client)
    assert body["user"]["role"] == Role.OWNER


def test_public_email_providers_never_share_an_organization(client: TestClient) -> None:
    """Domain grouping must not put every consumer-mailbox signup in one tenant."""
    first = register(client, "alice@gmail.com")
    second = register(client, "bob@gmail.com")

    assert first["user"]["organization_id"] != second["user"]["organization_id"]
    assert first["user"]["role"] == second["user"]["role"] == Role.OWNER


def test_duplicate_email_is_refused(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/auth/register", json={"email": "buyer@acme.com", "password": PASSWORD}
    )
    assert response.status_code == 409


@pytest.mark.parametrize("weak", ["short", "", "1234567890"])
def test_weak_passwords_are_refused(client: TestClient, weak: str) -> None:
    response = client.post("/api/auth/register", json={"email": "a@acme.com", "password": weak})
    assert response.status_code == 422


# --- login ----------------------------------------------------------------------


def test_login_succeeds_with_correct_credentials(client: TestClient) -> None:
    register(client)
    client.cookies.clear()

    response = client.post(
        "/api/auth/login", json={"email": "buyer@acme.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_unknown_account_and_wrong_password_are_indistinguishable(client: TestClient) -> None:
    register(client)

    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@acme.com", "password": PASSWORD}
    )
    wrong = client.post(
        "/api/auth/login", json={"email": "buyer@acme.com", "password": "wrong-but-long-enough"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_placeholder_user_from_the_backfill_cannot_log_in(client: TestClient) -> None:
    """Backfilled identities have no password and must stay unreachable."""

    async def _seed() -> None:
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            org = Organization(public_id="o-legacy", name="Legacy", slug="legacy")
            user = User(
                public_id="u-legacy",
                email="legacy@acme.com",
                password_hash=None,
                is_active=False,
            )
            session.add_all([org, user])
            await session.flush()
            session.add(Membership(user_id=user.id, organization_id=org.id, role=Role.OWNER))
            await session.commit()

    run(_seed())

    for attempt in ("", PASSWORD, "anything"):
        response = client.post(
            "/api/auth/login", json={"email": "legacy@acme.com", "password": attempt or PASSWORD}
        )
        assert response.status_code == 401


def test_deactivated_user_cannot_log_in(client: TestClient) -> None:
    register(client)

    async def _deactivate() -> None:
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            user = (await session.execute(select(User))).scalars().one()
            user.is_active = False
            await session.commit()

    run(_deactivate())

    response = client.post(
        "/api/auth/login", json={"email": "buyer@acme.com", "password": PASSWORD}
    )
    assert response.status_code == 401


# --- refresh rotation -----------------------------------------------------------


def test_refresh_issues_a_new_access_token_and_rotates_the_cookie(client: TestClient) -> None:
    register(client)
    original = client.cookies[REFRESH_COOKIE]

    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["user"]["email"] == "buyer@acme.com"
    assert client.cookies[REFRESH_COOKIE] != original


def test_replaying_a_rotated_token_revokes_the_whole_family(client: TestClient) -> None:
    """A replayed refresh token means it leaked, so every descendant session dies."""
    register(client)
    stolen = client.cookies[REFRESH_COOKIE]

    assert client.post("/api/auth/refresh").status_code == 200
    rotated = client.cookies[REFRESH_COOKIE]

    client.cookies.set(REFRESH_COOKIE, stolen, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401

    client.cookies.set(REFRESH_COOKIE, rotated, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_without_a_cookie_is_refused(client: TestClient) -> None:
    assert client.post("/api/auth/refresh").status_code == 401


def test_unknown_refresh_token_is_refused(client: TestClient) -> None:
    client.cookies.set(REFRESH_COOKIE, "not-a-real-token", path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401


# --- logout and revocation ------------------------------------------------------


def test_logout_revokes_the_session_and_clears_the_cookie(client: TestClient) -> None:
    register(client)

    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert client.post("/api/auth/refresh").status_code == 401


def test_revoke_all_sessions_invalidates_outstanding_access_tokens(client: TestClient) -> None:
    body = register(client)
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/revoke-all-sessions", headers=headers).status_code == 204

    # The token itself has not expired; the bumped version is what kills it.
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401


def test_me_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_authenticated_identity(client: TestClient) -> None:
    body = register(client)
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "buyer@acme.com"
    assert "password_hash" not in str(response.json())


# --- audit ----------------------------------------------------------------------


def test_authentication_events_are_audited(client: TestClient) -> None:
    register(client)
    client.post("/api/auth/login", json={"email": "buyer@acme.com", "password": "wrong-password-x"})

    rows = run(_rows(client, AuditLog))
    actions = {(row.action, row.outcome) for row in rows}

    assert ("user.register", "success") in actions
    assert ("user.login", "failure") in actions
    assert all("wrong-password-x" not in str(row.detail) for row in rows)


# --- throttling -----------------------------------------------------------------


def test_repeated_failed_logins_are_throttled(client: TestClient) -> None:
    register(client)

    for _ in range(5):
        assert (
            client.post(
                "/api/auth/login", json={"email": "buyer@acme.com", "password": "wrong-but-long"}
            ).status_code
            == 401
        )

    blocked = client.post(
        "/api/auth/login", json={"email": "buyer@acme.com", "password": "wrong-but-long"}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_throttling_does_not_punish_a_different_account(client: TestClient) -> None:
    """One address being attacked must not lock out everyone else."""
    register(client, "victim@acme.com")
    register(client, "bystander@acme.com")

    for _ in range(6):
        client.post(
            "/api/auth/login", json={"email": "victim@acme.com", "password": "wrong-but-long"}
        )

    assert (
        client.post(
            "/api/auth/login", json={"email": "bystander@acme.com", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_successful_logins_are_never_throttled(client: TestClient) -> None:
    register(client)

    for _ in range(20):
        assert (
            client.post(
                "/api/auth/login", json={"email": "buyer@acme.com", "password": PASSWORD}
            ).status_code
            == 200
        )


def test_repeated_duplicate_registrations_are_throttled(client: TestClient) -> None:
    """Retrying a taken address is how registration gets used to enumerate accounts."""
    register(client)

    statuses = [
        client.post(
            "/api/auth/register", json={"email": "buyer@acme.com", "password": PASSWORD}
        ).status_code
        for _ in range(12)
    ]

    assert 409 in statuses
    assert statuses[-1] == 429


# --- tenant enrolment ------------------------------------------------------------


def test_registering_a_company_domain_does_not_join_an_existing_tenant(
    client: TestClient,
) -> None:
    """Owning the mailbox is unproven at registration.

    Anyone could type colleague@acme.com. Joining Acme on that alone would hand them
    the organization's data the moment shared watchlists and dashboards exist.
    """
    first = register(client, "cfo@acme.com")
    second = register(client, "attacker@acme.com")

    assert second["user"]["organization_id"] != first["user"]["organization_id"]
    assert second["user"]["role"] == Role.OWNER


def test_joining_an_existing_organization_needs_an_invitation(client: TestClient) -> None:
    """The supported path in: an admin invites, the invitee accepts."""
    owner = register(client, "cfo@acme.com")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}

    invitation = client.post(
        "/api/auth/invitations",
        headers=headers,
        json={"email": "colleague@acme.com", "role": Role.MEMBER},
    )
    assert invitation.status_code == 201
    token = invitation.json()["token"]

    accepted = client.post(
        "/api/auth/register",
        json={"email": "colleague@acme.com", "password": PASSWORD, "invitation_token": token},
    )

    assert accepted.status_code == 201
    assert accepted.json()["user"]["organization_id"] == owner["user"]["organization_id"]
    assert accepted.json()["user"]["role"] == Role.MEMBER


def test_only_admins_may_invite(client: TestClient) -> None:
    owner = register(client, "cfo@acme.com")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}

    invitation = client.post(
        "/api/auth/invitations", headers=headers, json={"email": "colleague@acme.com"}
    ).json()

    joined = client.post(
        "/api/auth/register",
        json={
            "email": "colleague@acme.com",
            "password": PASSWORD,
            "invitation_token": invitation["token"],
        },
    ).json()
    member_headers = {"Authorization": f"Bearer {joined['access_token']}"}

    refused = client.post(
        "/api/auth/invitations", headers=member_headers, json={"email": "another@acme.com"}
    )
    assert refused.status_code == 403


def test_an_invitation_cannot_be_redeemed_by_a_different_address(client: TestClient) -> None:
    owner = register(client, "cfo@acme.com")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    invitation = client.post(
        "/api/auth/invitations", headers=headers, json={"email": "colleague@acme.com"}
    ).json()

    response = client.post(
        "/api/auth/register",
        json={
            "email": "someone.else@acme.com",
            "password": PASSWORD,
            "invitation_token": invitation["token"],
        },
    )

    assert response.status_code == 400


def test_an_invitation_is_single_use(client: TestClient) -> None:
    owner = register(client, "cfo@acme.com")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    invitation = client.post(
        "/api/auth/invitations", headers=headers, json={"email": "colleague@acme.com"}
    ).json()
    body = {
        "email": "colleague@acme.com",
        "password": PASSWORD,
        "invitation_token": invitation["token"],
    }

    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_an_unknown_invitation_token_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": "nobody@acme.com", "password": PASSWORD, "invitation_token": "made-up"},
    )

    assert response.status_code == 400


def test_invitations_are_audited(client: TestClient) -> None:
    owner = register(client, "cfo@acme.com")
    client.post(
        "/api/auth/invitations",
        headers={"Authorization": f"Bearer {owner['access_token']}"},
        json={"email": "colleague@acme.com"},
    )

    rows = run(_rows(client, AuditLog))
    assert ("organization.invite", "success") in {(r.action, r.outcome) for r in rows}


def test_registering_many_new_accounts_is_throttled(client: TestClient) -> None:
    """Limiting only failures let an attacker with fresh addresses create unlimited
    accounts and organizations without ever approaching the cap."""
    statuses = [
        client.post(
            "/api/auth/register", json={"email": f"new{index}@example.com", "password": PASSWORD}
        ).status_code
        for index in range(12)
    ]

    assert 201 in statuses
    assert 429 in statuses, "unique addresses bypassed the registration limit entirely"
