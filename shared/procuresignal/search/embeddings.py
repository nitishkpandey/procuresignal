"""Article embeddings: the semantic half of hybrid retrieval.

Two rules shape this module.

Embeddings are never faked into the production column. A hash-based placeholder sharing
a column with real vectors silently corrupts every ranking that reads it, and nothing
about the resulting scores looks wrong. No key means `embedding_provider()` returns
None, semantic search is off, and retrieval degrades to lexical and says so.

Nothing is written that has not been checked. A vector of the wrong width makes the
whole column unqueryable — pgvector refuses to compare vectors of different dimensions —
and a response with fewer vectors than inputs pairs every later article with the wrong
embedding. Both are rejected before the insert.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import Select, and_, desc, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from procuresignal.config.secrets import get_secret
from procuresignal.enrichment.budget import (
    GLOBAL_BUCKET,
    BudgetExceededError,
    consume,
    consume_overage,
    within_budget,
)
from procuresignal.jobs.retention import RetentionPolicy
from procuresignal.models import ArticleEmbedding, NewsArticleProcessed
from procuresignal.observability.metrics import record_budget_refusal

# One request per article is the same spend with an order of magnitude more latency and
# far more chances to be rate limited. OpenAI accepts well over this per request; the
# ceiling here is how much work one failed request throws away.
EMBEDDING_BATCH_SIZE = 100


class EmbeddingError(RuntimeError):
    """A provider returned something that must not reach the vector column.

    Distinct from a transport failure on purpose: hybrid retrieval catches this and
    degrades to lexical rather than failing the search.
    """


class EmbeddingProvider(Protocol):
    """What hybrid retrieval and the backfill need from an embedding model.

    `name` is the model identifier, not a label: it is stamped on every row and is what
    selection filters on.
    """

    name: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _retryable(error: BaseException) -> bool:
    """Retry what can succeed later, and nothing else.

    A 401 retried three times is three failures and a delay before the same error; a 400
    will never succeed. Rate limiting and server errors are the cases where waiting is
    the correct response.
    """

    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429 or error.response.status_code >= 500
    return False


class OpenAIEmbeddingProvider:
    """`text-embedding-3-small` at 1536 dimensions.

    An order of magnitude cheaper than `-3-large` for a 30-day corpus of news snippets,
    where the ranking difference does not justify the cost.
    """

    BASE_URL = "https://api.openai.com/v1/embeddings"
    MODEL = "text-embedding-3-small"
    DIMENSIONS = 1536

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        # Through the resolver so OPENAI_API_KEY_FILE and /run/secrets work.
        self.api_key = api_key or get_secret("OPENAI_API_KEY", default="")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")

        self.name: str = model or os.getenv("OPENAI_EMBEDDING_MODEL") or self.MODEL
        self.dimensions: int = dimensions or int(
            os.getenv("OPENAI_EMBEDDING_DIMENSIONS") or self.DIMENSIONS
        )
        self.timeout = timeout
        self.total_tokens_used = 0
        # Only ever set by tests, which assert the request shape rather than send one.
        self._transport = transport

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_retryable),
    )
    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.name, "input": texts, "dimensions": self.dimensions}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            response = await client.post(self.BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        self.total_tokens_used += int(usage.get("total_tokens") or 0)

        # Sorted by `index` rather than trusted in order. The API documents the field;
        # relying on the order would pair the wrong vector with the wrong article, and
        # every result would stay plausible while being wrong.
        ordered = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        return [[float(value) for value in item["embedding"]] for item in ordered]


def embedding_provider() -> EmbeddingProvider | None:
    """The configured provider, or None when there is no key.

    None is a supported state, not an error: semantic search is off and retrieval says
    so. The alternative — a placeholder vector — is a search that keeps working and is
    quietly wrong.
    """

    if not get_secret("OPENAI_API_KEY", default=""):
        return None
    return OpenAIEmbeddingProvider()


def _cutoff(days: int | None) -> datetime:
    # Retention's own window, so the two cannot drift apart: paying to embed an article
    # that is about to be pruned is spend with no reader.
    window = RetentionPolicy().processed_days if days is None else days
    return datetime.utcnow() - timedelta(days=window)


def _pending(model: str, cutoff: datetime) -> Select[Any]:
    already_embedded = exists().where(
        and_(
            ArticleEmbedding.processed_article_id == NewsArticleProcessed.id,
            ArticleEmbedding.model == model,
        )
    )
    return (
        select(NewsArticleProcessed)
        .where(NewsArticleProcessed.processed_at >= cutoff)
        .where(~already_embedded)
    )


def _text_for(article: NewsArticleProcessed) -> str:
    return f"{article.normalized_title}\n\n{article.summary}".strip()


def _estimate_tokens(texts: list[str]) -> int:
    """Roughly four characters per token, which is close enough for a cap.

    The cap exists to stop a runaway, not to produce an invoice. Being approximate in
    the conservative direction costs a little headroom and never overspends.
    """

    return max(1, sum(len(text) for text in texts) // 4)


async def pending_embedding_count(
    session: AsyncSession, *, model: str, days: int | None = None
) -> int:
    """Articles in the retention window with no vector under this model.

    The freshness signal. Embeddings quietly stopping degrades search to keyword
    matching, which reads as worse results rather than as a broken pipeline — the same
    failure shape as ingestion returning nothing while every health check stays green.
    """

    subquery = _pending(model, _cutoff(days)).subquery()
    total = await session.scalar(select(func.count()).select_from(subquery))
    return int(total or 0)


def _reject_unusable(vectors: list[list[float]], texts: list[str], dimensions: int) -> None:
    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"provider returned {len(vectors)} vectors for {len(texts)} texts: "
            "positions would no longer identify articles"
        )
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError(
                f"provider returned a {len(vector)}-dimension vector, expected {dimensions}: "
                "mixed widths make the column unqueryable"
            )


async def embed_pending_articles(
    session: AsyncSession,
    *,
    provider: EmbeddingProvider,
    limit: int = 200,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    days: int | None = None,
) -> int:
    """Embed articles that have no vector under the active model. Returns how many.

    Newest first. Ordering by id ascending is what starved the Phase 3 sanctions
    screener — it re-processed the same earliest rows forever and never reached the
    new ones — and here it would mean the articles most likely to be searched are the
    ones without vectors.
    """

    articles = list(
        (
            await session.execute(
                _pending(provider.name, _cutoff(days))
                .order_by(desc(NewsArticleProcessed.processed_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    written = 0
    for start in range(0, len(articles), batch_size):
        batch = articles[start : start + batch_size]
        texts = [_text_for(article) for article in batch]
        estimate = _estimate_tokens(texts)

        if not await within_budget(session, tenant=None, tokens=estimate):
            # A hard stop, matching enrichment: refusing the call is the point, and
            # what is left unembedded is visible in pending_embedding_count.
            record_budget_refusal(GLOBAL_BUCKET)
            break

        vectors = await provider.embed(texts)

        # Charged before the vectors are checked, because the call has already been
        # billed by the time they can be. A batch rejected below loses its accounting
        # when the transaction rolls back, understating spend by at most one batch.
        try:
            await consume(session, tenant=None, tokens=estimate)
        except BudgetExceededError:
            # The call happened as the budget ran out. Record it and refuse the next
            # one rather than lose what this one cost.
            await consume_overage(session, tenant=None, tokens=estimate)

        _reject_unusable(vectors, texts, provider.dimensions)

        session.add_all(
            [
                ArticleEmbedding(
                    processed_article_id=article.id,
                    model=provider.name,
                    dimensions=provider.dimensions,
                    embedding=vector,
                )
                for article, vector in zip(batch, vectors)
            ]
        )
        await session.commit()
        written += len(batch)

    return written
