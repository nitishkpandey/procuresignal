"""Lexical retrieval over PostgreSQL full-text search.

Replaces `ILIKE '%term%'`, which matches substrings rather than words: it finds
"disruptions" for the query "disruption" and misses it for "disruptions", ranks nothing,
and cannot tell a headline from a footnote. Stemming, `setweight` and `ts_rank_cd` fix
all three.

SQLite keeps the substring behaviour so development and the in-memory suite still work.
Everything the ranking claims is verified against a real PostgreSQL in
tests/postgres/test_lexical_search_pg.py, because none of it exists on SQLite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleProcessed, NewsArticleRaw


@dataclass(frozen=True)
class Hit:
    """One retrieved article and its retriever-native score.

    The score orders results within this retriever and is not comparable across
    retrievers: `ts_rank_cd` and cosine distance are different scales. Hybrid retrieval
    fuses on rank for exactly that reason.
    """

    processed_id: int
    score: float


# Kept in step with migrations/versions/r3s4t5_article_fts.py, which stems the documents.
# pl, ja, zh and ko appear in LanguageDetector.SUPPORTED_LANGUAGES but PostgreSQL 15
# ships no stemmer for them, and a wrong stemmer loses more than no stemmer does.
TEXT_SEARCH_CONFIGS = {
    "en": "english",
    "de": "german",
    "fr": "french",
    "es": "spanish",
    "it": "italian",
    "nl": "dutch",
    "pt": "portuguese",
    "ru": "russian",
}
FALLBACK_CONFIG = "simple"

_SEARCHABLE = re.compile(r"\w", re.UNICODE)

# The same parsed query is needed for the two match conditions and for the rank, and a
# CTE holding it would be materialised, hiding the value from the planner and with it
# the GIN index. Repeating a cheap immutable call is the cost of an index scan.
_TSQUERY = "websearch_to_tsquery(CAST(:configuration AS regconfig), :query)"

_FULL_TEXT_SQL = text(f"""
    SELECT p.id AS processed_id,
           ts_rank_cd(p.search_vector || r.search_vector, {_TSQUERY}) AS score
    FROM news_articles_processed p
    JOIN news_articles_raw r ON r.id = p.raw_article_id
    WHERE p.processed_at >= :cutoff
      AND (p.search_vector @@ {_TSQUERY} OR r.search_vector @@ {_TSQUERY})
    ORDER BY score DESC, p.processed_at DESC
    LIMIT :limit
    """)

# Field authority, mirroring the A/B/C weights the generated columns carry. Used only by
# the SQLite fallback, so that switching dialects does not reshuffle the top results.
_PROCESSED_FIELDS = (("normalized_title", 1.0), ("summary", 0.4))
_RAW_FIELDS = (("title", 1.0), ("description", 0.2), ("content_snippet", 0.2))
_FALLBACK_TOTAL = sum(weight for _, weight in _PROCESSED_FIELDS + _RAW_FIELDS)


def text_search_config(language: str) -> str:
    """The PostgreSQL text search configuration for a language tag.

    Accepts `de` and `de-DE` alike: the API takes the language from a client that sends
    the regional form.
    """

    return TEXT_SEARCH_CONFIGS.get(language.split("-")[0].strip().lower(), FALLBACK_CONFIG)


def build_tsquery(query: str) -> str:
    """Normalise user input for `websearch_to_tsquery`.

    Deliberately not an escaper. `websearch_to_tsquery` is the escaper — it is used
    precisely because it parses quoted phrases and `-exclusions` and cannot raise a
    syntax error on a stray `&` the way `to_tsquery` does, so escaping here would
    destroy two features to prevent a problem that no longer exists.

    What it does add is the empty case. An empty tsquery matches nothing on PostgreSQL,
    but the same input reaches the SQLite path as `ILIKE '%%'` and matches every article
    in the retention window. Returning `""` makes both dialects agree that a query with
    no searchable characters has no results.
    """

    collapsed = " ".join(query.split())
    return collapsed if _SEARCHABLE.search(collapsed) else ""


async def lexical_search(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    days: int,
    language: str = "en",
) -> list[Hit]:
    """Rank articles from the last `days` against `query`, best first.

    `language` configures the *query* side only; each document is stemmed with its own
    language, recorded when the generated column was built.
    """

    prepared = build_tsquery(query)
    if not prepared:
        return []

    cutoff = datetime.utcnow() - timedelta(days=days)
    dialect = session.bind.dialect.name if session.bind else ""
    if dialect == "postgresql":
        return await _full_text_search(session, prepared, cutoff, limit, language)
    return await _substring_search(session, prepared, cutoff, limit)


async def _full_text_search(
    session: AsyncSession,
    prepared: str,
    cutoff: datetime,
    limit: int,
    language: str,
) -> list[Hit]:
    result = await session.execute(
        _FULL_TEXT_SQL,
        {
            "configuration": text_search_config(language),
            "query": prepared,
            "cutoff": cutoff,
            "limit": limit,
        },
    )
    return [Hit(processed_id=row.processed_id, score=float(row.score)) for row in result]


async def _substring_search(
    session: AsyncSession,
    prepared: str,
    cutoff: datetime,
    limit: int,
) -> list[Hit]:
    """The pre-existing `ILIKE` behaviour, kept so SQLite development still works.

    No stemming, no proximity and no index — a development convenience, not a second
    implementation of ranking. Over-fetching before scoring mirrors what the search
    endpoint already did, since `ILIKE` cannot order by relevance in the database.
    """

    pattern = f"%{prepared}%"
    searched = [getattr(NewsArticleProcessed, name) for name, _ in _PROCESSED_FIELDS]
    searched += [getattr(NewsArticleRaw, name) for name, _ in _RAW_FIELDS]

    result = await session.execute(
        select(NewsArticleProcessed, NewsArticleRaw)
        .join(NewsArticleRaw, NewsArticleProcessed.raw_article_id == NewsArticleRaw.id)
        .where(NewsArticleProcessed.processed_at >= cutoff)
        .where(or_(*(column.ilike(pattern) for column in searched)))
        .order_by(desc(NewsArticleProcessed.processed_at))
        .limit(limit * 3)
    )

    needle = prepared.lower()

    def weight_of(row: object, fields: tuple[tuple[str, float], ...]) -> float:
        return sum(
            weight for name, weight in fields if needle in (getattr(row, name) or "").lower()
        )

    hits = []
    for processed, raw in result.all():
        score = weight_of(processed, _PROCESSED_FIELDS) + weight_of(raw, _RAW_FIELDS)
        if score:
            hits.append(Hit(processed_id=int(processed.id), score=score / _FALLBACK_TOTAL))

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:limit]
