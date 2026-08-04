"""Personalization pipeline orchestration."""

from datetime import datetime, timedelta
from typing import List, Tuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import (
    ArticleSupplierMention,
    NewsArticleProcessed,
    Supplier,
    UserNewsFeed,
    UserNewsPreference,
)
from procuresignal.personalization.matcher import MatchScore, PreferenceMatcher


class PersonalizationPipeline:
    """Orchestrate personalized feed generation."""

    @staticmethod
    def _fallback_preference(user_id: str, preference: UserNewsPreference) -> UserNewsPreference:
        """Build a baseline preference that keeps exclusions but clears positive filters."""

        return UserNewsPreference(
            user_id=user_id,
            preferred_categories=[],
            preferred_suppliers=[],
            preferred_regions=[],
            preferred_signals=[],
            excluded_categories=preference.excluded_categories or [],
            excluded_suppliers=preference.excluded_suppliers or [],
            excluded_regions=preference.excluded_regions or [],
            excluded_signals=preference.excluded_signals or [],
            excluded_topics=preference.excluded_topics or [],
        )

    @staticmethod
    async def _supplier_ids_by_article(
        session: AsyncSession, article_ids: list[int]
    ) -> dict[int, set[str]]:
        """Canonical suppliers each article was resolved to.

        Loaded in one query for the whole candidate set. Asking per article would turn
        a feed rebuild into a query per row.
        """

        if not article_ids:
            return {}

        rows = (
            await session.execute(
                select(ArticleSupplierMention.processed_article_id, Supplier.public_id)
                .join(Supplier, Supplier.id == ArticleSupplierMention.supplier_id)
                .where(ArticleSupplierMention.processed_article_id.in_(article_ids))
                .where(Supplier.is_active.is_(True))
            )
        ).all()

        mapped: dict[int, set[str]] = {}
        for article_id, public_id in rows:
            mapped.setdefault(article_id, set()).add(public_id)
        return mapped

    @staticmethod
    async def _score_articles(
        articles: list[NewsArticleProcessed],
        preference: UserNewsPreference,
        existing_article_ids: set[int],
        supplier_ids_by_article: dict[int, set[str]] | None = None,
    ) -> list[tuple[NewsArticleProcessed, MatchScore]]:
        scored_articles = []
        resolved = supplier_ids_by_article or {}

        for article in articles:
            if article.id in existing_article_ids:
                continue

            article_supplier_ids = resolved.get(article.id, set())
            if not PreferenceMatcher.should_include_article(
                article, preference, article_supplier_ids=article_supplier_ids
            ):
                continue

            score = await PreferenceMatcher.score_article(
                article, preference, article_supplier_ids=article_supplier_ids
            )

            # Only include if score > threshold (0.3)
            if score.overall_score >= 0.3:
                scored_articles.append((article, score))

        return scored_articles

    @staticmethod
    async def generate_feed(
        session: AsyncSession,
        user_id: str,
        limit: int = 50,
        days_back: int = 7,
    ) -> Tuple[List[UserNewsFeed], int, int]:
        """Generate personalized feed for user.

        Args:
            session: Database session
            user_id: User ID
            limit: Max articles in feed
            days_back: Only include articles from last N days

        Returns:
            (feed_articles, matched_count, total_count)
        """
        # Get user preference
        preference = await session.execute(
            select(UserNewsPreference).where(UserNewsPreference.user_id == user_id)
        )
        pref = preference.scalar_one_or_none()

        if not pref:
            # Default preference: include all
            pref = UserNewsPreference(
                user_id=user_id,
                preferred_categories=[],
                preferred_suppliers=[],
                preferred_regions=[],
                preferred_signals=[],
                excluded_categories=[],
                excluded_suppliers=[],
                excluded_regions=[],
                excluded_signals=[],
                excluded_topics=[],
            )

        # Get recent articles
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        existing_feed_query = await session.execute(
            select(UserNewsFeed.processed_article_id).where(UserNewsFeed.user_id == user_id)
        )
        existing_article_ids = {row[0] for row in existing_feed_query.all()}

        articles_query = await session.execute(
            select(NewsArticleProcessed)
            .where(NewsArticleProcessed.processed_at >= cutoff_date)
            .order_by(desc(NewsArticleProcessed.processed_at))
        )
        articles = articles_query.scalars().all()

        # One query for the whole candidate set, reused by both scoring passes.
        supplier_ids_by_article = await PersonalizationPipeline._supplier_ids_by_article(
            session, [article.id for article in articles]
        )

        # Score and rank articles
        scored_articles = await PersonalizationPipeline._score_articles(
            list(articles),
            pref,
            existing_article_ids,
            supplier_ids_by_article,
        )
        if not scored_articles:
            scored_articles = await PersonalizationPipeline._score_articles(
                list(articles),
                PersonalizationPipeline._fallback_preference(user_id, pref),
                existing_article_ids,
                supplier_ids_by_article,
            )

        # Sort by score (descending)
        scored_articles.sort(key=lambda x: x[1].overall_score, reverse=True)

        # Create feed entries
        feed_articles = []

        for rank, (article, score) in enumerate(scored_articles[:limit]):
            feed_entry = UserNewsFeed(
                user_id=user_id,
                processed_article_id=article.id,
                top_level_category=article.top_level_category,
                rank_score=score.overall_score,
                match_reasons={
                    "category": score.category_match,
                    "supplier": score.supplier_match,
                    "region": score.region_match,
                    "signal": score.signal_match,
                },
                related_sourcing_event_ids=[],
                surfaced_at=datetime.utcnow(),
                is_read=False,
                is_hidden=False,
            )
            feed_articles.append(feed_entry)

        # Save feed
        for entry in feed_articles:
            session.add(entry)

        await session.commit()

        return feed_articles, len(scored_articles), len(articles)

    @staticmethod
    async def get_user_feed(
        session: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> List[Tuple[NewsArticleProcessed, UserNewsFeed]]:
        """Get user's personalized feed with articles.

        Args:
            session: Database session
            user_id: User ID
            limit: Max articles to return

        Returns:
            List of (article, feed_entry) tuples
        """
        feed_query = await session.execute(
            select(UserNewsFeed)
            .where(UserNewsFeed.user_id == user_id)
            .order_by(desc(UserNewsFeed.rank_score))
            .limit(limit)
        )
        feed_entries = feed_query.scalars().all()

        results = []

        for entry in feed_entries:
            article = await session.get(NewsArticleProcessed, entry.processed_article_id)
            if article:
                results.append((article, entry))

        return results
