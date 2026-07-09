"""Assemble the chat system prompt from user preferences and recent feed."""

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import NewsArticleProcessed, UserNewsFeed
from procuresignal.personalization import PreferenceManager

_BASE_PERSONA = (
    "You are ProcureSignal, an AI procurement intelligence analyst. "
    "You help supply chain and procurement professionals understand news about "
    "suppliers, regions, tariffs, strikes, and supply-chain risks. "
    "Be concise, factual, and actionable. If you are unsure, say so."
)

# Keep the digest small so chat requests stay fast and inexpensive.
_RECENT_ARTICLE_LIMIT = 6
_SUMMARY_CHARS = 200


async def _recent_articles(session: AsyncSession, user_id: str) -> list[tuple[str, str, list]]:
    stmt = (
        select(
            NewsArticleProcessed.normalized_title,
            NewsArticleProcessed.summary,
            NewsArticleProcessed.signal_tags,
        )
        .join(UserNewsFeed, UserNewsFeed.processed_article_id == NewsArticleProcessed.id)
        .where(UserNewsFeed.user_id == user_id)
        .where(UserNewsFeed.is_hidden.is_(False))
        .order_by(desc(UserNewsFeed.surfaced_at))
        .limit(_RECENT_ARTICLE_LIMIT)
    )
    result = await session.execute(stmt)
    return [(title, summary, tags or []) for title, summary, tags in result.all()]


async def build_system_prompt(session: AsyncSession, user_id: str) -> str:
    """Build a context-aware system prompt for the user's chat session."""

    parts: list[str] = [_BASE_PERSONA]

    pref = await PreferenceManager.get_preference(session, user_id)
    if pref is not None:
        focus: list[str] = []
        if pref.preferred_suppliers:
            focus.append(f"Suppliers: {', '.join(pref.preferred_suppliers)}")
        if pref.preferred_regions:
            focus.append(f"Regions: {', '.join(pref.preferred_regions)}")
        if pref.preferred_categories:
            focus.append(f"Categories: {', '.join(pref.preferred_categories)}")
        if pref.preferred_signals:
            focus.append(f"Signals: {', '.join(pref.preferred_signals)}")
        if focus:
            parts.append("The user follows — " + "; ".join(focus) + ".")

    articles = await _recent_articles(session, user_id)
    if articles:
        digest = "\n".join(
            f"- {title} [{', '.join(tags) if tags else 'no tags'}]: {summary[:_SUMMARY_CHARS]}"
            for title, summary, tags in articles
        )
        parts.append("Recent relevant articles in the user's feed:\n" + digest)

    parts.append("Answer the user's questions grounded in this context when relevant.")
    return "\n\n".join(parts)
