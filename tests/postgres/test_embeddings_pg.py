"""Vectors against a real pgvector, because SQLite stores them as JSON.

The fallback column type keeps development working, but it cannot answer the only
questions that matter: does a 1536-float vector survive the round trip intact, and does
`<=>` order by cosine distance the way ranking assumes. Both are asserted here or
nowhere.
"""

from datetime import datetime, timedelta
from itertools import count

import pytest
from procuresignal.models import ArticleEmbedding, NewsArticleProcessed, NewsArticleRaw
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

_sequence = count(1)


async def _article(session: AsyncSession, *, title: str) -> int:
    ordinal = next(_sequence)
    now = datetime.utcnow()
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{ordinal}",
        title=title,
        article_url=f"https://example.com/{ordinal}",
        source_name="Test Source",
        published_at=now,
        language="en",
        ingested_at=now,
    )
    session.add(raw)
    await session.flush()

    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title=title,
        summary=f"A summary of {title}.",
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language="en",
        processed_at=now,
    )
    session.add(processed)
    await session.flush()
    return processed.id


async def _embed(session: AsyncSession, article: int, vector: list[float], *, model: str) -> None:
    session.add(
        ArticleEmbedding(
            processed_article_id=article,
            model=model,
            dimensions=len(vector),
            embedding=vector,
        )
    )
    await session.flush()


async def test_a_full_width_vector_survives_the_round_trip(pg_session: AsyncSession) -> None:
    """1536 floats, not the 4 the unit tests use. Width limits and precision loss show
    up at the real size or not at all."""

    article = await _article(pg_session, title="Rotterdam port strike")
    vector = [index / 1536 for index in range(1536)]

    await _embed(pg_session, article, vector, model="text-embedding-3-small")
    pg_session.expunge_all()

    stored = (await pg_session.execute(select(ArticleEmbedding))).scalar_one()
    assert stored.dimensions == 1536
    assert len(stored.embedding) == 1536
    assert stored.embedding[7] == pytest.approx(7 / 1536, abs=1e-6)


async def test_cosine_distance_orders_nearest_first(pg_session: AsyncSession) -> None:
    """`<=>` is the operator ranking calls. A vector column that cannot be ordered by
    it is storage, not an index."""

    near = await _article(pg_session, title="Near")
    far = await _article(pg_session, title="Far")
    await _embed(pg_session, near, [1.0, 0.05, 0.0], model="test-model")
    await _embed(pg_session, far, [0.0, 1.0, 0.0], model="test-model")

    ordered = (
        await pg_session.execute(
            text(
                "SELECT processed_article_id FROM article_embeddings "
                "WHERE model = 'test-model' "
                "ORDER BY embedding <=> CAST('[1,0,0]' AS vector) LIMIT 10"
            )
        )
    ).scalars()

    assert list(ordered) == [near, far]


async def test_one_row_per_article_and_model(pg_session: AsyncSession) -> None:
    """The uniqueness that makes the backfill idempotent. Enforced in the database
    because a re-run racing itself across two workers would pass an application check
    and still write twice.
    """

    article = await _article(pg_session, title="Rotterdam port strike")
    await _embed(pg_session, article, [1.0, 0.0, 0.0], model="test-model")

    with pytest.raises(IntegrityError):
        await _embed(pg_session, article, [0.0, 1.0, 0.0], model="test-model")


async def test_a_second_model_may_embed_the_same_article(pg_session: AsyncSession) -> None:
    """A model change adds rows beside the ones currently serving queries rather than
    replacing them, so a rollback is a filter change and not a re-embedding run."""

    article = await _article(pg_session, title="Rotterdam port strike")

    await _embed(pg_session, article, [1.0, 0.0, 0.0], model="old-model")
    await _embed(pg_session, article, [0.0, 1.0, 0.0, 0.0], model="new-model")

    rows = (await pg_session.execute(select(ArticleEmbedding))).scalars().all()
    assert {row.model for row in rows} == {"old-model", "new-model"}
    assert {row.dimensions for row in rows} == {3, 4}


async def test_the_column_holds_models_of_different_widths(pg_session: AsyncSession) -> None:
    """Declared without a fixed dimension on purpose: `text-embedding-3-large` is 3072,
    and a `vector(1536)` column would reject the migration that adopts it.

    The width guarantee that matters is enforced in code, per model, which is why every
    row records the dimensions it was written with.
    """

    declared = await pg_session.scalar(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'article_embeddings'::regclass AND attname = 'embedding'"
        )
    )

    assert declared == "vector"


async def test_deleting_an_article_takes_its_embedding_with_it(pg_session: AsyncSession) -> None:
    """Retention prunes processed articles after 30 days. Embeddings outliving them
    would grow without bound and rank results that no longer exist."""

    article = await _article(pg_session, title="Rotterdam port strike")
    await _embed(pg_session, article, [1.0, 0.0, 0.0], model="test-model")
    await pg_session.commit()

    await pg_session.execute(
        text("DELETE FROM news_articles_processed WHERE id = :id"), {"id": article}
    )
    await pg_session.commit()

    remaining = (await pg_session.execute(select(ArticleEmbedding))).scalars().all()
    assert remaining == []


async def test_the_migration_and_the_models_agree(pg_session: AsyncSession) -> None:
    """The schema here was built by `alembic upgrade head`, so a column the model
    declares and the migration forgot fails on the insert rather than at review."""

    article = await _article(pg_session, title="Rotterdam port strike")
    await _embed(pg_session, article, [1.0] * 1536, model="text-embedding-3-small")

    stored = (await pg_session.execute(select(ArticleEmbedding))).scalar_one()
    assert stored.created_at is not None
    assert isinstance(stored.created_at, datetime)
    assert stored.created_at > datetime.utcnow() - timedelta(minutes=5)
