"""Article embeddings: selection, batching, and everything that must not be written.

The vector column is shared by every ranking that reads it, so the interesting cases
here are the refusals — a provider that returns the wrong width, a provider that returns
too few rows, a tenant out of budget. A bad vector is not a failed search; it is a search
that keeps working and is quietly wrong.

The provider is a deterministic fake. The real client is exercised once, against a
stubbed transport, and never against the live API.
"""

from datetime import datetime, timedelta
from itertools import count

import httpx
import pytest
from procuresignal.enrichment.budget import DAILY_TOKEN_BUDGET, consume, remaining_tokens
from procuresignal.models import ArticleEmbedding, NewsArticleProcessed, NewsArticleRaw
from procuresignal.observability import metrics as metrics_module
from procuresignal.search.embeddings import (
    EmbeddingError,
    OpenAIEmbeddingProvider,
    embed_pending_articles,
    embedding_provider,
    pending_embedding_count,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_sequence = count(1)


class FakeProvider:
    """Deterministic vectors, and a record of how it was called.

    Fine in a test, never in production: a placeholder sharing a column with real
    vectors corrupts every ranking that reads it, invisibly.
    """

    def __init__(
        self, *, name: str = "fake-embed-1", dimensions: int = 4, emits: int | None = None
    ):
        self.name = name
        self.dimensions = dimensions
        self._emits = dimensions if emits is None else emits
        self.batches: list[int] = []
        self.texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        self.texts.extend(texts)
        return [[float(len(text) % 9)] * self._emits for text in texts]


class TruncatingProvider(FakeProvider):
    """Returns fewer vectors than it was given texts, which silently misaligns rows."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await super().embed(texts)
        return vectors[:-1]


async def _article(session: AsyncSession, *, title: str, age_days: int = 0) -> int:
    when = datetime.utcnow() - timedelta(days=age_days)
    ordinal = next(_sequence)
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{ordinal}",
        title=title,
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
        summary=f"A summary of {title}.",
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language="en",
        processed_at=when,
    )
    session.add(processed)
    await session.flush()
    return processed.id


async def _rows(session: AsyncSession) -> list[ArticleEmbedding]:
    result = await session.execute(select(ArticleEmbedding).order_by(ArticleEmbedding.id))
    return list(result.scalars().all())


async def test_each_article_gets_one_row_stamped_with_its_model(
    async_session: AsyncSession,
) -> None:
    """The model name is on every row because distances between two vector spaces are
    not comparable, and that failure is invisible without the column."""

    await _article(async_session, title="Rotterdam port strike")
    provider = FakeProvider()

    written = await embed_pending_articles(async_session, provider=provider)

    rows = await _rows(async_session)
    assert written == 1
    assert len(rows) == 1
    assert rows[0].model == "fake-embed-1"
    assert rows[0].dimensions == 4
    assert len(rows[0].embedding) == 4


async def test_rerunning_embeds_nothing_twice(async_session: AsyncSession) -> None:
    """Selection skips what the active model has already embedded, so the backfill is
    safe to schedule rather than something someone has to run once, carefully."""

    await _article(async_session, title="Rotterdam port strike")
    provider = FakeProvider()

    assert await embed_pending_articles(async_session, provider=provider) == 1
    assert await embed_pending_articles(async_session, provider=provider) == 0
    assert len(await _rows(async_session)) == 1


async def test_a_second_model_adds_rows_rather_than_overwriting(
    async_session: AsyncSession,
) -> None:
    """A model migration must not destroy the vectors currently serving queries."""

    article = await _article(async_session, title="Rotterdam port strike")

    await embed_pending_articles(async_session, provider=FakeProvider(name="old-model"))
    await embed_pending_articles(async_session, provider=FakeProvider(name="new-model"))

    rows = await _rows(async_session)
    assert {row.model for row in rows} == {"old-model", "new-model"}
    assert {row.processed_article_id for row in rows} == {article}


async def test_the_newest_articles_are_embedded_first(async_session: AsyncSession) -> None:
    """Ordering by id ascending is what starved the Phase 3 sanctions screener: it
    re-processed the same earliest rows forever while new ones were never reached.

    With a limit smaller than the backlog, the articles a user is most likely to search
    for are the ones that must get vectors.
    """

    for age in range(5):
        await _article(async_session, title=f"Article {age} days old", age_days=age)
    provider = FakeProvider()

    await embed_pending_articles(async_session, provider=provider, limit=2)

    embedded = {row.processed_article_id for row in await _rows(async_session)}
    newest = (
        (
            await async_session.execute(
                select(NewsArticleProcessed.id)
                .order_by(NewsArticleProcessed.processed_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    assert embedded == set(newest)


async def test_texts_are_sent_in_batches(async_session: AsyncSession) -> None:
    """One request per article is the same spend with an order of magnitude more
    latency and far more chances to be rate limited."""

    for index in range(5):
        await _article(async_session, title=f"Article {index}")
    provider = FakeProvider()

    await embed_pending_articles(async_session, provider=provider, limit=5, batch_size=2)

    assert provider.batches == [2, 2, 1]


async def test_the_embedded_text_carries_the_title_and_summary(
    async_session: AsyncSession,
) -> None:
    await _article(async_session, title="Rotterdam port strike")
    provider = FakeProvider()

    await embed_pending_articles(async_session, provider=provider)

    assert "Rotterdam port strike" in provider.texts[0]
    assert "A summary of Rotterdam port strike." in provider.texts[0]


async def test_a_vector_of_the_wrong_width_never_reaches_the_column(
    async_session: AsyncSession,
) -> None:
    """Mixing widths makes the whole column unqueryable: pgvector refuses to compare
    vectors of different dimensions, so one bad batch breaks every later search."""

    await _article(async_session, title="Rotterdam port strike")
    provider = FakeProvider(dimensions=4, emits=3)

    with pytest.raises(EmbeddingError):
        await embed_pending_articles(async_session, provider=provider)

    assert await _rows(async_session) == []


async def test_a_short_response_never_reaches_the_column(async_session: AsyncSession) -> None:
    """Vectors are matched to articles by position. One missing vector shifts every
    later article onto the wrong embedding, which no later check would catch."""

    await _article(async_session, title="First")
    await _article(async_session, title="Second")
    provider = TruncatingProvider()

    with pytest.raises(EmbeddingError):
        await embed_pending_articles(async_session, provider=provider)

    assert await _rows(async_session) == []


async def test_an_exhausted_budget_refuses_the_work(async_session: AsyncSession) -> None:
    """Embedding every article for every tenant is exactly the runaway the cap exists
    to stop, and the cap has to bind here as well as in enrichment."""

    await _article(async_session, title="Rotterdam port strike")
    await consume(async_session, tenant=None, tokens=DAILY_TOKEN_BUDGET, calls=1)
    provider = FakeProvider()
    before = metrics_module.LLM_BUDGET_REFUSALS.labels(tenant="__global__")._value.get()

    written = await embed_pending_articles(async_session, provider=provider)

    assert written == 0
    assert provider.batches == [], "the provider was called with no budget left"
    assert await _rows(async_session) == []
    assert metrics_module.LLM_BUDGET_REFUSALS.labels(tenant="__global__")._value.get() > before


async def test_successful_work_is_charged_to_the_budget(async_session: AsyncSession) -> None:
    await _article(async_session, title="Rotterdam port strike")

    await embed_pending_articles(async_session, provider=FakeProvider())

    assert await remaining_tokens(async_session, tenant=None) < DAILY_TOKEN_BUDGET


async def test_pending_count_is_what_is_left_to_embed(async_session: AsyncSession) -> None:
    """The freshness signal. Embeddings quietly stopping degrades search to keyword
    matching, which looks like worse results rather than like a broken pipeline."""

    for index in range(3):
        await _article(async_session, title=f"Article {index}")

    assert await pending_embedding_count(async_session, model="fake-embed-1") == 3

    await embed_pending_articles(async_session, provider=FakeProvider(), limit=2)

    assert await pending_embedding_count(async_session, model="fake-embed-1") == 1


async def test_articles_outside_the_retention_window_are_not_embedded(
    async_session: AsyncSession,
) -> None:
    """Retention drops them in days. Paying to embed them is spend with no reader."""

    await _article(async_session, title="Ancient news", age_days=90)

    assert await embed_pending_articles(async_session, provider=FakeProvider()) == 0


def test_without_a_key_there_is_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key means semantic search is off and retrieval degrades to lexical, reported
    honestly. It does not mean a hash-based placeholder in the vector column."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)

    assert embedding_provider() is None


def test_the_client_refuses_to_start_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)

    with pytest.raises(ValueError):
        OpenAIEmbeddingProvider()


async def test_the_request_openai_receives_names_the_model_and_dimensions() -> None:
    """The one test that touches the real client. It asserts the request shape against
    a stubbed transport, because the alternative is a test that bills someone."""

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1] * 1536}], "usage": {"total_tokens": 7}},
        )

    provider = OpenAIEmbeddingProvider(api_key="test-key", transport=httpx.MockTransport(handler))
    vectors = await provider.embed(["Rotterdam port strike"])

    assert vectors == [[0.1] * 1536]
    assert seen["url"] == "https://api.openai.com/v1/embeddings"
    assert seen["authorization"] == "Bearer test-key"
    assert seen["payload"] == {
        "model": "text-embedding-3-small",
        "input": ["Rotterdam port strike"],
        "dimensions": 1536,
    }


async def test_vectors_come_back_in_the_order_they_were_requested() -> None:
    """The API is documented to return `index`, not to preserve order. Trusting the
    order pairs the wrong vector with the wrong article, and every result stays
    plausible while being wrong."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [2.0] * 1536},
                    {"index": 0, "embedding": [1.0] * 1536},
                ],
                "usage": {"total_tokens": 9},
            },
        )

    provider = OpenAIEmbeddingProvider(api_key="test-key", transport=httpx.MockTransport(handler))

    assert await provider.embed(["first", "second"]) == [[1.0] * 1536, [2.0] * 1536]


def test_the_provider_name_is_the_model_identifier() -> None:
    """`name` is what every row is stamped with and what selection filters on, so it
    has to be the model identifier rather than a friendly label."""

    provider = OpenAIEmbeddingProvider(api_key="test-key")

    assert provider.name == "text-embedding-3-small"
    assert provider.dimensions == 1536
