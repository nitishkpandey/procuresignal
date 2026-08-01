"""News retrieval module."""

from .audit import RetrievalAuditRepository
from .base import FetchFailureCode, FetchResult, NewsProvider, RawArticle
from .catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from .deduplication import DeduplicationResult, article_fingerprint, deduplicate_within_run
from .fetching import SafeFetcher
from .large_object import LargeObjectFetcher, TemporaryFetchArtifact
from .orchestrator import (
    RetrievalOrchestrator,
    RetrievalRunResult,
    SourceRetrievalResult,
    configured_registry,
)
from .persistence import ArticlePersistence
from .providers import EUSanctionsProvider, GDELTProvider, NewsAPIProvider, RSSProvider
from .registry import (
    AdapterType,
    CoverageReport,
    ProcurementDomain,
    SourceClass,
    SourceDefinition,
    SourceRegistry,
)

__all__ = [
    "NewsProvider",
    "FetchFailureCode",
    "FetchResult",
    "SafeFetcher",
    "LargeObjectFetcher",
    "TemporaryFetchArtifact",
    "DeduplicationResult",
    "article_fingerprint",
    "deduplicate_within_run",
    "RetrievalAuditRepository",
    "RawArticle",
    "NewsAPIProvider",
    "GDELTProvider",
    "RSSProvider",
    "EUSanctionsProvider",
    "ArticlePersistence",
    "RetrievalOrchestrator",
    "RetrievalRunResult",
    "SourceRetrievalResult",
    "configured_registry",
    "AdapterType",
    "CoverageReport",
    "ProcurementDomain",
    "REGISTRY_VERSION",
    "SOURCE_REGISTRY",
    "SourceClass",
    "SourceDefinition",
    "SourceRegistry",
]
