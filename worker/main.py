"""Celery application factory."""

from celery import Celery

app = Celery("procuresignal-worker")
app.config_from_object("worker.celery_config", namespace="CELERY")
app.autodiscover_tasks(["worker"])


@app.task(bind=True, name="worker.main.debug_task")
def debug_task(self) -> None:
    """Debug task for inspecting worker requests."""
    print(f"Request: {self.request!r}")


if __name__ == "__main__":
    app.start()
