"""Retention against the schema that ships.

Two things cannot be checked on SQLite. Foreign keys are off there, so a delete that
should cascade to a child table looks identical to one that leaves orphans. And
`audit_log` carries triggers refusing DELETE — a retention job that ever tried to prune
it would raise on PostgreSQL and pass silently in the in-memory suite.
"""

from datetime import datetime, timedelta

import pytest
from procuresignal.jobs.retention import prune_expired_records
from procuresignal.models import (
    AgentRecommendation,
    AgentRun,
    AgentStep,
    AuditLog,
    Membership,
    Organization,
    Role,
    SearchFeedback,
    User,
)
from procuresignal.privacy.inventory import INVENTORY
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres

NOW = datetime.utcnow()
LONG_AGO = NOW - timedelta(days=500)


async def _tenant(session: AsyncSession, slug: str) -> tuple[int, int]:
    organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
    session.add(organization)
    await session.flush()
    user = User(public_id=f"user-{slug}", email=f"b@{slug}.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return organization.id, user.id


async def test_pruning_a_run_takes_its_transcript_with_it(pg_session: AsyncSession) -> None:
    """`agent_steps` and `agent_recommendations` have no window of their own — they are
    reached through the run's cascade. On SQLite that cascade never fires, so orphaned
    transcripts would accumulate invisibly."""

    organization_id, user_id = await _tenant(pg_session, "acme")
    run = AgentRun(
        public_id="stale-run",
        organization_id=organization_id,
        requested_by_user_id=user_id,
        supplier_public_id="acme-parts",
        status="completed",
        model="gpt-5.4-mini",
        started_at=LONG_AGO,
    )
    pg_session.add(run)
    await pg_session.flush()
    pg_session.add(AgentStep(run_id=run.id, ordinal=0, kind="model_message", payload_json={}))
    pg_session.add(
        AgentRecommendation(
            run_id=run.id, ordinal=0, title="x", rationale="y", evidence_event_keys=[]
        )
    )
    await pg_session.commit()

    await prune_expired_records(pg_session, now=NOW)

    assert (await pg_session.execute(select(AgentRun))).scalars().all() == []
    assert (await pg_session.execute(select(AgentStep))).scalars().all() == []
    assert (await pg_session.execute(select(AgentRecommendation))).scalars().all() == []


async def test_one_persons_expiry_does_not_touch_another(pg_session: AsyncSession) -> None:
    """Retention is about age, not about people. A window applied by user would be a
    bug that only shows up as somebody else's missing data."""

    first_org, first_user = await _tenant(pg_session, "acme")
    second_org, second_user = await _tenant(pg_session, "globex")

    for org, user, created in [
        (first_org, first_user, LONG_AGO),
        (second_org, second_user, NOW),
    ]:
        pg_session.add(
            SearchFeedback(
                organization_id=org,
                user_id=user,
                query_text=f"query-{user}",
                query_fingerprint=f"{user}" * 10,
                processed_article_id=1,
                rank_position=1,
                signal="click",
                mode="hybrid",
                created_at=created,
            )
        )
    await pg_session.commit()

    await prune_expired_records(pg_session, now=NOW)

    surviving = (await pg_session.execute(select(SearchFeedback))).scalars().all()
    assert [row.user_id for row in surviving] == [second_user]


async def test_retention_never_tries_to_prune_the_audit_log(pg_session: AsyncSession) -> None:
    """The append-only triggers would raise. That the job completes at all is the
    assertion; the surviving row is what makes it meaningful."""

    _organization_id, _user_id = await _tenant(pg_session, "acme")
    pg_session.add(
        AuditLog(
            action="test.event",
            outcome="success",
            actor_email="b@acme.example",
            detail={},
            created_at=LONG_AGO,
        )
    )
    await pg_session.commit()

    await prune_expired_records(pg_session, now=NOW)

    assert len((await pg_session.execute(select(AuditLog))).scalars().all()) == 1


async def test_the_audit_log_still_refuses_deletion(pg_session: AsyncSession) -> None:
    """Pinned separately so the reason retention skips it stays true. If the triggers
    were ever dropped, this fails and the registry's Article 17(3) note becomes a
    statement about a database that no longer behaves that way."""

    pg_session.add(AuditLog(action="test.event", outcome="success", detail={}, created_at=LONG_AGO))
    await pg_session.commit()

    with pytest.raises(Exception, match="append-only"):
        await pg_session.execute(text("DELETE FROM audit_log"))
    await pg_session.rollback()


async def test_every_registered_window_names_a_column_that_exists(
    pg_session: AsyncSession,
) -> None:
    """Checked against the migrated schema rather than the ORM, so a column the models
    declare and the migration forgot fails here."""

    for entry in INVENTORY:
        if entry.retention_days is None:
            continue
        found = await pg_session.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": entry.table, "column": entry.retention_column},
        )
        assert found == 1, f"{entry.table}.{entry.retention_column} is not in the schema"


async def test_a_clean_database_prunes_nothing_and_does_not_fail(
    pg_session: AsyncSession,
) -> None:
    """The job runs nightly against an instance that is usually already tidy."""

    result = await prune_expired_records(pg_session, now=NOW)

    assert set(result.by_table) == {
        entry.table for entry in INVENTORY if entry.retention_days is not None
    }
    assert all(count == 0 for count in result.by_table.values())
