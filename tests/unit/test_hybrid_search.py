"""Fusion, and the three ways semantic search can be unavailable.

Fusion is a pure function and is tested as one. The degradation paths are tested through
`search()` on SQLite, where vector retrieval genuinely cannot run — which makes it an
honest stand-in for a production instance with no embeddings yet. The hybrid path itself
needs real vectors and lives in tests/postgres/test_hybrid_search_pg.py.

The rule every one of these encodes: a search never returns an empty page because the
semantic half is unavailable, and never returns a 500.
"""

from datetime import datetime, timedelta
from itertools import count

import pytest
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.search.hybrid import DEGRADED, HYBRID, LEXICAL, RRF_K, fuse, search
from procuresignal.search.lexical import Hit
from sqlalchemy.ext.asyncio import AsyncSession

_sequence = count(1)


class StubProvider:
    name = "stub-embed"
    dimensions = 4

    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fails:
            raise RuntimeError("provider is down")
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


async def _article(session: AsyncSession, *, title: str, summary: str = "") -> int:
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
        summary=summary or f"A summary of {title}.",
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language="en",
        processed_at=now,
    )
    session.add(processed)
    await session.flush()
    return processed.id


def _hits(*ids: int) -> list[Hit]:
    """Descending scores, so position in the list is the rank."""

    return [Hit(processed_id=identifier, score=1.0 - index) for index, identifier in enumerate(ids)]


def test_agreement_between_retrievers_wins() -> None:
    """The property that makes fusion worth doing: a document both retrievers rank
    reasonably beats one that a single retriever ranks first.

    Here 7 is second on both lists and 1 is first on one, and 7 comes out ahead.
    """

    fused = fuse(_hits(1, 7), _hits(9, 7))

    assert [hit.processed_id for hit in fused][0] == 7


def test_scores_are_reciprocal_ranks_not_retriever_scores() -> None:
    """Averaging `ts_rank_cd` with cosine distance would weight by whichever scale
    happens to be larger, and normalising per query makes the weighting depend on the
    result set rather than on relevance. RRF needs only the positions.
    """

    fused = fuse(_hits(1, 2), [])

    assert fused[0].score == pytest.approx(1 / (RRF_K + 1))
    assert fused[1].score == pytest.approx(1 / (RRF_K + 2))


def test_a_strong_first_place_beats_two_middling_finishes() -> None:
    """Counterintuitive but deliberate: ranks (1, 3) score higher than ranks (2, 2).

    `1/(k+1) + 1/(k+3) > 2/(k+2)` because the reciprocal is convex, so RRF rewards one
    retriever being confident more than it rewards both being lukewarm. Anyone reading
    "agreement wins" as "averaging" will eventually try to make this case come out the
    other way; it is a property of the formula, not a defect in it.
    """

    fused = fuse(_hits(1, 2, 3), _hits(3, 2, 1))
    scores = {hit.processed_id: hit.score for hit in fused}

    assert scores[1] > scores[2]
    assert scores[3] > scores[2]
    assert scores[1] == pytest.approx(scores[3])


def test_a_document_found_by_both_sums_both_contributions() -> None:
    fused = fuse(_hits(4), _hits(4))

    assert len(fused) == 1
    assert fused[0].score == pytest.approx(2 / (RRF_K + 1))


def test_ties_resolve_the_same_way_every_time() -> None:
    """Two documents at rank 1 on different retrievers score identically. Left to set
    iteration the order would vary between runs, and a ranking that reshuffles on
    identical input is one nobody can debug or evaluate.
    """

    first = fuse(_hits(31), _hits(17))
    again = fuse(_hits(31), _hits(17))

    assert [hit.processed_id for hit in first] == [hit.processed_id for hit in again]
    assert first[0].score == pytest.approx(first[1].score)


def test_either_retriever_may_be_empty() -> None:
    assert [hit.processed_id for hit in fuse(_hits(5, 6), [])] == [5, 6]
    assert [hit.processed_id for hit in fuse([], _hits(5, 6))] == [5, 6]
    assert fuse([], []) == []


async def test_without_a_provider_the_mode_is_lexical(async_session: AsyncSession) -> None:
    """No key configured is a deployment choice, not a fault. Results are keyword-only
    and the response says so rather than implying semantic ranking ran."""

    wanted = await _article(async_session, title="Rotterdam port strike halts containers")

    outcome = await search(async_session, query="port strike", limit=10, days=7, provider=None)

    assert outcome.mode == LEXICAL
    assert [hit.processed_id for hit in outcome.hits] == [wanted]
    assert outcome.lexical_count == 1
    assert outcome.vector_count == 0


async def test_a_provider_that_fails_still_returns_results(async_session: AsyncSession) -> None:
    """The path that must never become a 500. A support question about bad results
    starts with which retriever produced them, so the failure is reported as a mode
    rather than swallowed into a normal-looking response."""

    wanted = await _article(async_session, title="Rotterdam port strike halts containers")
    provider = StubProvider(fails=True)

    outcome = await search(async_session, query="port strike", limit=10, days=7, provider=provider)

    assert outcome.mode == DEGRADED
    assert [hit.processed_id for hit in outcome.hits] == [wanted]


async def test_a_corpus_with_no_vectors_yet_is_degraded_not_hybrid(
    async_session: AsyncSession,
) -> None:
    """A provider is configured and working, but nothing has been embedded. Reporting
    `hybrid` here would claim a semantic contribution that did not happen."""

    await _article(async_session, title="Rotterdam port strike halts containers")
    provider = StubProvider()

    outcome = await search(async_session, query="port strike", limit=10, days=7, provider=provider)

    assert outcome.mode == DEGRADED
    assert outcome.vector_count == 0
    assert len(outcome.hits) == 1


async def test_an_empty_query_costs_nothing(async_session: AsyncSession) -> None:
    """Embedding a blank search box is a paid API call for a query that cannot match.
    The provider must not be reached at all."""

    await _article(async_session, title="Rotterdam port strike halts containers")
    provider = StubProvider()

    outcome = await search(async_session, query="   ", limit=10, days=7, provider=provider)

    assert outcome.hits == []
    assert outcome.mode == LEXICAL
    assert provider.calls == [], "the provider was billed for an empty query"


async def test_the_search_window_is_respected(async_session: AsyncSession) -> None:
    await _article(async_session, title="Rotterdam port strike halts containers")

    outcome = await search(async_session, query="port strike", limit=10, days=7, provider=None)
    assert len(outcome.hits) == 1

    stale = await async_session.get(NewsArticleProcessed, outcome.hits[0].processed_id)
    assert stale is not None
    stale.processed_at = datetime.utcnow() - timedelta(days=40)
    await async_session.commit()

    outcome = await search(async_session, query="port strike", limit=10, days=7, provider=None)
    assert outcome.hits == []


async def test_results_are_capped_at_the_requested_limit(async_session: AsyncSession) -> None:
    for index in range(6):
        await _article(async_session, title=f"Port strike update {index}")

    outcome = await search(async_session, query="port strike", limit=3, days=7, provider=None)

    assert len(outcome.hits) == 3


def test_the_modes_are_the_three_the_response_can_report() -> None:
    """Task 5 stores this string alongside every feedback row and Task 8 renders it,
    so the vocabulary is fixed here rather than spelled differently in each."""

    assert (HYBRID, LEXICAL, DEGRADED) == ("hybrid", "lexical", "degraded")
