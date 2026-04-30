"""Celery worker application entry point."""

from celery import Celery

app = Celery("procuresignal-worker", broker="redis://redis:6379/1", backend="redis://redis:6379/2")


@app.task
def hello(name: str) -> str:
    """Test task."""
    return f"Hello {name}"


if __name__ == "__main__":
    app.start()
