"""Relevance feedback capture.

Nothing trains on this yet, and that is the point: a model trained on twelve labels is
theatre, so the honest first step is collecting the data properly. What makes it usable
later is `rank_position` and `mode` — a click on result 1 and a click on result 9 say
opposite things about the ranker, and without the position the whole table is
untrainable no matter how many rows it holds.

These tests pin the shape that matters for that: one signal per user per query per
article, positions preserved, and no organization able to read another's.
"""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from procuresignal.auth.passwords import hash_password
from procuresignal.models import (
    Base,
    Membership,
    NewsArticleProcessed,
    NewsArticleRaw,
    Organization,
    Role,
    SearchFeedback,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.main import app


@pytest.fixture()
def feedback_env(monkeypatch: pytest.MonkeyPatch):
    """Two organizations, one article, and a switchable caller."""

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
        identities = {}
        async with maker() as session:
            now = datetime.utcnow()
            raw = NewsArticleRaw(
                provider="test",
                query_group="test",
                ingest_hash="seed-1",
                title="Rotterdam port strike halts container traffic",
                article_url="https://example.com/1",
                source_name="Reuters",
                published_at=now,
                language="en",
                ingested_at=now,
            )
            session.add(raw)
            await session.flush()
            article = NewsArticleProcessed(
                raw_article_id=raw.id,
                normalized_title="Rotterdam port strike halts container traffic",
                summary="Dockworkers walked out.",
                top_level_category="logistics",
                signal_score=0.5,
                processing_status="completed",
                language="en",
                processed_at=now,
            )
            session.add(article)

            for slug in ("acme", "globex"):
                organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
                session.add(organization)
                await session.flush()
                user = User(
                    public_id=f"user-{slug}",
                    email=f"buyer@{slug}.example",
                    password_hash=hash_password("irrelevant-for-this-test"),
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                session.add(
                    Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN)
                )
                identities[slug] = AuthenticatedUser(
                    id=user.id,
                    public_id=user.public_id,
                    email=user.email,
                    organization_id=organization.id,
                    organization_public_id=organization.public_id,
                    role=Role.ADMIN,
                )

            await session.commit()
            return maker, identities, article.id

    maker, identities, article_id = asyncio.run(prepare())
    caller = {"identity": identities["acme"]}

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: caller["identity"]

    with TestClient(app) as client:
        yield client, caller, identities, article_id, maker

    app.dependency_overrides.clear()


def _payload(article_id: int, **overrides) -> dict:
    return {
        "query": "port strike",
        "article_id": article_id,
        "rank_position": 1,
        "signal": "click",
        "mode": "hybrid",
        **overrides,
    }


def test_a_click_is_captured_with_its_position_and_mode(feedback_env) -> None:
    """Position and mode are the two fields that make this trainable. Losing either
    turns the table into a list of articles somebody once opened."""

    client, _caller, identities, article_id, maker = feedback_env

    response = client.post("/api/search/feedback", json=_payload(article_id, rank_position=9))

    assert response.status_code == 201

    async def stored():
        async with maker() as session:
            return (await session.execute(select(SearchFeedback))).scalars().all()

    rows = asyncio.run(stored())
    assert len(rows) == 1
    assert rows[0].rank_position == 9
    assert rows[0].mode == "hybrid"
    assert rows[0].signal == "click"
    assert rows[0].query_text == "port strike"
    assert rows[0].user_id == identities["acme"].id
    assert rows[0].organization_id == identities["acme"].organization_id


def test_the_same_query_typed_differently_groups(feedback_env) -> None:
    """`query_fingerprint` is a normalised hash so "Port  Strike" and "port strike"
    are one query. Without it every whitespace variant is its own unlearnable group."""

    client, _caller, _identities, article_id, _maker = feedback_env

    first = client.post("/api/search/feedback", json=_payload(article_id))
    second = client.post(
        "/api/search/feedback",
        json=_payload(article_id, query="  Port   STRIKE ", signal="useful"),
    )

    assert first.json()["query_fingerprint"] == second.json()["query_fingerprint"]


def test_clicking_twice_is_one_signal(feedback_env) -> None:
    """A user who clicks, goes back and clicks again has not given two independent
    labels. Counting it twice would weight that pair by how indecisive somebody was."""

    client, _caller, _identities, article_id, maker = feedback_env

    first = client.post("/api/search/feedback", json=_payload(article_id))
    second = client.post("/api/search/feedback", json=_payload(article_id))

    assert first.status_code == 201
    assert second.status_code == 201, "a repeat signal is a no-op, not an error"

    async def count():
        async with maker() as session:
            return len((await session.execute(select(SearchFeedback))).scalars().all())

    assert asyncio.run(count()) == 1


def test_different_signals_on_the_same_result_are_kept_apart(feedback_env) -> None:
    """Opening a result and then marking it not relevant are two different statements
    about the same pair, and the second is the more informative one."""

    client, _caller, _identities, article_id, maker = feedback_env

    client.post("/api/search/feedback", json=_payload(article_id, signal="click"))
    client.post("/api/search/feedback", json=_payload(article_id, signal="not_useful"))

    async def signals():
        async with maker() as session:
            rows = (await session.execute(select(SearchFeedback))).scalars().all()
            return {row.signal for row in rows}

    assert asyncio.run(signals()) == {"click", "not_useful"}


def test_feedback_on_an_article_that_does_not_exist_is_rejected(feedback_env) -> None:
    """An unchecked id would fill the table with rows no ranker can use and no
    reviewer can trace back to anything."""

    client, _caller, _identities, _article_id, _maker = feedback_env

    response = client.post("/api/search/feedback", json=_payload(999_999))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("signal", "thumbs_up"),
        ("mode", "magic"),
        ("rank_position", 0),
        ("query", ""),
    ],
)
def test_values_outside_the_vocabulary_are_rejected(feedback_env, field: str, value) -> None:
    """The columns are only trainable if their values mean one thing. A free-text
    signal or a mode nothing produces makes the table unlearnable a year from now,
    when nobody remembers which spellings were in use."""

    client, _caller, _identities, article_id, _maker = feedback_env

    response = client.post("/api/search/feedback", json=_payload(article_id, **{field: value}))

    assert response.status_code == 422


def test_one_organization_cannot_read_anothers_feedback(feedback_env) -> None:
    """Query text is user-entered content tied to an identified person. Leaking it
    across tenants is a data breach, not a bug in a reporting screen."""

    client, caller, identities, article_id, _maker = feedback_env

    client.post("/api/search/feedback", json=_payload(article_id))

    caller["identity"] = identities["globex"]
    response = client.get("/api/search/feedback")

    assert response.status_code == 200
    assert response.json()["items"] == []

    caller["identity"] = identities["acme"]
    assert len(client.get("/api/search/feedback").json()["items"]) == 1


def test_the_export_carries_what_training_needs(feedback_env) -> None:
    client, _caller, _identities, article_id, _maker = feedback_env

    client.post("/api/search/feedback", json=_payload(article_id, rank_position=4))
    item = client.get("/api/search/feedback").json()["items"][0]

    assert item["rank_position"] == 4
    assert item["mode"] == "hybrid"
    assert item["signal"] == "click"
    assert item["article_id"] == article_id
    assert item["query_fingerprint"]


def test_a_member_cannot_export_the_query_log(feedback_env) -> None:
    """Submitting feedback is ordinary use; reading everyone's queries back is an
    administrative act over personal data."""

    client, caller, identities, article_id, _maker = feedback_env

    client.post("/api/search/feedback", json=_payload(article_id))

    member = identities["acme"]
    caller["identity"] = AuthenticatedUser(
        id=member.id,
        public_id=member.public_id,
        email=member.email,
        organization_id=member.organization_id,
        organization_public_id=member.organization_public_id,
        role=Role.MEMBER,
    )

    assert client.get("/api/search/feedback").status_code == 403
    assert client.post("/api/search/feedback", json=_payload(article_id)).status_code == 201
