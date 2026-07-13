"""Celery application factory."""

import logging
from typing import Any

from celery import Celery

logger = logging.getLogger(__name__)

app = Celery("procuresignal-worker")
app.config_from_object("worker.celery_config", namespace="CELERY")
app.autodiscover_tasks(["worker"])


@app.task(bind=True, name="worker.main.debug_task")
def debug_task(self: Any) -> None:
    """Debug task for inspecting worker requests."""
    logger.debug("Worker debug task request: %r", self.request)


if __name__ == "__main__":
    app.start()
