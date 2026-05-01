"""Database seeding for development and testing."""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from shared.procuresignal.models import (
    NewsArticleRaw,
    NewsArticleProcessed,
    UserNewsPreference,
    NewsPipelineRun,
)


async def seed_test_data(session: AsyncSession) -> None:
    """Seed database with test data for development."""

    pipeline_run = NewsPipelineRun(
        started_at=datetime.utcnow() - timedelta(hours=1),
        finished_at=datetime.utcnow(),
        status="success",
        articles_fetched=150,
        articles_kept=42,
        articles_rejected=108,
        duplicates_removed=5,
        articles_sent_to_llm=42,
        feeds_materialized=12,
    )
    session.add(pipeline_run)

    raw_article = NewsArticleRaw(
        provider="newsapi",
        provider_article_id="article-12345",
        query_group="supplier_risk",
        ingest_hash="hash_article_12345",
        title="Bosch announces new manufacturing facility in Poland",
        description="Bosch Group opens new automotive supplier facility in Poznan",
        content_snippet="The facility will produce EV components...",
        article_url="https://example.com/article",
        canonical_url="https://example.com/article",
        source_name="Reuters",
        source_url="https://reuters.com",
        published_at=datetime.utcnow() - timedelta(days=1),
        language="en",
        ingested_at=datetime.utcnow() - timedelta(hours=1),
    )
    session.add(raw_article)

    await session.flush()

    processed_article = NewsArticleProcessed(
        raw_article_id=raw_article.id,
        normalized_title="Bosch manufacturing facility Poland",
        summary=(
            "Bosch announced a new automotive EV component manufacturing facility in Poznan, Poland. "
            "The facility will focus on battery management systems and electric drivetrain components. "
            "Production is expected to start in 2026 with an initial investment of EUR 50 million."
        ),
        top_level_category="suppliers",
        signal_tags=["expansion", "manufacturing", "ev_components", "poland"],
        priority_signal=None,
        detected_regions=["Poland"],
        detected_suppliers=["Bosch"],
        detected_categories=["automotive", "ev_components"],
        signal_score=0.87,
        processing_status="completed",
        llm_model="groq/llama-3.1-8b",
        language="en",
        processed_at=datetime.utcnow() - timedelta(hours=1),
    )
    session.add(processed_article)

    await session.flush()

    user1_prefs = UserNewsPreference(
        user_id="user-bosch-buyer",
        preferred_suppliers=["Bosch", "Siemens", "Continental"],
        preferred_regions=["Germany", "Poland", "Czech Republic"],
        preferred_categories=["automotive", "manufacturing", "ev_components"],
        excluded_topics=["general_news", "politics"],
        onboarding_completed=True,
    )
    session.add(user1_prefs)

    user2_prefs = UserNewsPreference(
        user_id="user-industrial-buyer",
        preferred_suppliers=["ABB", "Schneider Electric", "Siemens"],
        preferred_regions=["Sweden", "Germany", "Netherlands"],
        preferred_categories=["industrial_automation", "energy"],
        excluded_topics=[],
        onboarding_completed=True,
    )
    session.add(user2_prefs)

    await session.commit()
    print("Seed data inserted successfully")
