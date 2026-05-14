"""Celery task definitions."""

from worker.main import app
from worker.signal_tasks import process_article_for_signals

__all__ = ["app", "process_article_for_signals"]
