"""News retrieval module."""

from .audit import RetrievalAuditRepository
from .base import FetchFailureCode, FetchResult, NewsProvider, RawArticle
from .catalog import REGISTRY_VERSION, SOURCE_REGISTRY
from .fetching import SafeFetcher
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
    "RetrievalAuditRepository",
    "RawArticle",
    "NewsAPIProvider",
    "GDELTProvider",
    "RSSProvider",
    "ArticlePersistence",
    "AdapterType",
    "CoverageReport",
    "ProcurementDomain",
    "REGISTRY_VERSION",
    "SOURCE_REGISTRY",
    "SourceClass",
    "SourceDefinition",
    "SourceRegistry",
]
