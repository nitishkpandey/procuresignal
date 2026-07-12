"""Tests for APScheduler registration."""

import asyncio
import logging
from contextlib import asynccontextmanager

from procuresignal.jobs import RetentionResult

from api import scheduler
from api.scheduler import SCHEDULED_JOB_IDS, configure_scheduler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_scheduler_registers_stable_idempotent_jobs():
    scheduler = FakeScheduler()

    configure_scheduler(scheduler)

    ids = {job["id"] for job in scheduler.jobs}
    assert ids == set(SCHEDULED_JOB_IDS)
    assert all(job["replace_existing"] is True for job in scheduler.jobs)
    assert all(job["max_instances"] == 1 for job in scheduler.jobs)
    assert all(job["coalesce"] is True for job in scheduler.jobs)


def test_scheduler_registers_risk_event_job() -> None:
    from api.scheduler import SCHEDULED_JOB_IDS

    assert "generate-risk-events" in SCHEDULED_JOB_IDS


def test_retention_logging_includes_risk_event_deletions(monkeypatch, caplog) -> None:
    @asynccontextmanager
    async def fake_session_scope():
        yield object()

    async def fake_prune(*args, **kwargs):
        return RetentionResult(
            raw_deleted=1,
            processed_deleted=2,
            feed_deleted=3,
            risk_events_deleted=4,
        )

    monkeypatch.setattr(scheduler, "session_scope", fake_session_scope)
    monkeypatch.setattr(scheduler, "prune_expired_records", fake_prune)
    caplog.set_level(logging.INFO, logger="api.scheduler")

    asyncio.run(scheduler._run_retention())

    assert "risk_events=4" in caplog.text
