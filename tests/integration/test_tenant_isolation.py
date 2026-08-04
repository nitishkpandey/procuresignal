"""Every user-scoped route must serve the authenticated identity and nobody else.

Each test here corresponds to a vulnerability that existed before Phase 1 Task 5:
identity was taken from a query parameter, a request body, or a URL path, so any
caller could name any user and receive their data.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import (
    Base,
    ChatConversation,
    ChatMessage,
    NewsArticleProcessed,
    NewsArticleRaw,
    UserNewsFeed,
    UserNewsPreference,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_session
from api.main import app
from api.routers import currency as currency_router

PASSWORD = "a-sufficiently-long-password"


@dataclass
class Account:
    user_id: str
    headers: dict[str, str]
    conversation_id: str


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

    class _StubCurrencyMonitor:
        async def get_eur_monitor(self, **kwargs):
            from procuresignal.currency.service import CurrencyMonitorResponse

            return CurrencyMonitorResponse(
                base="EUR",
                as_of="2026-08-01",
                lookback_days=kwargs.get("days", 30),
                currencies=[],
            )

    monkeypatch.setattr(currency_router, "CurrencyMonitor", lambda: _StubCurrencyMonitor())

    app.dependency_overrides[get_session] = _session
    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.session_maker = maker  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _enrol(client: TestClient, email: str, marker: str) -> Account:
    body = client.post("/api/auth/register", json={"email": email, "password": PASSWORD}).json()
    user_id = body["user"]["user_id"]
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    async def _seed() -> str:
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            raw = NewsArticleRaw(
                provider="rss",
                provider_article_id=f"{marker}-raw",
                query_group="tariffs",
                ingest_hash=f"{marker}-hash",
                title=f"{marker} tariff headline",
                description=f"{marker} description",
                content_snippet=f"{marker} snippet",
                article_url=f"https://example.test/{marker}",
                source_name="Example Wire",
                published_at=datetime(2026, 7, 20, 9, 0),
                ingested_at=datetime(2026, 7, 20, 9, 30),
                language="en",
            )
            session.add(raw)
            await session.flush()

            processed = NewsArticleProcessed(
                raw_article_id=raw.id,
                normalized_title=f"{marker} tariff headline",
                summary=f"{marker} summary",
                top_level_category="logistics",
                signal_tags=["tariffs"],
                priority_signal=False,
                processed_at=datetime(2026, 7, 20, 9, 45),
            )
            session.add(processed)
            await session.flush()

            session.add(
                UserNewsFeed(
                    user_id=user_id,
                    processed_article_id=processed.id,
                    top_level_category="logistics",
                    rank_score=0.9,
                    match_reasons={"category": ["logistics"]},
                    surfaced_at=datetime(2026, 7, 20, 10, 0),
                )
            )
            session.add(
                UserNewsPreference(
                    user_id=user_id,
                    preferred_categories=[marker],
                    preferred_suppliers=[],
                    preferred_regions=[],
                    preferred_signals=[],
                    excluded_categories=[],
                    excluded_suppliers=[],
                    excluded_regions=[],
                    excluded_signals=[],
                    excluded_topics=[],
                )
            )
            conversation = ChatConversation(
                conversation_id=f"conv-{marker}", user_id=user_id, title=f"{marker} chat"
            )
            session.add(conversation)
            await session.flush()
            session.add(
                ChatMessage(
                    conversation_id=conversation.conversation_id,
                    user_id=user_id,
                    role="user",
                    content=f"{marker} secret message",
                )
            )
            await session.commit()
            return conversation.conversation_id

    return Account(user_id=user_id, headers=headers, conversation_id=asyncio.run(_seed()))


@pytest.fixture
def alice(client: TestClient) -> Account:
    return _enrol(client, "alice@acme.com", "alice")


@pytest.fixture
def bob(client: TestClient) -> Account:
    return _enrol(client, "bob@globex.com", "bob")


# Every route that used to accept identity from the caller.
USER_SCOPED_ROUTES = [
    ("get", "/api/feed"),
    ("get", "/api/preferences"),
    ("get", "/api/risk-events"),
    ("get", "/api/conversations"),
    ("get", "/api/search?q=tariff"),
    ("get", "/api/currency/eur-monitor"),
]


@pytest.mark.parametrize(("method", "path"), USER_SCOPED_ROUTES)
def test_route_requires_authentication(client: TestClient, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(("method", "path"), USER_SCOPED_ROUTES)
def test_supplying_another_user_id_does_not_change_the_result(
    client: TestClient, alice: Account, bob: Account, method: str, path: str
) -> None:
    """The old parameter must be ignored, not honoured."""
    joiner = "&" if "?" in path else "?"
    forged = f"{path}{joiner}user_id={bob.user_id}"

    honest = getattr(client, method)(path, headers=alice.headers)
    attempt = getattr(client, method)(forged, headers=alice.headers)

    assert honest.status_code == attempt.status_code == 200
    assert "bob" not in attempt.text
    assert bob.user_id not in attempt.text


def test_feed_returns_only_the_callers_articles(
    client: TestClient, alice: Account, bob: Account
) -> None:
    body = client.get("/api/feed", headers=alice.headers).json()

    assert body["user_id"] == alice.user_id
    titles = " ".join(article["title"] for article in body["articles"])
    assert "alice" in titles
    assert "bob" not in titles


def test_preferences_return_only_the_callers_record(
    client: TestClient, alice: Account, bob: Account
) -> None:
    body = client.get("/api/preferences", headers=alice.headers).json()

    assert body["user_id"] == alice.user_id
    assert body["interested_categories"] == ["alice"]


def test_preferences_cannot_be_written_for_another_user(
    client: TestClient, alice: Account, bob: Account
) -> None:
    """user_id was a request-body field, so anyone could overwrite anyone."""
    response = client.post(
        "/api/preferences",
        headers=alice.headers,
        json={
            "user_id": bob.user_id,
            "interested_categories": ["hijacked"],
            "platform_language": "en",
        },
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == alice.user_id

    victim = client.get("/api/preferences", headers=bob.headers).json()
    assert victim["interested_categories"] == ["bob"]


def test_language_update_cannot_target_another_user(
    client: TestClient, alice: Account, bob: Account
) -> None:
    response = client.patch(
        "/api/preferences/language",
        headers=alice.headers,
        json={"user_id": bob.user_id, "platform_language": "de"},
    )
    assert response.status_code == 200

    assert client.get("/api/preferences", headers=bob.headers).json()["platform_language"] == "en"


def test_conversation_messages_reject_another_user(
    client: TestClient, alice: Account, bob: Account
) -> None:
    """This endpoint previously had no ownership check at all."""
    response = client.get(
        f"/api/conversations/{bob.conversation_id}/messages", headers=alice.headers
    )

    # 404 rather than 403: a 403 confirms the conversation exists.
    assert response.status_code == 404
    assert "secret message" not in response.text


def test_conversation_messages_are_readable_by_their_owner(
    client: TestClient, bob: Account
) -> None:
    response = client.get(f"/api/conversations/{bob.conversation_id}/messages", headers=bob.headers)

    assert response.status_code == 200
    assert "bob secret message" in response.text


def test_clearing_history_only_clears_the_callers_own(
    client: TestClient, alice: Account, bob: Account
) -> None:
    assert client.delete("/api/conversations", headers=alice.headers).status_code == 200

    surviving = client.get("/api/conversations", headers=bob.headers).json()
    assert surviving["total_count"] == 1


def test_marking_an_article_read_cannot_target_another_users_feed(
    client: TestClient, alice: Account, bob: Account
) -> None:
    async def _bob_article_id() -> int:
        async with client.session_maker() as session:  # type: ignore[attr-defined]
            from sqlalchemy import select

            return (
                await session.execute(
                    select(UserNewsFeed.processed_article_id).where(
                        UserNewsFeed.user_id == bob.user_id
                    )
                )
            ).scalar_one()

    article_id = asyncio.run(_bob_article_id())

    response = client.post(f"/api/articles/{article_id}/read", headers=alice.headers)
    assert response.status_code == 404


def test_bulk_preference_endpoint_is_gone(client: TestClient, alice: Account) -> None:
    """It wrote arbitrary users' preferences and had no consumer."""
    response = client.post(
        "/api/preferences/bulk",
        headers=alice.headers,
        json={"items": [{"user_id": "someone-else", "interested_categories": ["x"]}]},
    )
    assert response.status_code == 404


def test_risk_event_status_change_requires_authentication(client: TestClient) -> None:
    assert client.patch("/api/risk-events/1/status", json={"status": "reviewed"}).status_code == 401


def test_article_detail_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/articles/1").status_code == 401


def test_signals_require_authentication(client: TestClient) -> None:
    assert client.get("/api/signals/").status_code == 401


def test_health_and_root_stay_public(client: TestClient) -> None:
    """Liveness probes cannot hold credentials."""
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


def test_viewers_cannot_change_a_risk_event_status(client: TestClient, alice: Account) -> None:
    """A viewer reads the intelligence but does not alter the team's record of it."""
    from procuresignal.models import Role

    from api.dependencies import get_current_user
    from api.main import app
    from tests.conftest import fixed_identity

    app.dependency_overrides[get_current_user] = lambda: fixed_identity(
        alice.user_id, role=Role.VIEWER
    )
    viewer = client.patch("/api/risk-events/1/status", json={"status": "reviewed"})

    app.dependency_overrides[get_current_user] = lambda: fixed_identity(
        alice.user_id, role=Role.MEMBER
    )
    member = client.patch("/api/risk-events/1/status", json={"status": "reviewed"})

    assert viewer.status_code == 403
    # 404 because no such event was seeded, which still proves the role gate let it past.
    assert member.status_code == 404
