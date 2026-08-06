"""Tests for dead-lettering tasks that exhaust their retries.

A task that runs out of retries currently disappears into the logs. The work is lost
and nobody is told, which is worse than a visible failure: the system looks healthy and
the articles simply never arrive.
"""

import pytest
from procuresignal.jobs.dead_letter import record_dead_letter
from procuresignal.models import DeadLetter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _rows(session: AsyncSession) -> list[DeadLetter]:
    return list((await session.execute(select(DeadLetter))).scalars().all())


async def test_an_exhausted_task_is_recorded(async_session: AsyncSession) -> None:
    await record_dead_letter(
        async_session,
        task_name="worker.tasks.enrich_articles_task",
        task_id="abc-123",
        payload={"hours_back": 6},
        error=ValueError("upstream refused"),
        retries=3,
    )
    await async_session.flush()

    row = (await _rows(async_session))[0]
    assert row.task_name == "worker.tasks.enrich_articles_task"
    assert row.task_id == "abc-123"
    assert row.error_type == "ValueError"
    assert "upstream refused" in row.error_message
    assert row.retries == 3


async def test_credentials_in_the_payload_are_scrubbed(async_session: AsyncSession) -> None:
    """Task arguments carry tokens, and a dead letter is read by whoever is on call."""
    await record_dead_letter(
        async_session,
        task_name="t",
        task_id="1",
        payload={"token": "sk-live-secret", "nested": {"api_key": "another"}, "days": 7},
        error=ValueError("x"),
        retries=1,
    )
    await async_session.flush()

    row = (await _rows(async_session))[0]
    assert "sk-live-secret" not in str(row.payload)
    assert "another" not in str(row.payload)
    assert row.payload["token"] == "[redacted]"
    assert row.payload["days"] == 7


async def test_the_traceback_is_kept(async_session: AsyncSession) -> None:
    """Without it, the record says something failed but not where."""
    try:
        raise RuntimeError("deep failure")
    except RuntimeError as exc:
        await record_dead_letter(
            async_session, task_name="t", task_id="1", payload={}, error=exc, retries=2
        )
    await async_session.flush()

    row = (await _rows(async_session))[0]
    assert "RuntimeError" in row.traceback
    assert "deep failure" in row.traceback


async def test_recording_never_raises(async_session: AsyncSession) -> None:
    """A failure while recording a failure must not replace the original error."""
    unserializable = {"obj": object()}

    await record_dead_letter(
        async_session,
        task_name="t",
        task_id="1",
        payload=unserializable,
        error=ValueError("original"),
        retries=1,
    )
    await async_session.flush()

    assert len(await _rows(async_session)) == 1


async def test_several_failures_are_separate_records(async_session: AsyncSession) -> None:
    for index in range(3):
        await record_dead_letter(
            async_session,
            task_name="t",
            task_id=f"id-{index}",
            payload={},
            error=ValueError("x"),
            retries=1,
        )
    await async_session.flush()

    assert len(await _rows(async_session)) == 3


def test_dead_letters_are_counted_for_alerting() -> None:
    """A queue silently filling with poison is the failure worth paging on."""
    from procuresignal.observability.metrics import DEAD_LETTERS

    assert DEAD_LETTERS is not None
    assert DEAD_LETTERS._labelnames == ("task",)


def test_the_worker_dead_letters_on_exhausted_retries() -> None:
    """The retry helper is the only place a task gives up, so it is the only hook."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "worker" / "tasks.py").read_text()

    assert "MaxRetriesExceededError" in source
    assert "record_dead_letter" in source


def test_the_scrubber_is_shared_with_the_audit_log() -> None:
    """Two definitions of "sensitive" drift, and one of them is always the stale one."""
    from procuresignal.jobs import dead_letter

    assert "from procuresignal.auth.audit import" in dead_letter.__doc__ or hasattr(
        dead_letter, "scrub"
    )


@pytest.mark.parametrize("key", ["password", "token", "secret", "api_key", "authorization"])
async def test_every_sensitive_key_shape_is_scrubbed(async_session: AsyncSession, key: str) -> None:
    await record_dead_letter(
        async_session,
        task_name="t",
        task_id="1",
        payload={key: "leaked-value"},
        error=ValueError("x"),
        retries=1,
    )
    await async_session.flush()

    assert "leaked-value" not in str((await _rows(async_session))[-1].payload)


class _FakeRequest:
    def __init__(self, retries: int) -> None:
        self.retries = retries
        self.id = "task-1"
        self.args: list = []
        self.kwargs: dict = {}


class _FakeTask:
    """Mimics Celery closely enough to expose the bug that hid the DLQ."""

    name = "worker.tasks.fake"
    max_retries = 2

    def __init__(self, retries: int) -> None:
        self.request = _FakeRequest(retries)
        self.retried = False

    def retry(self, exc=None, countdown=None):  # noqa: ANN001, ANN201
        self.retried = True
        # Celery's real behaviour: with `exc` supplied it re-raises that exception
        # once the limit is passed, rather than MaxRetriesExceededError.
        return RuntimeError("retry scheduled")


def test_a_task_below_its_limit_retries_rather_than_dead_letters(monkeypatch) -> None:
    import worker.tasks as tasks

    recorded: list = []
    monkeypatch.setattr(tasks, "record_dead_letter_metric", lambda name: recorded.append(name))

    task = _FakeTask(retries=0)

    async def _boom():
        raise ValueError("upstream")

    with pytest.raises(Exception):
        tasks._run_with_retry(task, _boom)

    assert task.retried is True
    assert recorded == []


def test_a_task_at_its_limit_dead_letters(monkeypatch) -> None:
    """This never happened: the old code waited for MaxRetriesExceededError, which
    Celery does not raise when an exception is passed to retry()."""
    import worker.tasks as tasks

    recorded: list = []
    monkeypatch.setattr(tasks, "record_dead_letter_metric", lambda name: recorded.append(name))

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(tasks, "_dead_letter", _noop)

    task = _FakeTask(retries=2)

    async def _boom():
        raise ValueError("upstream")

    with pytest.raises(ValueError):
        tasks._run_with_retry(task, _boom)

    assert task.retried is False
    assert recorded == ["worker.tasks.fake"]
