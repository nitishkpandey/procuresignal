"""APScheduler wiring for ProcureSignal jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from os import getenv
from typing import TYPE_CHECKING, Any, Protocol

from procuresignal.config.database import session_scope
from procuresignal.jobs import RetentionPolicy, prune_expired_records

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


class Scheduler(Protocol):
    """Scheduler surface required by job registration and its test fake."""

    def add_job(self, func: Callable[..., object], trigger: str, **kwargs: object) -> object:
        ...


logger = logging.getLogger(__name__)

SCHEDULED_JOB_IDS = (
    "retrieve-news",
    "normalize-articles",
    "enrich-articles",
    "generate-risk-events",
    "personalize-feeds",
    "prune-retention",
)


def _enqueue_retrieve_news() -> None:
    from worker.tasks import retrieve_news_task

    retrieve_news_task.delay()


def _enqueue_normalize_articles() -> None:
    from worker.tasks import normalize_articles_task

    normalize_articles_task.delay()


def _enqueue_enrich_articles() -> None:
    from worker.tasks import enrich_articles_task

    enrich_articles_task.delay()


def _enqueue_generate_risk_events() -> None:
    from worker.tasks import generate_risk_events_task

    generate_risk_events_task.delay()


def _enqueue_personalize_feeds() -> None:
    from worker.tasks import personalize_feeds_task

    personalize_feeds_task.delay()


async def _run_retention() -> None:
    async with session_scope() as session:
        result = await prune_expired_records(session, policy=RetentionPolicy())
        logger.info(
            "Retention pruned risk_events=%s raw=%s processed=%s feed=%s",
            result.risk_events_deleted,
            result.raw_deleted,
            result.processed_deleted,
            result.feed_deleted,
        )


def _job_options(job_id: str) -> dict[str, Any]:
    return {
        "id": job_id,
        "replace_existing": True,
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 900,
    }


def configure_scheduler(scheduler: Scheduler) -> None:
    """Register idempotent scheduled jobs on an APScheduler instance."""

    scheduler.add_job(
        _enqueue_retrieve_news,
        "cron",
        minute=0,
        hour="*/6",
        **_job_options("retrieve-news"),
    )
    scheduler.add_job(
        _enqueue_normalize_articles,
        "cron",
        minute=30,
        hour="*/2",
        **_job_options("normalize-articles"),
    )
    scheduler.add_job(
        _enqueue_enrich_articles,
        "cron",
        minute=45,
        hour="*/2",
        **_job_options("enrich-articles"),
    )
    scheduler.add_job(
        _enqueue_generate_risk_events,
        "cron",
        minute=50,
        hour="*/2",
        **_job_options("generate-risk-events"),
    )
    scheduler.add_job(
        _enqueue_personalize_feeds,
        "cron",
        minute=0,
        hour="*",
        **_job_options("personalize-feeds"),
    )
    scheduler.add_job(
        _run_retention,
        "cron",
        minute=15,
        hour=2,
        **_job_options("prune-retention"),
    )


def create_scheduler() -> AsyncIOScheduler:
    """Create the concrete APScheduler instance."""

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError as exc:  # pragma: no cover - deployment configuration guard
        raise RuntimeError(
            "APScheduler is not installed. Install the apscheduler package."
        ) from exc

    scheduler = AsyncIOScheduler(timezone="UTC")
    configure_scheduler(scheduler)
    return scheduler


def scheduler_enabled() -> bool:
    """Return whether API-owned APScheduler should run."""

    return getenv("ENABLE_APSCHEDULER", "false").lower() == "true"
