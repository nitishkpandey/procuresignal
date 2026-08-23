"""Hybrid retrieval where both halves can actually run.

The unit tests cover fusion arithmetic and the degradation paths. What only PostgreSQL
can answer is whether the two halves compose: whether the vector query returns anything,
whether fusion improves on either retriever alone, and whether the mode reported matches
what really happened.

Vectors here are hand-built and three-dimensional rather than produced by a model, so
"semantically similar" means "assigned a nearby vector by this test". That is enough to
verify the plumbing and the ranking; whether real embeddings put the right articles near
each other is what Task 7's evaluation harness measures.
"""

from datetime import datetime, timedelta
from itertools import count

import pytest
from procuresignal.models import ArticleEmbedding, NewsArticleProcessed, NewsArticleRaw
from procuresignal.search.hybrid import DEGRADED, HYBRID, search, vector_search
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

_sequence = count(1)

MODEL = "test-embed"


class StubProvider:
    """Maps a known query to a known point in the same space the fixtures use."""

    name = MODEL
    dimensions = 3

    def __init__(self, vector: list[float]):
        self.vector = vector
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self.vector for _ in texts]


async def _article(
    session: AsyncSession,
    *,
    title: str,
    summary: str = "",
    vector: list[float] | None = None,
    age_days: int = 0,
) -> int:
    ordinal = next(_sequence)
    when = datetime.utcnow() - timedelta(days=age_days)
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{ordinal}",
        title=title,
        description=summary,
        content_snippet=summary,
        article_url=f"https://example.com/{ordinal}",
        source_name="Test Source",
        published_at=when,
        language="en",
        ingested_at=when,
    )
    session.add(raw)
    await session.flush()

    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title=title,
        summary=summary or f"A summary of {title}.",
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language="en",
        processed_at=when,
    )
    session.add(processed)
    await session.flush()

    if vector is not None:
        session.add(
            ArticleEmbedding(
                processed_article_id=processed.id,
                model=MODEL,
                dimensions=len(vector),
                embedding=vector,
            )
        )
        await session.flush()
    return processed.id


async def test_the_vector_half_finds_what_keywords_cannot(pg_session: AsyncSession) -> None:
    """The reason for embedding anything at all.

    The article never uses the words "port" or "strike"; lexical retrieval cannot reach
    it at any ranking. Only the vector half can, and the fused result includes it.
    """

    lexical_only = await _article(
        pg_session, title="Port strike enters second week", vector=[0.0, 1.0, 0.0]
    )
    vector_only = await _article(
        pg_session,
        title="Dockworkers walk out in Rotterdam",
        summary="Container handling has stopped at the terminal.",
        vector=[1.0, 0.0, 0.0],
    )
    provider = StubProvider([1.0, 0.05, 0.0])

    outcome = await search(pg_session, query="port strike", limit=10, days=7, provider=provider)

    assert outcome.mode == HYBRID
    found = [hit.processed_id for hit in outcome.hits]
    assert vector_only in found, "the semantic half contributed nothing"
    assert lexical_only in found
    assert outcome.vector_count > 0
    assert outcome.lexical_count > 0


async def test_a_document_both_halves_rank_comes_first(pg_session: AsyncSession) -> None:
    """Fusion's whole claim.

    `keyword_favourite` is the top lexical hit — it repeats both query terms — but has
    no vector, as any article ingested since the last embedding run would not. `agreed`
    is only the second lexical hit and the first vector hit, and that combination is
    what puts it first. Neither retriever alone produces this order.
    """

    keyword_favourite = await _article(pg_session, title="Port strike port strike")
    agreed = await _article(
        pg_session,
        title="Port strike halts Rotterdam",
        summary="Dockworkers stopped work.",
        vector=[1.0, 0.0, 0.0],
    )
    distant = await _article(pg_session, title="Unrelated logistics note", vector=[0.0, 1.0, 0.0])
    provider = StubProvider([1.0, 0.0, 0.0])

    outcome = await search(pg_session, query="port strike", limit=10, days=7, provider=provider)
    ranked = [hit.processed_id for hit in outcome.hits]

    assert outcome.mode == HYBRID
    assert ranked[0] == agreed, ranked
    assert keyword_favourite in ranked
    # Orthogonal to the query and matching no keyword, so it is below the similarity
    # floor. Being the nearest of the unrelated documents is not a reason to return one.
    assert distant not in ranked


async def test_vectors_from_another_model_are_not_compared(pg_session: AsyncSession) -> None:
    """Two models are two spaces, and pgvector refuses to compare different widths
    outright. Filtering by model is what keeps a model migration from erroring or,
    worse, silently ranking across incomparable spaces."""

    article = await _article(pg_session, title="Rotterdam port strike")
    pg_session.add(
        ArticleEmbedding(
            processed_article_id=article,
            model="a-different-model",
            dimensions=5,
            embedding=[1.0, 0.0, 0.0, 0.0, 0.0],
        )
    )
    await pg_session.flush()

    hits = await vector_search(pg_session, embedding=[1.0, 0.0, 0.0], model=MODEL, limit=10, days=7)

    assert hits == []


async def test_an_unembedded_corpus_reports_degraded(pg_session: AsyncSession) -> None:
    """Real PostgreSQL, working provider, no vectors. The mode has to say so — this is
    exactly the state of production between deploying Task 3 and the first backfill
    finishing."""

    await _article(pg_session, title="Rotterdam port strike halts containers")

    outcome = await search(
        pg_session, query="port strike", limit=10, days=7, provider=StubProvider([1.0, 0.0, 0.0])
    )

    assert outcome.mode == DEGRADED
    assert len(outcome.hits) == 1


async def test_the_vector_half_respects_the_search_window(pg_session: AsyncSession) -> None:
    """Retention keeps 30 days but a search for the last 7 must not surface older
    articles just because their vectors are close."""

    await _article(pg_session, title="Ancient dockworker news", vector=[1.0, 0.0, 0.0], age_days=20)

    hits = await vector_search(pg_session, embedding=[1.0, 0.0, 0.0], model=MODEL, limit=10, days=7)

    assert hits == []


async def test_the_query_is_embedded_once_per_search(pg_session: AsyncSession) -> None:
    """Every search is a paid API call. Two would double the bill and the latency."""

    await _article(pg_session, title="Rotterdam port strike", vector=[1.0, 0.0, 0.0])
    provider = StubProvider([1.0, 0.0, 0.0])

    await search(pg_session, query="port strike", limit=10, days=7, provider=provider)

    assert len(provider.calls) == 1


async def test_a_query_with_no_good_answer_gets_no_answer(pg_session: AsyncSession) -> None:
    """Vector retrieval always has a nearest neighbour. Without a similarity floor,
    "recipe for sourdough bread" comes back with the ten least-unrelated procurement
    articles and the mode still reads `hybrid`.

    The floor is measured rather than guessed: against the golden corpus the two
    no-answer queries peak at 0.178 and 0.084 similarity, and the weakest true positive
    across the other ten is 0.390.
    """

    await _article(pg_session, title="Rotterdam port strike", vector=[1.0, 0.0, 0.0])

    hits = await vector_search(pg_session, embedding=[0.0, 1.0, 0.0], model=MODEL, limit=10, days=7)

    assert hits == []


async def test_the_floor_admits_a_genuine_match(pg_session: AsyncSession) -> None:
    """The other side of the same threshold: a near-but-not-identical vector is what a
    real paraphrase looks like, and excluding it would trade the no-answer case for
    every semantic match the feature exists to find."""

    article = await _article(pg_session, title="Rotterdam port strike", vector=[1.0, 0.4, 0.0])

    hits = await vector_search(pg_session, embedding=[1.0, 0.0, 0.0], model=MODEL, limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [article]
