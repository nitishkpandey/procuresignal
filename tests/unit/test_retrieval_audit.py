from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.procuresignal.models import Base, NewsRetrievalRun, NewsRetrievalSourceOutcome
from shared.procuresignal.retrieval.audit import RetrievalAuditRepository, run_candidate_statement


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
        first = await RetrievalAuditRepository(one).claim_run("worker-1", now, timedelta(minutes=5))
        second = await RetrievalAuditRepository(two).claim_run(
            "worker-2", now, timedelta(minutes=5)
        )
        assert first is not None
        assert second is None
        recovered = await RetrievalAuditRepository(two).claim_run(
            "worker-2", now + timedelta(minutes=6), timedelta(minutes=5)
        )
        assert recovered is not None


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
        assert await RetrievalAuditRepository(one).claim_source(run_id, "source", now)
        assert not await RetrievalAuditRepository(two).claim_source(run_id, "source", now)
        await RetrievalAuditRepository(one).fail_source(
            run_id, "source", "network_error", "secret response body / token=abc"
        )
        outcome = await one.scalar(
            select(NewsRetrievalSourceOutcome).where(NewsRetrievalSourceOutcome.run_id == run_id)
        )
        assert outcome is not None
        assert outcome.failure_code == "network_error"
        assert outcome.outcome_detail is None
