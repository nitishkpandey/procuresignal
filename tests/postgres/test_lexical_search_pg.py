"""Full-text search against a real PostgreSQL, because none of it exists elsewhere.

`tsvector`, `setweight`, `ts_rank_cd`, `websearch_to_tsquery` and GIN have no SQLite
equivalent, so every claim this module makes about ranking is unverifiable on the
in-memory suite. Stemming, weighting and proximity are the three reasons to replace
`ILIKE` at all; if they are not asserted here they are not asserted anywhere.
"""

from datetime import datetime, timedelta
from itertools import count

import pytest
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.search.lexical import TEXT_SEARCH_CONFIGS, lexical_search
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

# Ranking tests deliberately give two articles the same title, so identity cannot come
# from the text the way a natural ingest hash would.
_sequence = count(1)


async def _article(
    session: AsyncSession,
    *,
    title: str,
    summary: str = "",
    snippet: str = "",
    language: str = "en",
    age_days: int = 0,
) -> int:
    when = datetime.utcnow() - timedelta(days=age_days)
    ordinal = next(_sequence)
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{ordinal}",
        title=title,
        description=snippet,
        content_snippet=snippet,
        article_url=f"https://example.com/{ordinal}",
        source_name="Test Source",
        published_at=when,
        language=language,
        ingested_at=when,
    )
    session.add(raw)
    await session.flush()

    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title=title,
        summary=summary,
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language=language,
        processed_at=when,
    )
    session.add(processed)
    await session.flush()
    return int(processed.id)


async def test_a_plural_query_finds_the_singular_article(pg_session: AsyncSession) -> None:
    """The concrete gap `ILIKE` leaves: `'%disruptions%'` does not match "disruption".

    Substring matching is directional — it finds longer words containing the query and
    misses shorter ones the query contains. Stemming makes both directions work.
    """

    wanted = await _article(pg_session, title="Supply chain disruption at Hamburg")

    hits = await lexical_search(pg_session, query="disruptions", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [wanted]


async def test_german_articles_are_stemmed_as_german(pg_session: AsyncSession) -> None:
    """`english` stemming applied to German produces wrong stems. The document's own
    language decides its configuration, and the caller's decides the query's."""

    wanted = await _article(
        pg_session,
        title="Hafenstreiks legen Rotterdam lahm",
        summary="Die Streiks dauern an.",
        language="de",
    )

    hits = await lexical_search(pg_session, query="Hafenstreik", limit=10, days=7, language="de")

    assert [hit.processed_id for hit in hits] == [wanted]


async def test_a_term_in_the_title_outranks_the_same_term_in_a_snippet(
    pg_session: AsyncSession,
) -> None:
    """What `setweight` A/B/C is for. Both articles match; only the order is at stake.

    The title match is inserted first so it is also the *older* of the two. Results tie
    on recency, so an assertion written the other way round would pass on the tiebreak
    alone and keep passing with the weighting removed.
    """

    in_title = await _article(pg_session, title="Tariff imposed on imported steel")
    in_snippet = await _article(
        pg_session,
        title="Weekly logistics roundup",
        summary="General news.",
        snippet="A tariff on imported steel was mentioned in passing.",
    )

    hits = await lexical_search(pg_session, query="tariff", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [in_title, in_snippet]
    assert hits[0].score > hits[1].score


async def test_terms_close_together_outrank_terms_far_apart(pg_session: AsyncSession) -> None:
    """An article about a port strike outranks one that mentions a port in one clause
    and a strike in another.

    The two summaries carry the same words in the same quantity and differ only in where
    `strike` sits, so neither document length nor term frequency can produce the
    ordering — and the close match is inserted first, making it the older of the two, so
    the recency tiebreak cannot produce it either.

    This does not, on its own, pin the choice of `ts_rank_cd` over `ts_rank`: PostgreSQL
    ranks AND queries by term distance in both. `ts_rank_cd` is chosen because it scores
    the density of a full cover rather than one pairwise distance, which is the property
    that keeps holding as queries grow past two terms.
    """

    adjacent = await _article(
        pg_session,
        title="Weekly roundup",
        summary=(
            "Rotterdam update: a port strike began today, according to operators "
            "familiar with terminal scheduling."
        ),
    )
    scattered = await _article(
        pg_session,
        title="Weekly roundup",
        summary=(
            "Rotterdam update: a port began today, according to operators "
            "familiar with terminal scheduling strike."
        ),
    )

    hits = await lexical_search(pg_session, query="port strike", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [adjacent, scattered]
    assert hits[0].score > hits[1].score


async def test_the_gin_index_can_serve_the_query(pg_session: AsyncSession) -> None:
    """A GIN index that the planner cannot use is a write cost with no read benefit.

    `enable_seqscan` is disabled for the check because the planner correctly prefers a
    sequential scan over a handful of test rows; what is being asserted is that an
    index scan is *available* for this predicate, which is what fails when the index is
    missing, is the wrong operator class, or does not match the expression.
    """

    await _article(pg_session, title="Rotterdam port strike halts containers")
    await pg_session.execute(text("SET LOCAL enable_seqscan = off"))

    plan = "\n".join(
        row
        for (row,) in await pg_session.execute(
            text(
                "EXPLAIN SELECT id FROM news_articles_processed "
                "WHERE search_vector @@ websearch_to_tsquery('english', 'port strike')"
            )
        )
    )

    assert "Index Scan" in plan, plan
    assert "idx_processed_search_vector" in plan, plan


async def test_document_and_query_stemming_use_the_same_configurations(
    pg_session: AsyncSession,
) -> None:
    """The mapping lives twice — in the migration that builds the column and in the
    module that builds the query — because a migration importing live application code
    rewrites its own history the next time that code is refactored.

    Two copies that disagree is a silent failure: documents stemmed one way, queries
    another, and a search that quietly returns less. This is the check that makes the
    duplication safe.
    """

    expression = await pg_session.scalar(
        text(
            "SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d "
            "JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
            "WHERE d.adrelid = 'news_articles_processed'::regclass AND a.attname = 'search_vector'"
        )
    )

    assert expression is not None, "search_vector is not a generated column"
    for configuration in TEXT_SEARCH_CONFIGS.values():
        assert configuration in expression, f"the migration does not stem with {configuration}"
    assert "simple" in expression, "no fallback for languages PostgreSQL cannot stem"


async def test_punctuation_a_user_typed_is_not_a_syntax_error(pg_session: AsyncSession) -> None:
    """`to_tsquery` raises on a stray `&` or `!`, which surfaces to the user as a 500.

    `websearch_to_tsquery` treats them as text, so the worst outcome is no results.
    """

    await _article(pg_session, title="Rotterdam port strike halts containers")

    for query in ["port & strike", "port !!! strike", "strike | ", "port:*strike"]:
        assert await lexical_search(pg_session, query=query, limit=10, days=7) is not None


async def test_a_quoted_phrase_excludes_the_scattered_match(pg_session: AsyncSession) -> None:
    """Phrase search is a `websearch_to_tsquery` feature the old `ILIKE` had by
    accident and any hand-rolled tsquery builder would have lost."""

    adjacent = await _article(pg_session, title="A port strike halts containers")
    await _article(pg_session, title="Ports are busy and strikes are rare")

    hits = await lexical_search(pg_session, query='"port strike"', limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [adjacent]


async def test_an_exclusion_removes_the_unwanted_sense(pg_session: AsyncSession) -> None:
    procurement = await _article(pg_session, title="Dockworkers strike in Rotterdam")
    await _article(pg_session, title="Strike partnership announced by football clubs")

    hits = await lexical_search(pg_session, query="strike -football", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [procurement]


async def test_the_retention_window_and_limit_are_respected(pg_session: AsyncSession) -> None:
    recent = await _article(pg_session, title="Port strike begins", age_days=1)
    await _article(pg_session, title="Port strike ended", age_days=20)

    hits = await lexical_search(pg_session, query="port strike", limit=10, days=7)
    assert [hit.processed_id for hit in hits] == [recent]

    await _article(pg_session, title="Port strike spreads", age_days=2)
    assert len(await lexical_search(pg_session, query="port strike", limit=1, days=7)) == 1
