"""Contracts for service-level indicator recording rules."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SLO_RULES = ROOT / "docker" / "prometheus" / "slo-rules.yml"
EXPECTED_RECORDS = {
    "procuresignal:api_availability:ratio_5m",
    "procuresignal:api_latency_p95_seconds:5m",
    "procuresignal:notification_delivery_success:ratio_30m",
}


def _recording_rules() -> dict[str, str]:
    document = yaml.safe_load(SLO_RULES.read_text(encoding="utf-8"))
    return {
        rule["record"]: str(rule["expr"]) for group in document["groups"] for rule in group["rules"]
    }


def test_slo_rules_define_only_the_approved_indicators() -> None:
    assert set(_recording_rules()) == EXPECTED_RECORDS


def test_ratio_indicators_guard_their_denominators() -> None:
    records = _recording_rules()

    for name in (
        "procuresignal:api_availability:ratio_5m",
        "procuresignal:notification_delivery_success:ratio_30m",
    ):
        expression = records[name]
        assert "clamp_min" in expression
        assert "or vector(0)" in expression
        assert "and on()" in expression
        assert "> 0" in expression
    assert "histogram_quantile" in records["procuresignal:api_latency_p95_seconds:5m"]


def test_prometheus_loads_and_compose_mounts_the_slo_rules() -> None:
    prometheus = yaml.safe_load((ROOT / "prometheus.yml").read_text(encoding="utf-8"))
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    volumes = " ".join(compose["services"]["prometheus"].get("volumes", []))

    assert "/etc/prometheus/slo-rules.yml" in prometheus["rule_files"]
    assert "slo-rules.yml:/etc/prometheus/slo-rules.yml:ro" in volumes
