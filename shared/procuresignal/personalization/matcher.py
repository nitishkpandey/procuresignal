"""Personalization matching engine."""

from dataclasses import dataclass
from typing import List, Optional

from procuresignal.models import NewsArticleProcessed, UserNewsPreference


@dataclass
class MatchScore:
    """Match score details."""

    overall_score: float  # 0.0-1.0
    category_match: float  # 0.0-1.0
    supplier_match: float  # 0.0-1.0
    region_match: float  # 0.0-1.0
    signal_match: float  # 0.0-1.0

    def __hash__(self) -> int:
        return hash(self.overall_score)


class PreferenceMatcher:
    """Match articles against user preferences."""

    @staticmethod
    def calculate_category_match(
        article_category: str,
        preference: UserNewsPreference,
    ) -> float:
        """Calculate category match score.

        Args:
            article_category: Article's category
            preference: User preference

        Returns:
            Score 0.0-1.0
        """
        if not preference.interested_categories:
            return 0.5  # Neutral if no preference

        if article_category.lower() in preference.interested_categories:
            return 1.0

        # Check excluded categories
        if preference.excluded_categories:
            if article_category.lower() in preference.excluded_categories:
                return 0.0

        return 0.3  # Partial match

    @staticmethod
    def calculate_supplier_match(
        article_suppliers: List[str],
        preference: UserNewsPreference,
    ) -> float:
        """Calculate supplier match score.

        Args:
            article_suppliers: Suppliers mentioned in article
            preference: User preference

        Returns:
            Score 0.0-1.0
        """
        if not article_suppliers or not preference.watched_suppliers:
            return 0.5  # Neutral if no data

        # Check for matches
        article_suppliers_lower = [s.lower() for s in article_suppliers]
        watched_lower = [s.lower() for s in preference.watched_suppliers]

        matches = len(set(article_suppliers_lower) & set(watched_lower))

        if matches > 0:
            # More matches = higher score
            return min(1.0, 0.5 + (matches * 0.25))

        # Check excluded suppliers
        if preference.excluded_suppliers:
            excluded_lower = [s.lower() for s in preference.excluded_suppliers]
            if set(article_suppliers_lower) & set(excluded_lower):
                return 0.0

        return 0.3

    @staticmethod
    def calculate_region_match(
        article_regions: List[str],
        preference: UserNewsPreference,
    ) -> float:
        """Calculate region match score.

        Args:
            article_regions: Regions mentioned in article
            preference: User preference

        Returns:
            Score 0.0-1.0
        """
        if not article_regions or not preference.interested_regions:
            return 0.5  # Neutral

        # Check for matches
        article_regions_lower = [r.lower() for r in article_regions]
        interested_lower = [r.lower() for r in preference.interested_regions]

        matches = len(set(article_regions_lower) & set(interested_lower))

        if matches > 0:
            return min(1.0, 0.5 + (matches * 0.25))

        # Check excluded regions
        if preference.excluded_regions:
            excluded_lower = [r.lower() for r in preference.excluded_regions]
            if set(article_regions_lower) & set(excluded_lower):
                return 0.0

        return 0.3

    @staticmethod
    def calculate_signal_match(
        article_signal_tags: List[str],
        article_priority_signal: Optional[str],
        preference: UserNewsPreference,
    ) -> float:
        """Calculate signal match score.

        Args:
            article_signal_tags: Tags from article
            article_priority_signal: Priority signal if present
            preference: User preference

        Returns:
            Score 0.0-1.0
        """
        if not preference.interested_signals:
            return 0.5  # Neutral

        # Priority signals get higher weight
        if article_priority_signal:
            if article_priority_signal.lower() in [
                s.lower() for s in preference.interested_signals
            ]:
                return 1.0

        # Check regular signal tags
        article_tags_lower = [t.lower() for t in article_signal_tags]
        interested_lower = [s.lower() for s in preference.interested_signals]

        matches = len(set(article_tags_lower) & set(interested_lower))

        if matches > 0:
            return min(1.0, 0.5 + (matches * 0.25))

        # Check excluded signals
        if preference.excluded_signals:
            excluded_lower = [s.lower() for s in preference.excluded_signals]
            if set(article_tags_lower) & set(excluded_lower):
                return 0.0

        return 0.3

    @staticmethod
    async def score_article(
        article: NewsArticleProcessed,
        preference: UserNewsPreference,
    ) -> MatchScore:
        """Score article against user preference.

        Args:
            article: Processed article
            preference: User preference

        Returns:
            MatchScore with breakdown
        """
        # Calculate individual match scores
        category_score = PreferenceMatcher.calculate_category_match(
            article.top_level_category,
            preference,
        )

        supplier_score = PreferenceMatcher.calculate_supplier_match(
            article.detected_suppliers or [],
            preference,
        )

        region_score = PreferenceMatcher.calculate_region_match(
            article.detected_regions or [],
            preference,
        )

        signal_score = PreferenceMatcher.calculate_signal_match(
            article.signal_tags or [],
            article.priority_signal,
            preference,
        )

        # Calculate weighted overall score
        # Weights: category 30%, supplier 30%, region 20%, signal 20%
        overall = (
            category_score * 0.30
            + supplier_score * 0.30
            + region_score * 0.20
            + signal_score * 0.20
        )

        return MatchScore(
            overall_score=overall,
            category_match=category_score,
            supplier_match=supplier_score,
            region_match=region_score,
            signal_match=signal_score,
        )
