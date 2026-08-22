"""Lexical search: query preparation, and the SQLite fallback path.

The PostgreSQL behaviour that matters — stemming, weighting, proximity, index use —
cannot be observed on SQLite and is verified in tests/postgres/test_lexical_search_pg.py.
What is checked here is the part that must hold on every dialect: a query with nothing
searchable in it returns nothing, and development on SQLite keeps working.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.models import NewsArticleProcessed, NewsArticleRaw
from procuresignal.search.lexical import Hit, build_tsquery, lexical_search, text_search_config
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("port strike", "port strike"),
        ("  port   strike  ", "port strike"),
        ('"port strike"', '"port strike"'),
        ("strike -football", "strike -football"),
        ("semiconductor & tariffs", "semiconductor & tariffs"),
        ("Rotterdam:*", "Rotterdam:*"),
    ],
)
def test_searchable_input_reaches_postgres_unmangled(raw: str, expected: str) -> None:
    """`websearch_to_tsquery` is the parser, so this must not try to be one.

    Quoted phrases and `-exclusions` are features the user gets for free, and a stray
    `&` or `:*` is text rather than a syntax error — which is the entire reason
    `websearch_to_tsquery` is used instead of `to_tsquery`. Escaping here would break
    the first two and would not be needed for the third.
    """

    assert build_tsquery(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "!!!", "...", '""', "-", "  ??  "])
def test_a_query_with_nothing_to_search_for_is_empty(raw: str) -> None:
    """The empty case is the one that has to be caught before it reaches SQL.

    On PostgreSQL an empty tsquery matches nothing, but on the SQLite path the same
    input becomes `ILIKE '%%'`, which matches every article in the retention window.
    Two dialects disagreeing about what "no query" means is how a blank search box
    returns the entire corpus.
    """

    assert build_tsquery(raw) == ""


def test_languages_postgres_cannot_stem_fall_back_rather_than_guess() -> None:
    """`english` stemming applied to Polish produces wrong stems, which is worse than
    none. PostgreSQL 15 ships no configuration for pl, ja, zh or ko."""

    assert text_search_config("de") == "german"
    assert text_search_config("en") == "english"
    assert text_search_config("pl") == "simple"
    assert text_search_config("ja") == "simple"
    assert text_search_config("unknown") == "simple"


def test_language_tags_carry_a_region_suffix() -> None:
    """Browsers send `de-DE`, not `de`, and the API passes the header through."""

    assert text_search_config("de-DE") == "german"
    assert text_search_config("EN-GB") == "english"


async def _article(
    session: AsyncSession,
    *,
    title: str,
    summary: str,
    snippet: str = "",
    age_days: int = 0,
) -> int:
    """One raw/processed pair, as the enrichment pipeline would leave it."""

    when = datetime.utcnow() - timedelta(days=age_days)
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{title}-{age_days}",
        title=title,
        description=snippet,
        content_snippet=snippet,
        article_url=f"https://example.com/{abs(hash(title))}",
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
        summary=summary,
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language="en",
        processed_at=when,
    )
    session.add(processed)
    await session.flush()
    return int(processed.id)


async def test_sqlite_development_still_finds_articles(async_session: AsyncSession) -> None:
    """Contributors run on SQLite. A search that only works in CI is a search nobody
    can develop against."""

    wanted = await _article(
        async_session, title="Rotterdam port strike halts containers", summary="Dockworkers."
    )
    await _article(async_session, title="Quarterly earnings report", summary="Unrelated.")

    hits = await lexical_search(async_session, query="port strike", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [wanted]
    assert isinstance(hits[0], Hit)


async def test_a_title_match_outranks_a_body_match(async_session: AsyncSession) -> None:
    """The same ordering PostgreSQL's setweight A/B produces, so switching dialects
    does not silently reshuffle results."""

    in_body = await _article(
        async_session, title="Logistics update", summary="A tariff review is under way."
    )
    in_title = await _article(async_session, title="Tariff review announced", summary="Details.")

    hits = await lexical_search(async_session, query="tariff", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [in_title, in_body]
    assert hits[0].score > hits[1].score


async def test_an_empty_query_returns_nothing_rather_than_everything(
    async_session: AsyncSession,
) -> None:
    await _article(async_session, title="Rotterdam port strike", summary="Dockworkers.")

    assert await lexical_search(async_session, query="   ", limit=10, days=7) == []
    assert await lexical_search(async_session, query="!!!", limit=10, days=7) == []


async def test_results_outside_the_window_are_excluded(async_session: AsyncSession) -> None:
    recent = await _article(async_session, title="Port strike begins", summary="Now.", age_days=1)
    await _article(async_session, title="Port strike ended", summary="Long ago.", age_days=20)

    hits = await lexical_search(async_session, query="port strike", limit=10, days=7)

    assert [hit.processed_id for hit in hits] == [recent]


async def test_limit_is_applied(async_session: AsyncSession) -> None:
    for index in range(5):
        await _article(async_session, title=f"Port strike {index}", summary="Dockworkers.")

    hits = await lexical_search(async_session, query="port strike", limit=2, days=7)

    assert len(hits) == 2
