"""Tests for the persistent, versioned enrichment cache."""

import pytest
from procuresignal.enrichment.cache import EnrichmentCache
from procuresignal.enrichment.output_parser import EnrichmentOutput
from procuresignal.models import Base, EnrichmentCacheEntry
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as database_session:
        yield database_session
    await engine.dispose()


@pytest.fixture
def output() -> EnrichmentOutput:
    return EnrichmentOutput(
        summary="Bosch expanded semiconductor production capacity in Germany.",
        category="manufacturing",
        signal_tags=["expansion"],
        detected_suppliers=["Bosch"],
        detected_regions=["Germany"],
        detected_categories=["semiconductors"],
    )


@pytest.mark.asyncio
async def test_cache_round_trip_increments_and_persists_hit_count(
    session: AsyncSession, output: EnrichmentOutput
) -> None:
    cache = EnrichmentCache()
    key = {"fingerprint": "fingerprint-1", "policy_version": "p1", "taxonomy_version": "t1"}

    await cache.put(session, **key, output=output, original_method="deterministic")
    first = await cache.get(session, **key)
    second = await cache.get(session, **key)
    await session.flush()

    assert first is not None and first.output == output
    assert first.original_method == "deterministic"
    assert second == first
    entry = await session.scalar(select(EnrichmentCacheEntry))
    assert entry is not None
    assert entry.hit_count == 2


@pytest.mark.asyncio
async def test_cache_version_mismatch_is_a_miss(
    session: AsyncSession, output: EnrichmentOutput
) -> None:
    cache = EnrichmentCache()
    await cache.put(
        session,
        fingerprint="fingerprint-1",
        policy_version="p1",
        taxonomy_version="t1",
        output=output,
        original_method="llm",
    )

    assert (
        await cache.get(
            session,
            fingerprint="fingerprint-1",
            policy_version="p2",
            taxonomy_version="t1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_corrupt_cache_payload_is_miss_without_hit_increment(session: AsyncSession) -> None:
    entry = EnrichmentCacheEntry(
        content_fingerprint="corrupt",
        policy_version="p1",
        taxonomy_version="t1",
        payload={"summary": "short"},
        original_method="llm",
    )
    session.add(entry)
    await session.flush()

    result = await EnrichmentCache().get(
        session, fingerprint="corrupt", policy_version="p1", taxonomy_version="t1"
    )

    assert result is None
    assert entry.hit_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["cached", "skipped", "", "LLM"])
async def test_cache_rejects_invalid_original_methods(
    session: AsyncSession, output: EnrichmentOutput, method: str
) -> None:
    with pytest.raises(ValueError, match="original_method"):
        await EnrichmentCache().put(
            session,
            fingerprint="fingerprint-1",
            policy_version="p1",
            taxonomy_version="t1",
            output=output,
            original_method=method,
        )


@pytest.mark.asyncio
async def test_put_updates_existing_key_without_committing(
    session: AsyncSession, output: EnrichmentOutput
) -> None:
    cache = EnrichmentCache()
    key = {"fingerprint": "fingerprint-1", "policy_version": "p1", "taxonomy_version": "t1"}
    await cache.put(session, **key, output=output, original_method="llm")
    replacement = output.model_copy(update={"summary": "A sufficiently long replacement summary."})

    await cache.put(session, **key, output=replacement, original_method="deterministic")

    entries = (await session.scalars(select(EnrichmentCacheEntry))).all()
    assert len(entries) == 1
    assert entries[0].payload == replacement.model_dump(mode="json")
    assert entries[0].original_method == "deterministic"
    assert session.in_transaction()


def test_enrichment_output_rejects_corrupt_fixture() -> None:
    with pytest.raises(ValidationError):
        EnrichmentOutput.model_validate({"summary": "short"})
