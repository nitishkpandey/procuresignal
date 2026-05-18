"""Tests for Celery tasks."""

from worker.main import app
from worker.tasks import (
    enrich_articles_task,
    health_check_task,
    normalize_articles_task,
    personalize_feeds_task,
    retrieve_news_task,
)


def test_health_check_task() -> None:
    """Health check should return a healthy status payload."""
    result = health_check_task()

    assert result["status"] == "healthy"
    assert result["worker"]
    assert "timestamp" in result


def test_task_names_and_retry_config() -> None:
    """Tasks should be registered with the expected names and retry policy."""
    assert retrieve_news_task.name == "worker.tasks.retrieve_news_task"
    assert normalize_articles_task.name == "worker.tasks.normalize_articles_task"
    assert enrich_articles_task.name == "worker.tasks.enrich_articles_task"
    assert personalize_feeds_task.name == "worker.tasks.personalize_feeds_task"

    assert retrieve_news_task.max_retries == 3
    assert normalize_articles_task.max_retries == 3
    assert enrich_articles_task.max_retries == 2
    assert personalize_feeds_task.max_retries == 2


def test_celery_routes_and_schedule() -> None:
    """Celery should route periodic work onto the correct queues."""
    assert app.conf.task_routes["worker.tasks.retrieve_news_task"]["queue"] == "retrieval"
    assert app.conf.task_routes["worker.tasks.normalize_articles_task"]["queue"] == "processing"
    assert app.conf.task_routes["worker.tasks.enrich_articles_task"]["queue"] == "enrichment"
    assert app.conf.task_routes["worker.tasks.personalize_feeds_task"]["queue"] == "personalization"

    schedule = app.conf.beat_schedule
    assert schedule["retrieve-news-every-6-hours"]["options"]["queue"] == "retrieval"
    assert schedule["normalize-articles-every-2-hours"]["options"]["queue"] == "processing"
    assert schedule["enrich-articles-every-2-hours"]["options"]["queue"] == "enrichment"
    assert schedule["personalize-feeds-every-hour"]["options"]["queue"] == "personalization"
