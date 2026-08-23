"""Hybrid retrieval: the one entry point the API calls.

Lexical and semantic retrieval answer different questions. Keyword search finds
"Hafenstreik" in a document that says "Hafenstreik" and nothing else; vector search finds
the article about a dock workers' walkout that never uses the word. Running both and
fusing them is worth more than tuning either.

Fusion is by reciprocal rank, not by combining scores. `ts_rank_cd` and cosine distance
are not on a comparable scale, and normalising them per query makes the weighting depend
on which documents happened to match rather than on relevance. RRF needs only the
positions, which are comparable by construction.

Degradation is explicit and reported. No provider, no vectors yet, or a provider that
raises all produce keyword results and a mode that says so — never an empty page, and
never a 500. Which retriever produced a result is the first question support asks.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.search.embeddings import EmbeddingProvider
from procuresignal.search.lexical import Hit, build_tsquery, lexical_search

logger = logging.getLogger(__name__)

# Both retrievers ran and the vector side contributed.
HYBRID = "hybrid"
# No provider is configured. Keyword-only by deployment choice, not by fault.
LEXICAL = "lexical"
# A provider is configured but produced nothing: it raised, or nothing is embedded yet.
DEGRADED = "degraded"

# The constant from the original RRF paper. Large enough that the difference between
# ranks 1 and 2 does not swamp a second retriever's opinion, small enough that deep
# results still fall away.
RRF_K = 60

# Fused from deeper lists than are returned: a document ranked 25th by keywords and 1st
# by vector should be able to reach the first page, which it cannot if each retriever
# only offers `limit` candidates.
CANDIDATE_MULTIPLIER = 2

# Vector retrieval always has a nearest neighbour: without a floor, "recipe for sourdough
# bread" returns the ten least-unrelated procurement articles and the mode still says
# hybrid. A system that always returns something is not better than one that returns
# nothing, it is just harder to catch being wrong.
#
# Measured against the golden corpus with text-embedding-3-small, not guessed. The two
# queries whose correct answer is nothing peak at 0.178 and 0.084 similarity; the weakest
# true positive across the other ten queries is 0.390. 0.25 sits in that gap with room on
# both sides. It is calibrated to this model and moves if the model does.
MINIMUM_SIMILARITY = 0.25


@dataclass(frozen=True)
class ScoredHit:
    processed_id: int
    score: float


@dataclass(frozen=True)
class SearchOutcome:
    """Results plus what produced them.

    `lexical_count` and `vector_count` are the candidate counts each retriever
    contributed, which is how "the vector half returned nothing" is distinguished from
    "the vector half returned the same things".
    """

    hits: list[ScoredHit]
    mode: str
    lexical_count: int
    vector_count: int


_VECTOR_SQL = text("""
    SELECT e.processed_article_id AS processed_id,
           1 - (e.embedding <=> CAST(:query_vector AS vector)) AS score
    FROM article_embeddings e
    JOIN news_articles_processed p ON p.id = e.processed_article_id
    WHERE e.model = :model
      AND p.processed_at >= :cutoff
      AND e.embedding <=> CAST(:query_vector AS vector) <= :maximum_distance
    ORDER BY e.embedding <=> CAST(:query_vector AS vector)
    LIMIT :limit
    """)


def fuse(lexical: Sequence[Hit], vector: Sequence[Hit], *, k: int = RRF_K) -> list[ScoredHit]:
    """Reciprocal rank fusion over two ranked lists.

    The reciprocal is convex, so ranks (1, 3) score above ranks (2, 2): RRF rewards one
    retriever being confident more than both being lukewarm. That is the formula
    working, not a rounding artefact, and it is pinned by a test.

    Ties are broken by which retriever found the document first and at what rank, then
    by id. Two documents at rank 1 on different retrievers score identically, and left
    to dictionary iteration their order would depend on insertion; a ranking that
    reshuffles on identical input cannot be debugged or evaluated.
    """

    contributions: dict[int, float] = defaultdict(float)
    provenance: dict[int, tuple[int, int]] = {}

    for source, hits in enumerate((lexical, vector)):
        for rank, hit in enumerate(hits, start=1):
            contributions[hit.processed_id] += 1.0 / (k + rank)
            provenance.setdefault(hit.processed_id, (source, rank))

    return [
        ScoredHit(processed_id=processed_id, score=score)
        for processed_id, score in sorted(
            contributions.items(),
            key=lambda item: (-item[1], provenance[item[0]], item[0]),
        )
    ]


async def vector_search(
    session: AsyncSession,
    *,
    embedding: Sequence[float],
    model: str,
    limit: int,
    days: int,
    minimum_similarity: float = MINIMUM_SIMILARITY,
) -> list[Hit]:
    """Nearest neighbours by cosine distance, within the search window.

    Filtered by model first: vectors from two embedding models occupy different spaces,
    and pgvector refuses to compare different widths outright. Then by similarity, so a
    query with no good answer gets no answer rather than the least-bad one.

    Returns nothing on SQLite, which has no vector type and no distance operators. That
    is the same signal as an unembedded corpus and is handled the same way.
    """

    dialect = session.bind.dialect.name if session.bind else ""
    if dialect != "postgresql":
        return []

    literal = "[" + ",".join(repr(float(value)) for value in embedding) + "]"
    result = await session.execute(
        _VECTOR_SQL,
        {
            "query_vector": literal,
            "model": model,
            "cutoff": datetime.utcnow() - timedelta(days=days),
            "maximum_distance": 1.0 - minimum_similarity,
            "limit": limit,
        },
    )
    return [Hit(processed_id=row.processed_id, score=float(row.score)) for row in result]


async def search(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    days: int,
    provider: EmbeddingProvider | None = None,
    language: str = "en",
) -> SearchOutcome:
    """Retrieve articles for a query, using whichever retrievers are available."""

    prepared = build_tsquery(query)
    if not prepared:
        # No searchable characters. Embedding it would be a paid API call for a query
        # that cannot match anything.
        return SearchOutcome(hits=[], mode=LEXICAL, lexical_count=0, vector_count=0)

    candidates = limit * CANDIDATE_MULTIPLIER
    lexical = await lexical_search(
        session, query=query, limit=candidates, days=days, language=language
    )

    if provider is None:
        return _outcome(lexical, [], mode=LEXICAL, limit=limit)

    try:
        embeddings = await provider.embed([prepared])
        vector = await vector_search(
            session,
            embedding=embeddings[0],
            model=provider.name,
            limit=candidates,
            days=days,
        )
    except Exception:
        # Deliberately broad. Any failure in the semantic half degrades the search
        # rather than failing it: a keyword result is worth more to the user than a
        # 500, and the mode tells support which half was unavailable.
        logger.warning("semantic retrieval failed, serving lexical results", exc_info=True)
        return _outcome(lexical, [], mode=DEGRADED, limit=limit)

    if not vector:
        # A working provider that matched nothing means the corpus is not embedded yet.
        # Calling that `hybrid` would claim a contribution that did not happen.
        return _outcome(lexical, [], mode=DEGRADED, limit=limit)

    return _outcome(lexical, vector, mode=HYBRID, limit=limit)


def _outcome(
    lexical: Sequence[Hit], vector: Sequence[Hit], *, mode: str, limit: int
) -> SearchOutcome:
    return SearchOutcome(
        hits=fuse(lexical, vector)[:limit],
        mode=mode,
        lexical_count=len(lexical),
        vector_count=len(vector),
    )
