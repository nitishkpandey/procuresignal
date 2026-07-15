import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.procuresignal.models import (
    Base,
    NewsRetrievalCircuit,
    NewsRetrievalRun,
    NewsRetrievalSourceOutcome,
)
from shared.procuresignal.retrieval.audit import RetrievalAuditRepository, run_candidate_statement
from shared.procuresignal.retrieval.base import FetchFailureCode


def test_postgresql_claim_candidate_uses_skip_locked() -> None:
    sql = str(
        run_candidate_statement(datetime(2026, 7, 13, 12), skip_locked=True).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "FOR UPDATE SKIP LOCKED" in sql


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def test_two_sessions_claim_run_once_and_stale_lease_recovers(sessions) -> None:
    now = datetime(2026, 7, 13, 12)
    async with sessions() as setup:
        setup.add(
            NewsRetrievalRun(run_key="run", status="pending", registry_version="v1", started_at=now)
        )
        await setup.commit()
    async with sessions() as one, sessions() as two:
        first = await RetrievalAuditRepository(one).claim_run("worker-1", now)
        second = await RetrievalAuditRepository(two).claim_run("worker-2", now)
        assert first is not None
        assert second is None
        recovered = await RetrievalAuditRepository(two).claim_run(
            "worker-2", now + timedelta(minutes=66)
        )
        assert recovered is not None


async def test_concurrent_sqlite_claim_race_has_one_owner(sessions) -> None:
    now = datetime(2026, 7, 13, 12)
    async with sessions() as setup:
        setup.add(
            NewsRetrievalRun(
                run_key="race", status="pending", registry_version="v1", started_at=now
            )
        )
        await setup.commit()
    async with sessions() as one, sessions() as two:
        results = await asyncio.gather(
            RetrievalAuditRepository(one).claim_run("one", now),
            RetrievalAuditRepository(two).claim_run("two", now),
        )
        assert sum(result is not None for result in results) == 1


async def test_run_completion_is_owner_scoped(sessions) -> None:
    now = datetime(2026, 7, 13, 12)
    async with sessions() as session:
        run = NewsRetrievalRun(
            run_key="owned",
            status="running",
            registry_version="v1",
            started_at=now,
            lease_owner="owner",
            lease_expires_at=now + timedelta(minutes=65),
        )
        session.add(run)
        await session.commit()
        repo = RetrievalAuditRepository(session)
        assert not await repo.complete_run(run.id, "stale", now=now)
        assert await repo.complete_run(run.id, "owner", now=now)


async def test_source_claim_is_atomic_and_failure_details_are_sanitized(sessions) -> None:
    now = datetime(2026, 7, 13, 12)
    async with sessions() as setup:
        run = NewsRetrievalRun(
            run_key="run", status="running", registry_version="v1", started_at=now
        )
        setup.add(run)
        await setup.commit()
        run_id = run.id
    async with sessions() as one, sessions() as two:
        assert await RetrievalAuditRepository(one).claim_source(run_id, "source", "worker-1", now)
        assert not await RetrievalAuditRepository(two).claim_source(
            run_id, "source", "worker-2", now
        )
        assert not await RetrievalAuditRepository(two).fail_source(
            run_id, "source", "worker-2", FetchFailureCode.NETWORK_ERROR, now=now
        )
        assert await RetrievalAuditRepository(one).fail_source(
            run_id,
            "source",
            "worker-1",
            FetchFailureCode.NETWORK_ERROR,
            "secret response body / token=abc",
            now=now,
        )
        outcome = await one.scalar(
            select(NewsRetrievalSourceOutcome).where(NewsRetrievalSourceOutcome.run_id == run_id)
        )
        assert outcome is not None
        assert outcome.failure_code == "network_error"
        assert outcome.outcome_detail is None


async def test_source_stale_lease_reclaim_and_stale_owner_cannot_complete(sessions) -> None:
    now = datetime(2026, 7, 13, 12)
    async with sessions() as session:
        run = NewsRetrievalRun(
            run_key="run", status="running", registry_version="v1", started_at=now
        )
        session.add(run)
        await session.commit()
        repo = RetrievalAuditRepository(session)
        assert await repo.claim_source(run.id, "source", "old", now)
        assert await repo.claim_source(run.id, "source", "new", now + timedelta(minutes=66))
        assert not await repo.complete_source(run.id, "source", "old", now=now)
        assert await repo.complete_source(run.id, "source", "new", now=now)


async def test_durable_circuit_opens_half_open_atomically_and_resets(sessions) -> None:
    now = datetime(2026, 7, 13, 12)
    async with sessions() as one, sessions() as two:
        first = RetrievalAuditRepository(one)
        for _ in range(5):
            await first.record_circuit_failure("source", now)
        circuit = await one.scalar(
            select(NewsRetrievalCircuit).where(NewsRetrievalCircuit.source_id == "source")
        )
        assert circuit is not None and circuit.open_until == now + timedelta(minutes=30)
        assert not await RetrievalAuditRepository(two).claim_circuit_probe("source", "two", now)
        due = now + timedelta(minutes=31)
        assert await first.claim_circuit_probe("source", "one", due)
        assert not await RetrievalAuditRepository(two).claim_circuit_probe("source", "two", due)
        assert await first.record_circuit_success("source", "one")
        await one.refresh(circuit)
        assert circuit.failure_count == 0 and circuit.open_until is None
