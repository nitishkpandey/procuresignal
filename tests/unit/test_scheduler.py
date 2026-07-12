"""Tests for APScheduler registration."""

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
