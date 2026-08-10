"""Tests for the operational alert rules.

These are alerts for the people running the system, distinct from the customer-facing
alert rules that arrive in Phase 4.

The important one is the first: a rule naming a metric nobody publishes never fires,
and a monitoring system that never fires looks exactly like a healthy one. That is the
same failure that left prometheus.yml scraping a non-existent endpoint for months.
"""

import re
from pathlib import Path

import pytest
import yaml
from procuresignal.observability import metrics as metrics_module
from prometheus_client import REGISTRY

ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = ROOT / "docker" / "prometheus" / "alerts.yml"

# Function names and keywords that appear in PromQL but are not metric names.
_PROMQL_KEYWORDS = {
    "time",
    "rate",
    "increase",
    "sum",
    "avg",
    "max",
    "min",
    "count",
    "absent",
    "by",
    "on",
    "without",
    "offset",
    "and",
    "or",
    "unless",
    "bool",
    "vector",
    "clamp_max",
    "clamp_min",
    "histogram_quantile",
    "le",
    "job",
    "instance",
    "stage",
    "source_id",
    "outcome",
    "status",
    "path",
    "method",
}


def _rules() -> list[dict]:
    document = yaml.safe_load(RULES_FILE.read_text())
    return [rule for group in document["groups"] for rule in group["rules"]]


def _metric_names_in(expression: str) -> set[str]:
    """Identifiers in a PromQL expression that look like metric names."""
    candidates = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b(?=\s*[\{\[\)\s]|$)", expression))
    return {name for name in candidates if name.startswith("procuresignal_")}


def _published_metric_names() -> set[str]:
    names: set[str] = set()
    for metric in REGISTRY.collect():
        names.add(metric.name)
        for sample in metric.samples:
            names.add(sample.name)
            # Counters expose <name>_total; rules reference that form.
            if sample.name.endswith("_total"):
                names.add(sample.name[: -len("_total")])
    return names


def test_the_rules_file_exists_and_parses() -> None:
    assert RULES_FILE.exists(), "no alert rules: /metrics with nothing watching it"
    assert _rules(), "rules file defines no alerts"


@pytest.mark.parametrize("rule", _rules() if RULES_FILE.exists() else [])
def test_every_alert_references_a_metric_we_publish(rule: dict) -> None:
    """A rule watching an unpublished metric never fires and is indistinguishable
    from a system that is simply healthy."""
    published = _published_metric_names()

    for name in _metric_names_in(rule["expr"]):
        base = name[: -len("_total")] if name.endswith("_total") else name
        assert (
            name in published or base in published
        ), f"{rule['alert']} watches {name!r}, which nothing publishes"


@pytest.mark.parametrize("rule", _rules() if RULES_FILE.exists() else [])
def test_every_alert_carries_severity_and_an_explanation(rule: dict) -> None:
    """An alert nobody can act on gets muted, and then so does the next one."""
    assert rule["labels"]["severity"] in {"critical", "warning"}
    assert rule["annotations"]["summary"]
    assert rule["annotations"]["description"]


@pytest.mark.parametrize("rule", _rules() if RULES_FILE.exists() else [])
def test_every_alert_waits_before_firing(rule: dict) -> None:
    """Without `for`, one scrape blip pages somebody at three in the morning."""
    assert rule.get("for"), f"{rule['alert']} has no `for` duration"


def test_pipeline_staleness_is_alerted() -> None:
    """The classic failure: ingestion returns nothing for days, health stays green."""
    alerts = {rule["alert"] for rule in _rules()}

    assert "PipelineStale" in alerts
    assert "PipelineNeverRan" in alerts


def test_the_alerts_cover_every_failure_this_phase_names() -> None:
    alerts = {rule["alert"] for rule in _rules()}

    for expected in (
        "PipelineStale",
        "PipelineNeverRan",
        "ApiServerErrors",
        "RetrievalSourceFailing",
        "EnrichmentLlmFailing",
        "TasksDeadLettering",
        "LlmBudgetExhausted",
        "SanctionsScreeningUnplaced",
        "NotificationsNotDraining",
    ):
        assert expected in alerts


def test_prometheus_loads_the_rules_file() -> None:
    """A rules file nothing reads is a text file."""
    config = yaml.safe_load((ROOT / "prometheus.yml").read_text())

    assert config.get("rule_files"), "prometheus.yml does not load any rule files"
    assert any("alerts" in path for path in config["rule_files"])


def test_the_rules_file_is_mounted_into_the_container() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    volumes = " ".join(compose["services"]["prometheus"].get("volumes", []))

    assert "alerts.yml" in volumes


def test_recorders_for_alerted_metrics_are_actually_called() -> None:
    """These existed as exported functions with no callers, which would have made
    every rule built on them permanently silent."""
    tasks = (ROOT / "worker" / "tasks.py").read_text()

    assert "record_retrieval(" in tasks
    assert "record_llm_call(" in tasks
    assert metrics_module.RETRIEVAL_ARTICLES is not None


def _label_selectors(expression: str) -> list[tuple[str, set[str]]]:
    """(metric, labels it filters on) for each selector in a PromQL expression."""
    pairs = []
    for metric, body in re.findall(r"(procuresignal_[a-zA-Z0-9_]*)\{([^}]*)\}", expression):
        labels = set(re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*[=!]~?=?", body))
        pairs.append((metric, labels))
    return pairs


@pytest.mark.parametrize("rule", _rules() if RULES_FILE.exists() else [])
def test_every_label_selector_uses_a_label_the_metric_declares(rule: dict) -> None:
    """PromQL treats an absent label as the empty string.

    So `{status!="success"}` against a metric with no `status` label matches every
    series rather than none, and the alert fires on healthy traffic. That is worse than
    a rule that never fires, and the metric-name check alone does not catch it.
    """
    declared = {
        metric._name: set(metric._labelnames or ())
        for metric in (
            metrics_module.HTTP_REQUESTS,
            metrics_module.RETRIEVAL_ARTICLES,
            metrics_module.ENRICHMENT_LLM_CALLS,
            metrics_module.PIPELINE_LAST_SUCCESS,
            metrics_module.DEAD_LETTERS,
            metrics_module.LLM_BUDGET_REFUSALS,
            metrics_module.SANCTIONS_SCREENING,
            metrics_module.NOTIFICATIONS_PENDING,
        )
    }

    for metric_name, labels in _label_selectors(rule["expr"]):
        base = metric_name[: -len("_total")] if metric_name.endswith("_total") else metric_name
        available = declared.get(base)
        if available is None:
            continue
        unknown = labels - available
        assert not unknown, (
            f"{rule['alert']} filters {metric_name} on {sorted(unknown)}, which it does "
            f"not declare. PromQL matches every series instead of none."
        )
