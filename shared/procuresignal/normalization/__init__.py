"""Normalization and quality gate module."""

from .deduplicator import ArticleDeduplicator
from .language import LanguageDetector, LanguageValidator
from .normalizer import ArticleNormalizer
from .quality_filters import QualityCheckResult, QualityGates
from .source_trust import SourceTrustFilter

__all__ = [
    "ArticleDeduplicator",
    "QualityGates",
    "QualityCheckResult",
    "SourceTrustFilter",
    "LanguageDetector",
    "LanguageValidator",
    "ArticleNormalizer",
]
