"""Personalization pipeline orchestration."""

from datetime import datetime, timedelta
from typing import List, Tuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import (
    NewsArticleProcessed,
    UserNewsFeed,
    UserNewsPreference,
)
from procuresignal.personalization.matcher import PreferenceMatcher


class PersonalizationPipeline:
    """Orchestrate personalized feed generation."""

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
                interested_categories=[],
                interested_suppliers=[],
                interested_regions=[],
                interested_signals=[],
            )

        # Get recent articles
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        articles_query = await session.execute(
            select(NewsArticleProcessed)
            .where(NewsArticleProcessed.processed_at >= cutoff_date)
            .order_by(desc(NewsArticleProcessed.processed_at))
        )
        articles = articles_query.scalars().all()

        # Score and rank articles
        scored_articles = []

        for article in articles:
            score = await PreferenceMatcher.score_article(article, pref)

            # Only include if score > threshold (0.3)
            if score.overall_score >= 0.3:
                scored_articles.append((article, score))

        # Sort by score (descending)
        scored_articles.sort(key=lambda x: x[1].overall_score, reverse=True)

        # Create feed entries
        feed_articles = []

        for rank, (article, score) in enumerate(scored_articles[:limit]):
            feed_entry = UserNewsFeed(
                user_id=user_id,
                article_id=article.id,
                relevance_score=score.overall_score,
                rank=rank + 1,
                match_breakdown={
                    "category": score.category_match,
                    "supplier": score.supplier_match,
                    "region": score.region_match,
                    "signal": score.signal_match,
                },
                added_to_feed_at=datetime.utcnow(),
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
            .order_by(UserNewsFeed.rank)
            .limit(limit)
        )
        feed_entries = feed_query.scalars().all()

        results = []

        for entry in feed_entries:
            article = await session.get(NewsArticleProcessed, entry.article_id)
            if article:
                results.append((article, entry))

        return results
