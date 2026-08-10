"""Evaluation and delivery run on a schedule, and separately.

Two tasks rather than one: a transport outage must not stop rules being evaluated, and
a slow rule must not stop delivery of what is already queued. Coupling them means one
bad dependency stops both halves of the alerting path.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_evaluation_and_delivery_are_separate_tasks() -> None:
    from worker.celery_config import CELERY_TASK_ROUTES

    assert "worker.tasks.evaluate_alert_rules_task" in CELERY_TASK_ROUTES
    assert "worker.tasks.deliver_notifications_task" in CELERY_TASK_ROUTES


def test_both_are_scheduled() -> None:
    from worker.celery_config import CELERY_BEAT_SCHEDULE

    scheduled = {entry["task"] for entry in CELERY_BEAT_SCHEDULE.values()}
    assert "worker.tasks.evaluate_alert_rules_task" in scheduled
    assert "worker.tasks.deliver_notifications_task" in scheduled


def test_evaluation_runs_after_risk_events() -> None:
    """Rules read the events that run produces; evaluating first would see nothing."""
    from worker.celery_config import CELERY_BEAT_SCHEDULE

    def minute_of(task: str) -> int:
        for entry in CELERY_BEAT_SCHEDULE.values():
            if entry["task"] == task:
                return min(entry["schedule"].minute)
        raise AssertionError(f"{task} is not scheduled")

    assert minute_of("worker.tasks.generate_risk_events_task") < minute_of(
        "worker.tasks.evaluate_alert_rules_task"
    )


def test_both_report_pipeline_freshness() -> None:
    """A stage with no gauge is invisible to the staleness alert."""
    source = (ROOT / "worker" / "tasks.py").read_text()

    assert 'record_pipeline_success("alert_evaluation")' in source
    assert 'record_pipeline_success("notification_delivery")' in source


def test_the_outbox_depth_is_published() -> None:
    """A drain that stalls leaves alerts queued and everything else looking healthy."""
    from procuresignal.observability.metrics import NOTIFICATIONS_PENDING

    assert NOTIFICATIONS_PENDING is not None


def test_an_alert_watches_a_stalled_outbox() -> None:
    import yaml

    document = yaml.safe_load((ROOT / "docker/prometheus/alerts.yml").read_text())
    alerts = {rule["alert"] for group in document["groups"] for rule in group["rules"]}

    assert "NotificationsNotDraining" in alerts
