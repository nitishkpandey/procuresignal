"""Integration tests for REST API."""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.config import database as database_module
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw, UserNewsPreference
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_session
from api.main import app


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
                llm_model="groq/llama-3.1-8b",
                language="en",
                processed_at=datetime.utcnow(),
            )
            session.add(processed)

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
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["user_id"] == "user-new"
    assert created["interested_categories"] == ["automotive"]

    fetched = api_client.get("/api/preferences", params={"user_id": "user-new"})
    assert fetched.status_code == 200
    assert fetched.json()["interested_suppliers"] == ["bosch"]


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
