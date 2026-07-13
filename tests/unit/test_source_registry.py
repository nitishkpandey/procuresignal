"""Contract tests for the typed retrieval source registry."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from procuresignal.retrieval.catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from procuresignal.retrieval.registry import (
    AdapterType,
    ProcurementDomain,
    SourceClass,
    SourceDefinition,
    SourceRegistry,
)

SNAPSHOT = Path("tests/fixtures/retrieval/catalog_expected.json")


def definition(**changes: object) -> SourceDefinition:
    """Return a valid definition with selected fields replaced."""
    base = SourceDefinition(
        source_id="example_source",
        display_name="Example Source",
        homepage_url="https://example.com/",
        endpoint_url="https://feeds.example.com/news.xml",
        adapter=AdapterType.RSS,
        source_class=SourceClass.INDUSTRY,
        domains=frozenset({ProcurementDomain.LOGISTICS}),
        countries=("eu",),
        languages=("en",),
        poll_minutes=60,
        item_limit=25,
        expected_content_types=("application/rss+xml", "application/xml"),
        allowed_hosts=("feeds.example.com",),
        trust_seed=0.7,
        license_note="Public RSS feed; retain attribution and article links.",
    )
    return replace(base, **changes)


def test_registry_rejects_unsafe_and_ambiguous_definitions() -> None:
    with pytest.raises(ValueError, match="https"):
        SourceRegistry((definition(endpoint_url="http://example.com/feed"),))
    with pytest.raises(ValueError, match="duplicate source_id"):
        SourceRegistry((definition(source_id="ec"), definition(source_id="ec")))
    with pytest.raises(ValueError, match="domains"):
        SourceRegistry((definition(domains=frozenset()),))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_id": "Not Stable"}, "source_id"),
        ({"homepage_url": "http://example.com"}, "https"),
        ({"languages": ()}, "languages"),
        ({"languages": ("english",)}, "languages"),
        ({"countries": ("europe",)}, "countries"),
        ({"poll_minutes": 4}, "poll_minutes"),
        ({"poll_minutes": 1441}, "poll_minutes"),
        ({"item_limit": 0}, "item_limit"),
        ({"item_limit": 101}, "item_limit"),
        ({"trust_seed": -0.01}, "trust_seed"),
        ({"trust_seed": 1.01}, "trust_seed"),
        ({"license_note": "  "}, "license_note"),
        ({"allowed_hosts": ("other.example.com",)}, "allowed_hosts"),
    ],
)
def test_registry_validates_definition_bounds(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SourceRegistry((definition(**changes),))


def test_registry_is_immutable_and_selects_enabled_sources_deterministically() -> None:
    registry = SourceRegistry(
        (
            definition(source_id="z_source"),
            definition(source_id="disabled", enabled_by_default=False),
            definition(source_id="a_source"),
        )
    )

    assert tuple(source.source_id for source in registry.enabled()) == (
        "a_source",
        "z_source",
    )
    assert tuple(
        source.source_id for source in registry.enabled(source_ids={"z_source", "disabled"})
    ) == ("z_source",)
    with pytest.raises(FrozenInstanceError):
        registry.sources = ()  # type: ignore[misc]


def test_coverage_report_lists_exact_missing_requirements() -> None:
    registry = SourceRegistry((definition(domains=frozenset({ProcurementDomain.LOGISTICS})),))

    report = registry.validate_coverage()

    assert report.missing_domains == tuple(
        domain for domain in ProcurementDomain if domain is not ProcurementDomain.LOGISTICS
    )
    assert report.missing_authoritative_domains == (
        ProcurementDomain.SANCTIONS,
        ProcurementDomain.REGULATION,
    )
    assert report.missing_structured_authoritative_domains == (ProcurementDomain.SANCTIONS,)
    assert report.authoritative_domains == ()


def test_production_registry_meets_phase_3_coverage() -> None:
    report = SOURCE_REGISTRY.validate_coverage()
    assert report.missing_domains == ()
    assert report.missing_authoritative_domains == ()
    assert report.missing_structured_authoritative_domains == (ProcurementDomain.SANCTIONS,)
    assert {"sanctions", "regulation"} <= {domain.value for domain in report.authoritative_domains}


def test_enabled_catalog_matches_reviewed_snapshot() -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    assert expected["registry_version"] == REGISTRY_VERSION
    assert expected["enabled_source_ids"] == [
        source.source_id for source in SOURCE_REGISTRY.enabled()
    ]
    actual_by_id = {source.source_id: source for source in SOURCE_REGISTRY.sources}
    assert set(actual_by_id) == {candidate["source_id"] for candidate in expected["candidates"]}
    for candidate in expected["candidates"]:
        source = actual_by_id[candidate["source_id"]]
        assert candidate == {
            "source_id": source.source_id,
            "owner": candidate["owner"],
            "display_name": source.display_name,
            "endpoint": source.endpoint_url,
            "adapter": source.adapter.value,
            "source_class": source.source_class.value,
            "domains": sorted(domain.value for domain in source.domains),
            "countries": list(source.countries),
            "languages": list(source.languages),
            "expected_content_types": list(source.expected_content_types),
            "allowed_hosts": list(source.allowed_hosts),
            "trust_seed": source.trust_seed,
            "license_note": source.license_note,
            "planned_fixture": candidate["planned_fixture"],
            "enabled": source.enabled_by_default,
        }


def test_snapshot_declares_only_future_fixture_intent() -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    for candidate in expected["candidates"]:
        assert "fixture" not in candidate
        assert candidate["planned_fixture"].endswith((".xml", ".json"))
