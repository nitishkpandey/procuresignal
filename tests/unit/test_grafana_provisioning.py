"""Validate the on-disk contract consumed by a fresh Grafana instance."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GRAFANA = ROOT / "docker/grafana"


def test_datasource_and_dashboard_provider_are_ready_without_ui_setup():
    source = yaml.safe_load((GRAFANA / "provisioning/datasources/prometheus.yml").read_text())[
        "datasources"
    ][0]
    assert source["url"] == "http://prometheus:9090"
    assert source["isDefault"] is True
    provider = yaml.safe_load((GRAFANA / "provisioning/dashboards/procuresignal.yml").read_text())[
        "providers"
    ][0]
    assert provider["allowUiUpdates"] is False
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"
    dashboard = json.loads((GRAFANA / "dashboards/procuresignal-operations.json").read_text())
    assert dashboard["uid"] == "procuresignal-operations"
    panels = dashboard["panels"]
    assert len({panel["id"] for panel in panels}) == len(panels)
    assert {panel["title"] for panel in panels} == {
        "Target health",
        "API availability",
        "API p95 latency",
        "Pipeline age",
        "Retrieval failures",
        "Dead letters",
        "Notification delivery success",
        "Notification backlog",
        "Sanctions unmatched ratio",
        "Embedding backlog",
        "LLM budget refusals",
    }
    for panel in panels:
        assert panel["datasource"]["uid"] == source["uid"]
        assert panel["targets"][0]["expr"]


def test_compose_provisions_monitoring_read_only_with_pinned_images():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    mounts = services["grafana"]["volumes"]
    assert "./docker/grafana/provisioning:/etc/grafana/provisioning:ro" in mounts
    assert "./docker/grafana/dashboards:/var/lib/grafana/dashboards:ro" in mounts
    for service in ("grafana", "prometheus"):
        assert not services[service]["image"].endswith(":latest")
