"""The feedback table's guarantees, enforced by the database that ships.

The API tests run on SQLite and prove the endpoint deduplicates. What they cannot prove
is that the constraint exists in the migrated schema — SQLite builds its tables from the
ORM in those tests, so a migration that forgot the unique constraint would pass every one
of them and let two workers write the same label in production.
"""

from datetime import datetime

import pytest
from procuresignal.models import (
    Membership,
    NewsArticleProcessed,
    NewsArticleRaw,
    Organization,
    Role,
    SearchFeedback,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


async def _tenant(session: AsyncSession, slug: str) -> tuple[int, int]:
    organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
    session.add(organization)
    await session.flush()
    user = User(public_id=f"user-{slug}", email=f"buyer@{slug}.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return organization.id, user.id


async def _article(session: AsyncSession) -> int:
    now = datetime.utcnow()
    raw = NewsArticleRaw(
        provider="test",
        query_group="test",
        ingest_hash=f"hash-{now.timestamp()}",
        title="Rotterdam port strike",
        article_url="https://example.com/1",
        source_name="Reuters",
        published_at=now,
        language="en",
        ingested_at=now,
    )
    session.add(raw)
    await session.flush()
    processed = NewsArticleProcessed(
        raw_article_id=raw.id,
        normalized_title="Rotterdam port strike",
        summary="Dockworkers walked out.",
        top_level_category="logistics",
        signal_score=0.5,
        processing_status="completed",
        language="en",
        processed_at=now,
    )
    session.add(processed)
    await session.flush()
    return processed.id


def _feedback(organization_id: int, user_id: int, article_id: int, **overrides) -> SearchFeedback:
    values = {
        "organization_id": organization_id,
        "user_id": user_id,
        "query_text": "port strike",
        "query_fingerprint": "f" * 64,
        "processed_article_id": article_id,
        "rank_position": 1,
        "signal": "click",
        "mode": "hybrid",
        **overrides,
    }
    return SearchFeedback(**values)


async def test_the_same_label_cannot_be_written_twice(pg_session: AsyncSession) -> None:
    """Two clicks racing each other both read no row; only the constraint stops both
    from inserting."""

    organization_id, user_id = await _tenant(pg_session, "acme")
    article_id = await _article(pg_session)

    pg_session.add(_feedback(organization_id, user_id, article_id))
    await pg_session.flush()

    pg_session.add(_feedback(organization_id, user_id, article_id))
    with pytest.raises(IntegrityError):
        await pg_session.flush()


async def test_two_users_may_judge_the_same_result(pg_session: AsyncSession) -> None:
    """The label belongs to a person. Deduplicating across users would throw away the
    agreement that makes a label trustworthy."""

    first_org, first_user = await _tenant(pg_session, "acme")
    _second_org, second_user = await _tenant(pg_session, "globex")
    article_id = await _article(pg_session)

    pg_session.add(_feedback(first_org, first_user, article_id))
    pg_session.add(_feedback(first_org, second_user, article_id))
    await pg_session.flush()

    rows = (await pg_session.execute(select(SearchFeedback))).scalars().all()
    assert len(rows) == 2


async def test_feedback_survives_the_article_it_judged(pg_session: AsyncSession) -> None:
    """The reason `processed_article_id` carries no foreign key.

    Retention prunes processed articles after 30 days. If the labels went with them the
    training set could never hold more than 30 days of feedback, which cannot support a
    train/test split — and collecting data for that split is the only reason this table
    exists yet.
    """

    organization_id, user_id = await _tenant(pg_session, "acme")
    article_id = await _article(pg_session)
    pg_session.add(_feedback(organization_id, user_id, article_id))
    await pg_session.commit()

    await pg_session.execute(
        text("DELETE FROM news_articles_processed WHERE id = :id"), {"id": article_id}
    )
    await pg_session.commit()

    surviving = (await pg_session.execute(select(SearchFeedback))).scalars().all()
    assert len(surviving) == 1
    assert surviving[0].processed_article_id == article_id


async def test_erasing_a_user_erases_their_feedback(pg_session: AsyncSession) -> None:
    """Query text is personal data, so it goes when the person does. Phase 7 may decide
    anonymised retention is better; this is the behaviour it would be changing from, and
    it is recorded in docs/personal-data-inventory.md.
    """

    organization_id, user_id = await _tenant(pg_session, "acme")
    article_id = await _article(pg_session)
    pg_session.add(_feedback(organization_id, user_id, article_id))
    await pg_session.commit()

    await pg_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await pg_session.commit()

    assert (await pg_session.execute(select(SearchFeedback))).scalars().all() == []
