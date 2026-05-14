"""Celery worker application entry point."""

import os

from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
backend_url = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

app = Celery("procuresignal-worker", broker=broker_url, backend=backend_url)

# Ensure task modules are loaded when worker starts.
app.autodiscover_tasks(["worker"])


@app.task
def hello(name: str) -> str:
    """Test task."""
    return f"Hello {name}"


if __name__ == "__main__":
    app.start()
