"""News retrieval module."""

from .base import NewsProvider, RawArticle
from .persistence import ArticlePersistence
from .providers import GDELTProvider, NewsAPIProvider, RSSProvider

__all__ = [
    "NewsProvider",
    "RawArticle",
    "NewsAPIProvider",
    "GDELTProvider",
    "RSSProvider",
    "ArticlePersistence",
]
