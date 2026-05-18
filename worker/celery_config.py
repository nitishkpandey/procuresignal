"""Celery configuration."""

import os

from celery.schedules import crontab
from kombu import Queue

CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    os.getenv("REDIS_URL", "redis://redis:6379/0"),
)
CELERY_RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND",
    os.getenv("REDIS_URL", "redis://redis:6379/1"),
)

CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_DEFAULT_EXCHANGE_TYPE = "direct"
CELERY_TASK_DEFAULT_ROUTING_KEY = "default"

CELERY_TASK_QUEUES = (
    Queue("retrieval", routing_key="retrieval"),
    Queue("processing", routing_key="processing"),
    Queue("enrichment", routing_key="enrichment"),
    Queue("personalization", routing_key="personalization"),
    Queue("default", routing_key="default"),
)

CELERY_TASK_ROUTES = {
    "worker.tasks.retrieve_news_task": {"queue": "retrieval", "routing_key": "retrieval"},
    "worker.tasks.normalize_articles_task": {
        "queue": "processing",
        "routing_key": "processing",
    },
    "worker.tasks.enrich_articles_task": {"queue": "enrichment", "routing_key": "enrichment"},
    "worker.tasks.personalize_feeds_task": {
        "queue": "personalization",
        "routing_key": "personalization",
    },
    "worker.tasks.health_check_task": {"queue": "default", "routing_key": "default"},
}

CELERY_BEAT_SCHEDULE = {
    "retrieve-news-every-6-hours": {
        "task": "worker.tasks.retrieve_news_task",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"queue": "retrieval"},
    },
    "normalize-articles-every-2-hours": {
        "task": "worker.tasks.normalize_articles_task",
        "schedule": crontab(minute=30, hour="*/2"),
        "options": {"queue": "processing"},
    },
    "enrich-articles-every-2-hours": {
        "task": "worker.tasks.enrich_articles_task",
        "schedule": crontab(minute=45, hour="*/2"),
        "options": {"queue": "enrichment"},
    },
    "personalize-feeds-every-hour": {
        "task": "worker.tasks.personalize_feeds_task",
        "schedule": crontab(minute=0, hour="*"),
        "options": {"queue": "personalization"},
    },
}

CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SOFT_TIME_LIMIT = 3600
CELERY_TASK_TIME_LIMIT = 3700

CELERY_WORKER_LOG_FORMAT = "[%(levelname)s] %(name)s - %(message)s"
CELERY_WORKER_TASK_LOG_FORMAT = "[%(levelname)s] %(name)s[%(process)d] - %(message)s"
