"""One-shot: enqueue the retrieval -> normalize -> enrich -> personalize pipeline.

Run as the docker-compose `bootstrap` service so a fresh stack populates real
demo data. Best-effort: logs and returns 0 even if the broker is unreachable or
keys are missing, so it never blocks the stack.
"""

import os
import sys

from celery import Celery

BROKER = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

# (task name, queue, countdown seconds) — staggered so each stage runs after the
# previous has had time to produce rows.
PIPELINE = [
    ("worker.tasks.retrieve_news_task", "retrieval", 0),
    ("worker.tasks.normalize_articles_task", "processing", 60),
    ("worker.tasks.enrich_articles_task", "enrichment", 120),
    ("worker.tasks.personalize_feeds_task", "personalization", 180),
]


def main() -> int:
    try:
        app = Celery(broker=BROKER, backend=BACKEND)
        for name, queue, countdown in PIPELINE:
            app.send_task(name, queue=queue, countdown=countdown)
            print(f"[bootstrap] enqueued {name} (queue={queue}, countdown={countdown}s)")
        print("[bootstrap] pipeline enqueued; data populates as workers process tasks.")
    except Exception as exc:  # noqa: BLE001 - best-effort, must never block the stack
        print(f"[bootstrap] WARNING: could not enqueue pipeline: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
