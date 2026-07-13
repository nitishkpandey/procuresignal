"""Typed, validated definitions for registry-backed retrieval sources."""

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class SourceClass(StrEnum):
    """Authority classification of a retrieval source."""

    OFFICIAL = "official"
    ESTABLISHED_MEDIA = "established_media"
    INDUSTRY = "industry"


class AdapterType(StrEnum):
    """Adapter used to retrieve and parse a source."""

    RSS = "rss"
    STRUCTURED_SANCTIONS = "structured_sanctions"
    NEWSAPI = "newsapi"
    GDELT = "gdelt"


class ProcurementDomain(StrEnum):
    """Procurement-risk domains covered by sources."""

    SANCTIONS = "sanctions"
    REGULATION = "regulation"
    LOGISTICS = "logistics"
    COMMODITIES = "commodities"
    FX = "fx"
    SUPPLIER_RISK = "supplier_risk"
    EUROPE_BUSINESS = "europe_business"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """Immutable configuration and provenance for one retrieval endpoint."""

    source_id: str
    display_name: str
    homepage_url: str
    endpoint_url: str
    adapter: AdapterType
    source_class: SourceClass
    domains: frozenset[ProcurementDomain]
    countries: tuple[str, ...]
    languages: tuple[str, ...]
    poll_minutes: int
    item_limit: int
    expected_content_types: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    trust_seed: float
    license_note: str
    enabled_by_default: bool = True
    parser_hint: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Deterministic coverage gaps for the Phase 3 source matrix."""

    covered_domains: tuple[ProcurementDomain, ...]
    authoritative_domains: tuple[ProcurementDomain, ...]
    missing_domains: tuple[ProcurementDomain, ...]
    missing_authoritative_domains: tuple[ProcurementDomain, ...]


_SOURCE_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_COUNTRY = re.compile(r"^[a-z]{2}$")
_AUTHORITY_REQUIRED = (
    ProcurementDomain.SANCTIONS,
    ProcurementDomain.REGULATION,
)


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """Validated immutable collection of source definitions."""

    sources: tuple[SourceDefinition, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for source in self.sources:
            if source.source_id in seen:
                raise ValueError(f"duplicate source_id: {source.source_id}")
            seen.add(source.source_id)
            self._validate(source)

    @staticmethod
    def _validate(source: SourceDefinition) -> None:
        if not _SOURCE_ID.fullmatch(source.source_id):
            raise ValueError("source_id must be stable lowercase snake_case")
        if not source.display_name.strip():
            raise ValueError("display_name must not be empty")
        if not isinstance(source.adapter, AdapterType):
            raise ValueError("adapter must be an AdapterType")
        if not isinstance(source.source_class, SourceClass):
            raise ValueError("source_class must be a SourceClass")
        if not source.domains or not all(
            isinstance(domain, ProcurementDomain) for domain in source.domains
        ):
            raise ValueError("domains must contain ProcurementDomain values")
        if not source.languages or not all(
            _LANGUAGE.fullmatch(language) for language in source.languages
        ):
            raise ValueError("languages must contain lowercase ISO-like tokens")
        if not source.countries or not all(
            _COUNTRY.fullmatch(country) for country in source.countries
        ):
            raise ValueError("countries must contain lowercase ISO-like tokens")
        if not 5 <= source.poll_minutes <= 1440:
            raise ValueError("poll_minutes must be between 5 and 1440")
        if not 1 <= source.item_limit <= 100:
            raise ValueError("item_limit must be between 1 and 100")
        if not 0 <= source.trust_seed <= 1:
            raise ValueError("trust_seed must be between 0 and 1")
        if not source.license_note.strip():
            raise ValueError("license_note must not be empty")
        if not source.expected_content_types or any(
            not content_type.strip() for content_type in source.expected_content_types
        ):
            raise ValueError("expected_content_types must not be empty")
        if not source.allowed_hosts or any(
            host != host.lower() or not host.strip() for host in source.allowed_hosts
        ):
            raise ValueError("allowed_hosts must contain normalized hostnames")

        for label, url in (
            ("homepage_url", source.homepage_url),
            ("endpoint_url", source.endpoint_url),
        ):
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"{label} must be an absolute https URL")
            if parsed.username or parsed.password:
                raise ValueError(f"{label} must not contain credentials")

        endpoint_host = urlsplit(source.endpoint_url).hostname
        if endpoint_host not in source.allowed_hosts:
            raise ValueError("endpoint host must be present in allowed_hosts")

    def enabled(self, *, source_ids: set[str] | None = None) -> tuple[SourceDefinition, ...]:
        """Return default-enabled definitions, optionally restricted by ID."""
        return tuple(
            sorted(
                (
                    source
                    for source in self.sources
                    if source.enabled_by_default
                    and (source_ids is None or source.source_id in source_ids)
                ),
                key=lambda source: source.source_id,
            )
        )

    def validate_coverage(self) -> CoverageReport:
        """Report Phase 3 domain and mandatory-authority gaps."""
        enabled = self.enabled()
        covered = {domain for source in enabled for domain in source.domains}
        authoritative = {
            domain
            for source in enabled
            if source.source_class is SourceClass.OFFICIAL
            for domain in source.domains
        }
        return CoverageReport(
            covered_domains=tuple(domain for domain in ProcurementDomain if domain in covered),
            authoritative_domains=tuple(
                domain for domain in ProcurementDomain if domain in authoritative
            ),
            missing_domains=tuple(domain for domain in ProcurementDomain if domain not in covered),
            missing_authoritative_domains=tuple(
                domain for domain in _AUTHORITY_REQUIRED if domain not in authoritative
            ),
        )
