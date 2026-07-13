"""News retrieval module."""

from .base import NewsProvider, RawArticle
from .catalog import REGISTRY_VERSION, SOURCE_REGISTRY
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
