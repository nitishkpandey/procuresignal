"""Integration tests for REST API."""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from procuresignal.config import database as database_module
from procuresignal.currency.service import CurrencyMonitorResponse
from procuresignal.models import (
    Base,
    NewsArticleProcessed,
    NewsArticleRaw,
    RiskEvent,
    UserNewsPreference,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_session
from api.main import app
from api.routers import articles as articles_router
from api.routers import currency as currency_router
from api.routers import feed as feed_router
from api.routers import risk_events as risk_events_router


@pytest.fixture()
def api_client():
    """Create a test client backed by a seeded in-memory SQLite database."""

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare_database() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_maker() as session:
            raw = NewsArticleRaw(
                provider="newsapi",
                provider_article_id="article-123",
                query_group="supplier_risk",
                ingest_hash="seed-hash-123",
                title="Bosch announces new manufacturing facility in Poland",
                description="Bosch Group opens new automotive supplier facility in Poznan",
                content_snippet="The facility will produce EV components...",
                article_url="https://example.com/article",
                canonical_url="https://example.com/article",
                source_name="Reuters",
                source_url="https://reuters.com",
                published_at=datetime.utcnow(),
                language="en",
                ingested_at=datetime.utcnow(),
            )
            session.add(raw)
            await session.flush()

            processed = NewsArticleProcessed(
                raw_article_id=raw.id,
                normalized_title="Bosch manufacturing facility Poland",
                summary="Bosch announced a new manufacturing facility in Poznan, Poland.",
                top_level_category="automotive",
                signal_tags=["expansion", "manufacturing", "poland"],
                priority_signal="expansion",
                detected_regions=["Poland"],
                detected_suppliers=["Bosch"],
                detected_categories=["automotive", "manufacturing"],
                signal_score=0.87,
                processing_status="completed",
                llm_model="openai/test-model",
                language="en",
                processed_at=datetime.utcnow(),
            )
            session.add(processed)

            raw_missing_entities = NewsArticleRaw(
                provider="rss",
                provider_article_id="article-456",
                query_group="general",
                ingest_hash="seed-hash-456",
                title="Ferrari supplier talks expand in Italy after Mercedes parts warning",
                description="Ferrari and Mercedes discuss supplier continuity in Maranello, Italy.",
                content_snippet="Procurement teams are watching component availability across Italy.",
                article_url="https://example.com/article-456",
                canonical_url="https://example.com/article-456",
                source_name="Industry Week",
                source_url="https://industryweek.com",
                published_at=datetime.utcnow(),
                language="en",
                ingested_at=datetime.utcnow(),
            )
            session.add(raw_missing_entities)
            await session.flush()

            processed_missing_entities = NewsArticleProcessed(
                raw_article_id=raw_missing_entities.id,
                normalized_title="Ferrari supplier talks expand in Italy after strike warning",
                summary="Ferrari and Mercedes are watching supplier continuity in Italy after strike disruption.",
                top_level_category="automotive",
                signal_tags=["strike", "supplier_risk"],
                priority_signal="strike",
                detected_regions=[],
                detected_suppliers=[],
                detected_categories=[],
                signal_score=0.71,
                processing_status="completed",
                llm_model="openai/test-model",
                language="en",
                processed_at=datetime.utcnow(),
            )
            session.add(processed_missing_entities)

            pref = UserNewsPreference(
                user_id="user-123",
                preferred_categories=["automotive"],
                preferred_suppliers=["bosch"],
                preferred_regions=["poland"],
                preferred_signals=["expansion"],
                excluded_categories=[],
                excluded_suppliers=[],
                excluded_regions=[],
                excluded_signals=[],
                excluded_topics=[],
                onboarding_completed=True,
            )
            session.add(pref)

            await session.commit()

        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        return session_maker

    session_maker = asyncio.run(prepare_database())
    original_db_config = database_module.db_config
    db_config = database_module.DatabaseConfig("sqlite+aiosqlite://")
    db_config.engine = engine
    db_config.session_maker = session_maker
    database_module.db_config = db_config

    async def override_get_session():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    database_module.db_config = original_db_config
    asyncio.run(engine.dispose())


def test_root_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/")

    assert response.status_code == 200
    assert response.json()["service"] == "ProcureSignal API"


def test_health_check(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_api_health_check(api_client: TestClient) -> None:
    response = api_client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "api"
    assert payload["database"] == "connected"


def test_currency_endpoint_uses_service_defaults(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeCurrencyMonitor:
        calls: list[dict] = []

        async def get_eur_monitor(self, **kwargs):
            self.calls.append(kwargs)
            return CurrencyMonitorResponse(
                base="EUR",
                as_of="2026-07-09",
                lookback_days=kwargs.get("days", 30),
                currencies=[],
            )

    monitor = FakeCurrencyMonitor()
    monkeypatch.setattr(currency_router, "CurrencyMonitor", lambda: monitor)

    response = api_client.get("/api/currency/eur-monitor", params={"days": 30})

    assert response.status_code == 200
    assert response.json()["base"] == "EUR"
    assert monitor.calls == [{"days": 30}]


def test_feed_missing_user_id(api_client: TestClient) -> None:
    response = api_client.get("/api/feed")

    assert response.status_code == 422


def test_feed_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/api/feed", params={"user_id": "user-123", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "user-123"
    assert payload["total_count"] >= 1
    assert payload["articles"]


def test_risk_events_endpoint_generates_and_lists_events(api_client: TestClient) -> None:
    response = api_client.get("/api/risk-events", params={"user_id": "user-123", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "user-123"
    assert payload["total_count"] >= 0
    assert "events" in payload


def test_risk_event_status_update(api_client: TestClient) -> None:
    created = api_client.get("/api/risk-events", params={"user_id": "user-123", "limit": 20})
    assert created.status_code == 200
    events = created.json()["events"]
    if not events:
        pytest.skip("seed data did not produce a risk event")

    event_id = events[0]["id"]
    response = api_client.patch(f"/api/risk-events/{event_id}/status", json={"status": "reviewed"})

    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"


def test_risk_events_paginates_after_preference_ranking(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def skip_generation(*args, **kwargs) -> None:
        return None

    async def seed_events() -> list[int]:
        session_maker = database_module.db_config.session_maker
        assert session_maker is not None
        now = datetime.utcnow()
        events = []
        for index, confidence, suppliers in [
            (1, 0.60, []),
            (2, 0.60, []),
            (3, 0.60, []),
            (4, 0.70, ["Bosch"]),
            (5, 0.65, ["Bosch"]),
        ]:
            events.append(
                RiskEvent(
                    event_key=f"pagination-{index}",
                    processed_article_id=100 + index,
                    risk_type="strike",
                    severity="medium",
                    confidence=confidence,
                    affected_suppliers=suppliers,
                    affected_locations=["Italy"],
                    affected_categories=["automotive"],
                    evidence_snippet="Supplier continuity risk.",
                    recommendation="Review contingency plans.",
                    source_name="Test source",
                    source_url="https://example.com/risk-event",
                    published_at=now - timedelta(seconds=index),
                    status="new",
                )
            )
        async with session_maker() as session:
            session.add_all(events)
            await session.commit()
            return [event.id for event in events]

    older_preferred_ids = asyncio.run(seed_events())[-2:]
    monkeypatch.setattr(risk_events_router, "generate_risk_events", skip_generation)

    response = api_client.get(
        "/api/risk-events",
        params={
            "user_id": "user-123",
            "category": "automotive",
            "limit": 1,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 5
    assert payload["events"][0]["id"] == older_preferred_ids[1]


def test_feed_translates_articles_when_language_requested(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_translate(articles, language):
        assert language == "de"
        return [
            article.model_copy(
                update={
                    "title": f"DE: {article.title}",
                    "summary": f"DE: {article.summary}",
                }
            )
            for article in articles
        ]

    monkeypatch.setattr(feed_router, "translate_feed_articles", fake_translate, raising=False)

    response = api_client.get(
        "/api/feed",
        params={"user_id": "user-123", "limit": 20, "language": "de"},
    )

    assert response.status_code == 200
    first_article = response.json()["articles"][0]
    assert first_article["title"].startswith("DE: ")
    assert first_article["summary"].startswith("DE: ")


def test_feed_without_preferences_returns_general_news(api_client: TestClient) -> None:
    response = api_client.get("/api/feed", params={"user_id": "new-user", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "new-user"
    assert payload["articles"]


def test_feed_with_unmatched_preferences_falls_back_to_general_news(
    api_client: TestClient,
) -> None:
    saved = api_client.post(
        "/api/preferences",
        json={
            "user_id": "unmatched-user",
            "interested_signals": ["warning"],
        },
    )
    assert saved.status_code == 200

    response = api_client.get("/api/feed", params={"user_id": "unmatched-user", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "unmatched-user"
    assert payload["articles"]


def test_feed_tops_up_when_existing_rows_are_below_requested_limit(
    api_client: TestClient,
) -> None:
    first = api_client.get("/api/feed", params={"user_id": "top-up-user", "limit": 1})
    assert first.status_code == 200
    assert len(first.json()["articles"]) == 1

    second = api_client.get("/api/feed", params={"user_id": "top-up-user", "limit": 20})

    assert second.status_code == 200
    assert len(second.json()["articles"]) > 1


def test_preference_update_clears_stale_feed(api_client: TestClient) -> None:
    first = api_client.get("/api/feed", params={"user_id": "user-123", "limit": 20})
    assert first.status_code == 200
    assert first.json()["articles"]

    updated = api_client.post(
        "/api/preferences",
        json={
            "user_id": "user-123",
            "excluded_categories": ["automotive"],
        },
    )
    assert updated.status_code == 200

    refreshed = api_client.get("/api/feed", params={"user_id": "user-123", "limit": 20})
    assert refreshed.status_code == 200
    assert refreshed.json()["articles"] == []


def test_language_update_does_not_clear_existing_feed(api_client: TestClient) -> None:
    first = api_client.get("/api/feed", params={"user_id": "user-123", "limit": 20})
    assert first.status_code == 200
    assert first.json()["articles"]

    updated = api_client.patch(
        "/api/preferences/language",
        json={"user_id": "user-123", "platform_language": "de"},
    )

    assert updated.status_code == 200
    assert updated.json()["platform_language"] == "de"

    refreshed = api_client.get("/api/feed", params={"user_id": "user-123", "limit": 20})
    assert refreshed.status_code == 200
    assert refreshed.json()["articles"]


def test_preferences_round_trip(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/preferences",
        json={
            "user_id": "user-new",
            "interested_categories": ["Automotive"],
            "interested_suppliers": ["Bosch"],
            "interested_regions": ["Germany"],
            "interested_signals": ["Tariff"],
            "excluded_categories": ["Politics"],
            "platform_language": "de",
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["user_id"] == "user-new"
    assert created["interested_categories"] == ["automotive"]
    assert created["platform_language"] == "de"

    fetched = api_client.get("/api/preferences", params={"user_id": "user-new"})
    assert fetched.status_code == 200
    assert fetched.json()["interested_suppliers"] == ["bosch"]
    assert fetched.json()["platform_language"] == "de"


def test_preference_category_alias_generates_feed(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/preferences",
        json={
            "user_id": "user-alias",
            "interested_categories": ["Automobiles"],
        },
    )

    assert response.status_code == 200
    assert response.json()["interested_categories"] == ["automotive"]

    feed = api_client.get("/api/feed", params={"user_id": "user-alias", "limit": 20})
    assert feed.status_code == 200
    assert feed.json()["articles"]
    assert feed.json()["articles"][0]["category"] == "automotive"


def test_bulk_preferences(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/preferences/bulk",
        json={
            "items": [
                {
                    "user_id": "bulk-1",
                    "interested_categories": ["Manufacturing"],
                    "interested_suppliers": ["Siemens"],
                },
                {
                    "user_id": "bulk-2",
                    "interested_regions": ["Poland"],
                    "excluded_signals": ["strike"],
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["updated_count"] == 2


def test_get_article_not_found(api_client: TestClient) -> None:
    response = api_client.get("/api/articles/999999")

    assert response.status_code == 404


def test_get_article_detail(api_client: TestClient) -> None:
    response = api_client.get("/api/articles/1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"]
    assert payload["source_name"] == "Reuters"


def test_get_article_detail_translates_when_language_requested(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_translate(article, language):
        assert language == "de"
        return article.model_copy(
            update={
                "title": f"DE: {article.title}",
                "summary": f"DE: {article.summary}",
            }
        )

    monkeypatch.setattr(
        articles_router,
        "translate_article_detail",
        fake_translate,
        raising=False,
    )

    response = api_client.get("/api/articles/1", params={"language": "de"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"].startswith("DE: ")
    assert payload["summary"].startswith("DE: ")


def test_get_article_detail_infers_missing_entities(api_client: TestClient) -> None:
    response = api_client.get("/api/articles/2")

    assert response.status_code == 200
    payload = response.json()
    assert "Ferrari" in payload["detected_suppliers"]
    assert "Mercedes" in payload["detected_suppliers"]
    assert "Italy" in payload["detected_regions"]
    assert payload["detected_categories"] == ["automotive"]


def test_feed_infers_missing_entities(api_client: TestClient) -> None:
    response = api_client.get("/api/feed", params={"user_id": "metadata-user", "limit": 20})

    assert response.status_code == 200
    article = next(
        item
        for item in response.json()["articles"]
        if item["title"] == "Ferrari supplier talks expand in Italy after strike warning"
    )
    assert "Ferrari" in article["detected_suppliers"]
    assert "Italy" in article["detected_regions"]


def test_search_missing_query(api_client: TestClient) -> None:
    response = api_client.get("/api/search")

    assert response.status_code == 422


def test_search_articles(api_client: TestClient) -> None:
    response = api_client.get("/api/search", params={"q": "Bosch", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Bosch"
    assert payload["total_results"] >= 1


def test_mark_article_read(api_client: TestClient) -> None:
    feed_response = api_client.get("/api/feed", params={"user_id": "user-123", "limit": 10})
    assert feed_response.status_code == 200

    read_response = api_client.post(
        "/api/articles/1/read",
        params={"user_id": "user-123"},
    )

    assert read_response.status_code == 200
    assert read_response.json()["read"] is True
