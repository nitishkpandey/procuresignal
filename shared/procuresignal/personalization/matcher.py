"""Personalization matching engine."""

from dataclasses import dataclass
from typing import Iterable, List, Optional

from procuresignal.enrichment.entities import canonical_region_name, extract_regions_from_text
from procuresignal.models import NewsArticleProcessed, UserNewsPreference
from procuresignal.personalization.categories import canonical_category, canonical_category_set
from procuresignal.signals.taxonomy import expand_signal_terms, text_matches_signal_terms


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
    def _normalized(values: Iterable[str] | None) -> set[str]:
        """Normalize preference/article tokens for case-insensitive matching."""
        return {str(value).strip().lower() for value in values or [] if str(value).strip()}

    @staticmethod
    def _preferred_categories(preference: UserNewsPreference) -> set[str]:
        return canonical_category_set(
            getattr(
                preference, "preferred_categories", getattr(preference, "interested_categories", [])
            )
        )

    @staticmethod
    def _excluded_categories(preference: UserNewsPreference) -> set[str]:
        excluded = getattr(
            preference,
            "excluded_categories",
            getattr(preference, "excluded_topics", []),
        )
        if not excluded:
            excluded = getattr(preference, "excluded_topics", [])
        return canonical_category_set(excluded)

    @staticmethod
    def _preferred_suppliers(preference: UserNewsPreference) -> set[str]:
        return PreferenceMatcher._normalized(
            getattr(
                preference, "preferred_suppliers", getattr(preference, "interested_suppliers", [])
            )
        )

    @staticmethod
    def _preferred_regions(preference: UserNewsPreference) -> set[str]:
        return PreferenceMatcher._region_tokens(
            getattr(preference, "preferred_regions", getattr(preference, "interested_regions", []))
        )

    @staticmethod
    def _preferred_signals(preference: UserNewsPreference) -> set[str]:
        return expand_signal_terms(
            getattr(preference, "preferred_signals", getattr(preference, "interested_signals", []))
        )

    @staticmethod
    def _article_categories(article: NewsArticleProcessed) -> set[str]:
        return canonical_category_set(
            [article.top_level_category, *(article.detected_categories or [])]
        )

    @staticmethod
    def _article_suppliers(article: NewsArticleProcessed) -> set[str]:
        return PreferenceMatcher._normalized(article.detected_suppliers or [])

    @staticmethod
    def _article_text(article: NewsArticleProcessed) -> str:
        return " ".join(
            part.strip().lower()
            for part in [article.normalized_title or "", article.summary or ""]
            if part and part.strip()
        )

    @staticmethod
    def _supplier_text_matches(
        article: NewsArticleProcessed,
        preferred_suppliers: set[str],
    ) -> set[str]:
        text = PreferenceMatcher._article_text(article)
        return {supplier for supplier in preferred_suppliers if supplier in text}

    @staticmethod
    def _region_tokens(values: Iterable[str] | None) -> set[str]:
        """Normalize regions through the shared alias map before matching."""
        return {
            canonical_region_name(str(value)).strip().lower()
            for value in values or []
            if canonical_region_name(str(value)).strip()
        }

    @staticmethod
    def _article_regions(article: NewsArticleProcessed) -> set[str]:
        return PreferenceMatcher._region_tokens(article.detected_regions or [])

    @staticmethod
    def _text_regions(article: NewsArticleProcessed) -> set[str]:
        return PreferenceMatcher._region_tokens(
            extract_regions_from_text(PreferenceMatcher._article_text(article))
        )

    @staticmethod
    def _article_regions_for_matching(article: NewsArticleProcessed) -> set[str]:
        regions = set(PreferenceMatcher._article_regions(article))
        regions.update(PreferenceMatcher._text_regions(article))
        return regions

    @staticmethod
    def _article_signals(article: NewsArticleProcessed) -> set[str]:
        return expand_signal_terms(
            [value for value in [article.priority_signal, *(article.signal_tags or [])] if value]
        )

    @staticmethod
    def _excluded_signals(preference: UserNewsPreference) -> set[str]:
        return expand_signal_terms(getattr(preference, "excluded_signals", []))

    @staticmethod
    def _article_signal_context(article: NewsArticleProcessed) -> str:
        parts = [PreferenceMatcher._article_text(article)]
        parts.extend(PreferenceMatcher._article_regions_for_matching(article))
        return " ".join(part for part in parts if part)

    @staticmethod
    def _signal_matches_article(
        article: NewsArticleProcessed,
        signals: Iterable[str],
    ) -> bool:
        signal_terms = expand_signal_terms(signals)
        if not signal_terms:
            return False

        article_terms = set(PreferenceMatcher._article_signals(article))
        article_terms.update(
            expand_signal_terms(PreferenceMatcher._article_regions_for_matching(article))
        )

        return bool(article_terms & signal_terms) or text_matches_signal_terms(
            PreferenceMatcher._article_signal_context(article),
            signal_terms,
        )

    @staticmethod
    def has_excluded_match(
        article: NewsArticleProcessed,
        preference: UserNewsPreference,
    ) -> bool:
        """Return True when an article hits any explicit exclusion."""
        excluded_suppliers = PreferenceMatcher._normalized(
            getattr(preference, "excluded_suppliers", [])
        )
        excluded_regions = PreferenceMatcher._normalized(
            getattr(preference, "excluded_regions", [])
        )
        excluded_regions = PreferenceMatcher._region_tokens(excluded_regions)
        excluded_signals = PreferenceMatcher._excluded_signals(preference)

        return bool(
            (
                PreferenceMatcher._article_categories(article)
                & PreferenceMatcher._excluded_categories(preference)
            )
            or (PreferenceMatcher._article_suppliers(article) & excluded_suppliers)
            or (PreferenceMatcher._article_regions_for_matching(article) & excluded_regions)
            or PreferenceMatcher._signal_matches_article(article, excluded_signals)
        )

    @staticmethod
    def should_include_article(
        article: NewsArticleProcessed,
        preference: UserNewsPreference,
    ) -> bool:
        """Decide whether an article is eligible for the user's feed.

        Category and supplier interests are the strongest intent signals. Region
        and signal preferences refine the feed, but should not allow generic
        articles through when primary focus preferences are present.
        """
        if PreferenceMatcher.has_excluded_match(article, preference):
            return False

        preferred_categories = PreferenceMatcher._preferred_categories(preference)
        preferred_suppliers = PreferenceMatcher._preferred_suppliers(preference)
        preferred_regions = PreferenceMatcher._preferred_regions(preference)
        preferred_signals = PreferenceMatcher._preferred_signals(preference)

        category_match = bool(PreferenceMatcher._article_categories(article) & preferred_categories)
        supplier_match = bool(
            (PreferenceMatcher._article_suppliers(article) & preferred_suppliers)
            or PreferenceMatcher._supplier_text_matches(article, preferred_suppliers)
        )
        region_match = bool(
            PreferenceMatcher._article_regions_for_matching(article) & preferred_regions
        )
        signal_match = PreferenceMatcher._signal_matches_article(article, preferred_signals)

        if preferred_categories or preferred_suppliers:
            return category_match or supplier_match
        if preferred_regions:
            return region_match
        if preferred_signals:
            return signal_match
        return True

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
        preferred_categories = PreferenceMatcher._preferred_categories(preference)
        excluded_categories = PreferenceMatcher._excluded_categories(preference)
        article_category_normalized = canonical_category(article_category)

        if article_category_normalized in excluded_categories:
            return 0.0

        if not preferred_categories:
            return 0.5  # Neutral if no preference

        if article_category_normalized in preferred_categories:
            return 1.0

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
        preferred_suppliers = PreferenceMatcher._preferred_suppliers(preference)
        excluded_suppliers = PreferenceMatcher._normalized(
            getattr(preference, "excluded_suppliers", [])
        )
        article_suppliers_lower = PreferenceMatcher._normalized(article_suppliers)

        if article_suppliers_lower & excluded_suppliers:
            return 0.0

        if not article_suppliers or not preferred_suppliers:
            return 0.5  # Neutral if no data

        # Check for matches
        matches = len(article_suppliers_lower & preferred_suppliers)

        if matches > 0:
            # More matches = higher score
            return min(1.0, 0.5 + (matches * 0.25))

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
        preferred_regions = PreferenceMatcher._preferred_regions(preference)
        excluded_regions = PreferenceMatcher._region_tokens(
            getattr(preference, "excluded_regions", [])
        )
        article_regions_lower = PreferenceMatcher._region_tokens(article_regions)

        if article_regions_lower & excluded_regions:
            return 0.0

        if not article_regions or not preferred_regions:
            return 0.5  # Neutral

        # Check for matches
        matches = len(article_regions_lower & preferred_regions)

        if matches > 0:
            return min(1.0, 0.5 + (matches * 0.25))

        return 0.3

    @staticmethod
    def calculate_signal_match(
        article_signal_tags: List[str],
        article_priority_signal: Optional[str],
        preference: UserNewsPreference,
        article_signal_context: str = "",
    ) -> float:
        """Calculate signal match score.

        Args:
            article_signal_tags: Tags from article
            article_priority_signal: Priority signal if present
            preference: User preference

        Returns:
            Score 0.0-1.0
        """
        preferred_signals = PreferenceMatcher._preferred_signals(preference)
        excluded_signals = PreferenceMatcher._excluded_signals(preference)
        article_tags_lower = expand_signal_terms(
            [value for value in [*article_signal_tags, article_priority_signal] if value]
        )

        if (article_tags_lower & excluded_signals) or text_matches_signal_terms(
            article_signal_context,
            excluded_signals,
        ):
            return 0.0

        if not preferred_signals:
            return 0.5  # Neutral

        # Priority signals get higher weight
        if article_priority_signal:
            if expand_signal_terms([article_priority_signal]) & preferred_signals:
                return 1.0

        # Check regular signal tags
        matches = len(article_tags_lower & preferred_signals)
        if text_matches_signal_terms(article_signal_context, preferred_signals):
            matches += 1

        if matches > 0:
            return min(1.0, 0.5 + (matches * 0.25))

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

        supplier_tokens = set(article.detected_suppliers or [])
        supplier_tokens.update(
            PreferenceMatcher._supplier_text_matches(
                article,
                PreferenceMatcher._preferred_suppliers(preference),
            )
        )
        supplier_score = PreferenceMatcher.calculate_supplier_match(
            list(supplier_tokens), preference
        )

        region_score = PreferenceMatcher.calculate_region_match(
            list(PreferenceMatcher._article_regions_for_matching(article)),
            preference,
        )

        signal_score = PreferenceMatcher.calculate_signal_match(
            article.signal_tags or [],
            article.priority_signal,
            preference,
            PreferenceMatcher._article_signal_context(article),
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
