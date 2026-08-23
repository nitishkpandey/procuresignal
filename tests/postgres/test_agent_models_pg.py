"""The agent tables as the migration actually builds them.

The unit tests create the schema from the ORM, so a migration that disagrees with the
models passes every one of them. What is verified here is the schema that ships: the
uniqueness that keeps a transcript ordered, and the cascades that decide what survives a
deleted tenant.

Cascades in particular cannot be checked on SQLite at all — foreign keys are off by
default there — so an ON DELETE clause that never fires would look identical to one that
works.
"""

from datetime import datetime

import pytest
from procuresignal.models import (
    AgentRecommendation,
    AgentRun,
    AgentStep,
    Membership,
    Organization,
    Role,
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


async def _run(session: AsyncSession, organization_id: int, user_id: int, public_id: str) -> int:
    run = AgentRun(
        public_id=public_id,
        organization_id=organization_id,
        requested_by_user_id=user_id,
        supplier_public_id="acme-parts",
        status="running",
        model="gpt-5.4-mini",
        started_at=datetime.utcnow(),
    )
    session.add(run)
    await session.flush()
    return run.id


async def test_the_transcript_order_is_enforced_by_the_database(
    pg_session: AsyncSession,
) -> None:
    """Two workers appending to one run would both compute the same next ordinal. Only
    the constraint stops both from writing it."""

    organization_id, user_id = await _tenant(pg_session, "acme")
    run_id = await _run(pg_session, organization_id, user_id, "run-1")

    pg_session.add(AgentStep(run_id=run_id, ordinal=0, kind="model_message", payload_json={}))
    await pg_session.flush()

    pg_session.add(AgentStep(run_id=run_id, ordinal=0, kind="tool_call", payload_json={}))
    with pytest.raises(IntegrityError):
        await pg_session.flush()


async def test_recommendation_order_is_enforced_by_the_database(
    pg_session: AsyncSession,
) -> None:
    organization_id, user_id = await _tenant(pg_session, "acme")
    run_id = await _run(pg_session, organization_id, user_id, "run-1")

    pg_session.add(
        AgentRecommendation(
            run_id=run_id, ordinal=0, title="A", rationale="", evidence_event_keys=[]
        )
    )
    await pg_session.flush()

    pg_session.add(
        AgentRecommendation(
            run_id=run_id, ordinal=0, title="B", rationale="", evidence_event_keys=[]
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.flush()


async def test_deleting_a_run_takes_its_transcript_with_it(pg_session: AsyncSession) -> None:
    """Steps and recommendations have no meaning without the run they belong to.
    Orphans would accumulate forever and show up in every aggregate query."""

    organization_id, user_id = await _tenant(pg_session, "acme")
    run_id = await _run(pg_session, organization_id, user_id, "run-1")
    pg_session.add(AgentStep(run_id=run_id, ordinal=0, kind="model_message", payload_json={}))
    pg_session.add(
        AgentRecommendation(
            run_id=run_id, ordinal=0, title="A", rationale="", evidence_event_keys=[]
        )
    )
    await pg_session.commit()

    await pg_session.execute(text("DELETE FROM agent_runs WHERE id = :id"), {"id": run_id})
    await pg_session.commit()

    assert (await pg_session.execute(select(AgentStep))).scalars().all() == []
    assert (await pg_session.execute(select(AgentRecommendation))).scalars().all() == []


async def test_deleting_an_organization_takes_its_runs_with_it(
    pg_session: AsyncSession,
) -> None:
    organization_id, user_id = await _tenant(pg_session, "acme")
    await _run(pg_session, organization_id, user_id, "run-1")
    await pg_session.commit()

    await pg_session.execute(
        text("DELETE FROM organizations WHERE id = :id"), {"id": organization_id}
    )
    await pg_session.commit()

    assert (await pg_session.execute(select(AgentRun))).scalars().all() == []


async def test_a_decision_outlives_the_person_who_made_it(pg_session: AsyncSession) -> None:
    """The approval trail is the point of this table. Cascading the approver away would
    delete the record of who agreed to something, which is the one fact an audit is
    asking for a year later.
    """

    organization_id, user_id = await _tenant(pg_session, "acme")
    run_id = await _run(pg_session, organization_id, user_id, "run-1")
    _approver_org, approver_id = await _tenant(pg_session, "reviewer")
    pg_session.add(
        AgentRecommendation(
            run_id=run_id,
            ordinal=0,
            title="Qualify a second source",
            rationale="Open recall plus a strike.",
            evidence_event_keys=["acme-quality"],
            status="approved",
            decided_by_user_id=approver_id,
            decided_at=datetime.utcnow(),
            decision_note="Agreed in the Tuesday review.",
        )
    )
    await pg_session.commit()

    await pg_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": approver_id})
    await pg_session.commit()

    surviving = (await pg_session.execute(select(AgentRecommendation))).scalar_one()
    assert surviving.status == "approved"
    assert surviving.decision_note == "Agreed in the Tuesday review."
    assert surviving.decided_by_user_id is None


async def test_a_run_survives_the_supplier_registry_being_tidied(
    pg_session: AsyncSession,
) -> None:
    """`supplier_public_id` is deliberately not a foreign key: a run records what
    somebody asked and what was said, and merging two supplier rows must not erase the
    analysis that informed a decision."""

    organization_id, user_id = await _tenant(pg_session, "acme")
    run_id = await _run(pg_session, organization_id, user_id, "run-1")

    stored = await pg_session.get(AgentRun, run_id)
    assert stored is not None
    assert stored.supplier_public_id == "acme-parts"

    foreign_keys = await pg_session.scalar(
        text(
            "SELECT count(*) FROM information_schema.key_column_usage k "
            "JOIN information_schema.table_constraints c "
            "  ON c.constraint_name = k.constraint_name "
            "WHERE k.table_name = 'agent_runs' AND k.column_name = 'supplier_public_id' "
            "  AND c.constraint_type = 'FOREIGN KEY'"
        )
    )
    assert foreign_keys == 0


async def test_the_defaults_come_from_the_migration_not_only_the_orm(
    pg_session: AsyncSession,
) -> None:
    """Inserted with raw SQL, bypassing the ORM defaults, so what is asserted is what
    the shipped schema does when something other than SQLAlchemy writes a row."""

    organization_id, user_id = await _tenant(pg_session, "acme")
    await pg_session.execute(
        text(
            "INSERT INTO agent_runs (public_id, organization_id, requested_by_user_id, "
            "supplier_public_id, model, started_at) "
            "VALUES ('raw-1', :org, :user, 'acme-parts', 'gpt-5.4-mini', now())"
        ),
        {"org": organization_id, "user": user_id},
    )

    row = (
        await pg_session.execute(
            text(
                "SELECT status, step_count, prompt_tokens, completion_tokens "
                "FROM agent_runs WHERE public_id = 'raw-1'"
            )
        )
    ).one()

    assert row.status == "running"
    assert (row.step_count, row.prompt_tokens, row.completion_tokens) == (0, 0, 0)
