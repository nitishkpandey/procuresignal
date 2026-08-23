"""The search endpoint, over the seeded in-memory corpus.

SQLite cannot run the vector half, so every response here is keyword-backed. That is the
point of these tests: the endpoint has to stay useful and honest on an instance where
semantic search is unavailable, which is also what production looks like before the
first embedding run finishes.
"""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.models import Base, NewsArticleProcessed, NewsArticleRaw
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import get_current_user, get_session
from api.main import app
from tests.conftest import fixed_identity


@pytest.fixture()
def search_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            for index, (title, summary) in enumerate(
                [
                    ("Rotterdam port strike halts container traffic", "Dockworkers walked out."),
                    ("Bosch opens a plant in Poznan", "An automotive supplier facility."),
                    ("Quarterly results from a logistics group", "Revenue was flat."),
                ]
            ):
                now = datetime.utcnow()
                raw = NewsArticleRaw(
                    provider="test",
                    query_group="test",
                    ingest_hash=f"seed-{index}",
                    title=title,
                    description=summary,
                    content_snippet=summary,
                    article_url=f"https://example.com/{index}",
                    source_name="Reuters",
                    published_at=now,
                    language="en",
                    ingested_at=now,
                )
                session.add(raw)
                await session.flush()
                session.add(
                    NewsArticleProcessed(
                        raw_article_id=raw.id,
                        normalized_title=title,
                        summary=summary,
                        top_level_category="logistics",
                        signal_score=0.5,
                        processing_status="completed",
                        language="en",
                        processed_at=now,
                    )
                )
            await session.commit()
        return maker

    maker = asyncio.run(prepare())

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: fixed_identity("user-1")

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_search_reports_the_mode_it_ran_in(search_client: TestClient) -> None:
    """Without a key the mode is `lexical`, not a silent pretence that ranking is
    semantic. The UI reads this to say keyword-only rather than overclaim."""

    response = search_client.get("/api/search", params={"q": "port strike", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "lexical"
    assert payload["results"], "a keyword-matchable query returned nothing"
    assert "Rotterdam" in payload["results"][0]["title"]


def test_relevance_stays_within_the_range_the_schema_promises(
    search_client: TestClient,
) -> None:
    """Raw reciprocal-rank scores are around 0.016 and would fail the 0-1 field
    validation's intent by being meaninglessly small rather than by being out of
    range."""

    payload = search_client.get("/api/search", params={"q": "port strike"}).json()

    assert payload["results"][0]["relevance"] == pytest.approx(1.0)
    assert all(0.0 <= result["relevance"] <= 1.0 for result in payload["results"])


def test_a_query_matching_nothing_is_an_empty_page_not_an_error(
    search_client: TestClient,
) -> None:
    payload = search_client.get("/api/search", params={"q": "zzzznonexistent"}).json()

    assert payload["results"] == []
    assert payload["total_results"] == 0
    assert payload["mode"] == "lexical"


def test_punctuation_a_user_typed_does_not_produce_a_500(search_client: TestClient) -> None:
    """`to_tsquery` would raise on these. `websearch_to_tsquery` is used precisely so
    the worst case is no results."""

    for query in ["port & strike", "!!!", "port:*", '"unclosed', "-"]:
        response = search_client.get("/api/search", params={"q": query})
        assert response.status_code == 200, query


def test_the_limit_bounds_the_page(search_client: TestClient) -> None:
    payload = search_client.get("/api/search", params={"q": "a", "limit": 1}).json()

    assert len(payload["results"]) <= 1


def test_the_old_substring_scorer_is_gone() -> None:
    """It ranked by counting substrings and was replaced, not supplemented. Two
    ranking functions in one module is how the wrong one gets called later.
    """

    from api.routers import articles

    assert not hasattr(articles, "_score_search_result")
