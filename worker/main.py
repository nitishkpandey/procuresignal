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


from celery.signals import celeryd_init  # noqa: E402
from procuresignal.observability.metrics import (  # noqa: E402
    start_worker_metrics_server,
)


@celeryd_init.connect
def _serve_metrics(**_kwargs: object) -> None:
    """Prometheus has to be able to reach the worker, or its counters are decoration."""
    try:
        start_worker_metrics_server()
    except Exception:  # noqa: BLE001 - metrics must never stop the worker booting
        import logging

        logging.getLogger(__name__).exception("could not start worker metrics server")
