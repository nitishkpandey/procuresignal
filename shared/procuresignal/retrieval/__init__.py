"""News retrieval module."""

from .audit import RetrievalAuditRepository
from .base import FetchFailureCode, FetchResult, NewsProvider, RawArticle
from .catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from .deduplication import DeduplicationResult, article_fingerprint, deduplicate_within_run
from .fetching import SafeFetcher
from .orchestrator import (
    RetrievalOrchestrator,
    RetrievalRunResult,
    SourceRetrievalResult,
    configured_registry,
)
from .persistence import ArticlePersistence
from .providers import GDELTProvider, NewsAPIProvider, RSSProvider
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
    "DeduplicationResult",
    "article_fingerprint",
    "deduplicate_within_run",
    "RetrievalAuditRepository",
    "RawArticle",
    "NewsAPIProvider",
    "GDELTProvider",
    "RSSProvider",
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
