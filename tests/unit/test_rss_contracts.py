from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from procuresignal.models import Base, NewsArticleRaw
from procuresignal.retrieval import FetchResult
from procuresignal.retrieval.catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from procuresignal.retrieval.providers.rss import RSSProvider
from procuresignal.retrieval.registry import (
    AdapterType,
    ProcurementDomain,
    SourceClass,
    SourceDefinition,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

FIXTURES = Path("tests/fixtures/retrieval")


class FixtureFetcher:
    def __init__(self, fixture: str) -> None:
        self.fixture = fixture
        self.calls: list[SourceDefinition] = []

    async def fetch(self, source: SourceDefinition) -> FetchResult:
        self.calls.append(source)
        return FetchResult(
            content=(FIXTURES / self.fixture).read_bytes(),
            content_type="application/xml",
            final_url=source.endpoint_url,
            status_code=200,
        )


def source(source_id: str) -> SourceDefinition:
    return next(item for item in SOURCE_REGISTRY.sources if item.source_id == source_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_id", "fixture", "domain", "language"),
    [
        ("ecb_press", "ecb_press.xml", "regulation", "de"),
        ("eu_commission_press", "eu_commission_press.xml", "sanctions", "fr"),
    ],
)
async def test_registry_source_contract_populates_provenance_and_primary_domain(
    source_id: str, fixture: str, domain: str, language: str
) -> None:
    definition = source(source_id)
    fetcher = FixtureFetcher(fixture)

    articles = await RSSProvider(definition, fetcher).fetch_articles(["not-a-domain"])

    assert fetcher.calls == [definition]
    assert articles
    first = articles[0]
    assert first.query_group == domain
    assert first.source_id == definition.source_id
    assert first.source_class == definition.source_class.value
    assert first.source_domains == tuple(sorted(item.value for item in definition.domains))
    assert first.source_countries == definition.countries
    assert first.registry_version == REGISTRY_VERSION
    assert first.source_name == definition.display_name
    assert first.source_url == definition.homepage_url
    assert first.language == language
    assert first.published_at.tzinfo is None
    assert first.retrieved_at is not None
    assert first.retrieved_at.tzinfo is None


@pytest.mark.asyncio
async def test_rss_text_is_sanitized_bounded_and_relative_url_is_canonicalized() -> None:
    definition = replace(source("ecb_press"), item_limit=1)
    article = (await RSSProvider(definition, FixtureFetcher("ecb_press.xml")).fetch_articles([]))[0]

    assert article.description == "Neue Leitlinien für Banken."
    assert "script" not in (article.description or "").lower()
    assert (
        article.canonical_url
        == "https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.pr260714~abc.en.html"
    )
    assert article.provider_article_id == "ecb-2026-07-14-de"
    assert article.published_at == datetime(2026, 7, 14, 16, 30)
    assert len(article.title) <= 500
    assert len(article.description or "") <= 2_000


@pytest.mark.asyncio
async def test_atom_missing_description_and_future_timestamp_are_safe() -> None:
    before = datetime.utcnow()
    articles = await RSSProvider(
        source("eu_commission_press"), FixtureFetcher("eu_commission_press.xml")
    ).fetch_articles(["commodities"])
    after = datetime.utcnow()

    assert articles[0].published_at == datetime(2026, 7, 14, 8, 15)
    assert articles[0].description == "La Commission protège les chaînes d'approvisionnement."
    assert articles[1].description is None
    assert before <= articles[1].published_at <= after


@pytest.mark.asyncio
async def test_rss_timestamps_roundtrip_through_naive_database_columns() -> None:
    raw = (
        await RSSProvider(source("ecb_press"), FixtureFetcher("ecb_press.xml")).fetch_articles([])
    )[0]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        stored = NewsArticleRaw(
            provider=raw.provider,
            provider_article_id=raw.provider_article_id,
            query_group=raw.query_group,
            ingest_hash="rss-naive-roundtrip",
            title=raw.title,
            description=raw.description,
            content_snippet=raw.content_snippet,
            article_url=raw.article_url,
            canonical_url=raw.canonical_url,
            source_name=raw.source_name,
            source_url=raw.source_url,
            published_at=raw.published_at,
            retrieved_at=raw.retrieved_at,
            language=raw.language,
            ingested_at=datetime.utcnow(),
        )
        session.add(stored)
        await session.commit()
        await session.refresh(stored)
        assert stored.published_at == raw.published_at
        assert stored.retrieved_at == raw.retrieved_at
        assert stored.published_at.tzinfo is None
        assert stored.retrieved_at is not None and stored.retrieved_at.tzinfo is None
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture", "domain", "expected_url"),
    [
        (
            "europe_logistics.xml",
            ProcurementDomain.LOGISTICS,
            "https://logistics.example/story?id=7",
        ),
        (
            "europe_commodities.xml",
            ProcurementDomain.COMMODITIES,
            "https://commodities.example/articles/metals;daily?edition=eu",
        ),
    ],
)
async def test_rss_and_atom_formats_map_each_source_to_its_domain(
    fixture: str, domain: ProcurementDomain, expected_url: str
) -> None:
    definition = SourceDefinition(
        source_id=f"europe_{domain.value}",
        display_name=f"Europe {domain.value}",
        homepage_url=f"https://{domain.value}.example/",
        endpoint_url=f"https://{domain.value}.example/feed",
        adapter=AdapterType.RSS,
        source_class=SourceClass.INDUSTRY,
        domains=frozenset({domain}),
        countries=("eu",),
        languages=("en",),
        poll_minutes=60,
        item_limit=10,
        expected_content_types=("application/xml",),
        allowed_hosts=(f"{domain.value}.example",),
        trust_seed=0.7,
        license_note="Recorded contract fixture.",
    )
    article = (await RSSProvider(definition, FixtureFetcher(fixture)).fetch_articles([]))[0]
    assert article.query_group == domain.value
    assert article.canonical_url == expected_url


def test_dead_feed_table_is_removed() -> None:
    assert not hasattr(RSSProvider, "FEEDS")
