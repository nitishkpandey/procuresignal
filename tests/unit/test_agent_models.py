"""The durable record of what the agent did.

Nothing here calls a model. These tables exist so that the loop built in Task 2 cannot
run without leaving a trail, and so that "which runs recommended switching supplier, and
on what evidence" is a query rather than a reading exercise.

The transcript is a table rather than a JSON column on the run for exactly that reason. A
blob is unqueryable, and the question a reviewer asks after a bad recommendation is
always about a pattern across runs.
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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _tenant(session: AsyncSession, slug: str = "acme") -> tuple[int, int]:
    organization = Organization(public_id=f"org-{slug}", name=slug, slug=slug)
    session.add(organization)
    await session.flush()
    user = User(public_id=f"user-{slug}", email=f"buyer@{slug}.example", is_active=True)
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.ADMIN))
    await session.flush()
    return organization.id, user.id


async def _run(session: AsyncSession, organization_id: int, user_id: int, **overrides) -> AgentRun:
    run = AgentRun(
        public_id=overrides.pop("public_id", "run-1"),
        organization_id=organization_id,
        requested_by_user_id=user_id,
        supplier_public_id="acme-parts",
        status="running",
        model="gpt-5.4-mini",
        started_at=datetime.utcnow(),
        **overrides,
    )
    session.add(run)
    await session.flush()
    return run


async def test_a_run_records_who_asked_and_about_what(async_session: AsyncSession) -> None:
    organization_id, user_id = await _tenant(async_session)

    run = await _run(async_session, organization_id, user_id)

    assert run.status == "running"
    assert run.supplier_public_id == "acme-parts"
    assert run.requested_by_user_id == user_id
    assert run.step_count == 0
    assert run.finished_at is None


async def test_a_run_starts_with_no_spend_recorded(async_session: AsyncSession) -> None:
    """Token counts live on the run because "what did this feature cost" is a question
    the daily budget cap can only answer in aggregate."""

    organization_id, user_id = await _tenant(async_session)

    run = await _run(async_session, organization_id, user_id)

    assert run.prompt_tokens == 0
    assert run.completion_tokens == 0


async def test_steps_keep_the_order_they_happened_in(async_session: AsyncSession) -> None:
    """A transcript out of order is not a transcript. The ordinal is explicit rather
    than inferred from the primary key, which is an implementation detail that
    reordering inserts would quietly break."""

    organization_id, user_id = await _tenant(async_session)
    run = await _run(async_session, organization_id, user_id)

    for ordinal, (kind, tool) in enumerate(
        [
            ("model_message", None),
            ("tool_call", "get_supplier_impact"),
            ("tool_result", "get_supplier_impact"),
        ]
    ):
        async_session.add(
            AgentStep(
                run_id=run.id,
                ordinal=ordinal,
                kind=kind,
                tool_name=tool,
                payload_json={"note": kind},
            )
        )
    await async_session.flush()

    steps = (
        (
            await async_session.execute(
                select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.ordinal)
            )
        )
        .scalars()
        .all()
    )
    assert [step.kind for step in steps] == ["model_message", "tool_call", "tool_result"]
    assert steps[1].tool_name == "get_supplier_impact"


async def test_a_run_cannot_have_two_steps_in_the_same_position(
    async_session: AsyncSession,
) -> None:
    organization_id, user_id = await _tenant(async_session)
    run = await _run(async_session, organization_id, user_id)

    async_session.add(AgentStep(run_id=run.id, ordinal=0, kind="model_message", payload_json={}))
    await async_session.flush()

    async_session.add(AgentStep(run_id=run.id, ordinal=0, kind="tool_call", payload_json={}))
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_two_runs_number_their_steps_independently(async_session: AsyncSession) -> None:
    organization_id, user_id = await _tenant(async_session)
    first = await _run(async_session, organization_id, user_id, public_id="run-1")
    second = await _run(async_session, organization_id, user_id, public_id="run-2")

    async_session.add(AgentStep(run_id=first.id, ordinal=0, kind="model_message", payload_json={}))
    async_session.add(AgentStep(run_id=second.id, ordinal=0, kind="model_message", payload_json={}))
    await async_session.flush()

    assert len((await async_session.execute(select(AgentStep))).scalars().all()) == 2


async def test_a_recommendation_starts_proposed(async_session: AsyncSession) -> None:
    """The model never approves anything, including its own output. `proposed` is the
    only state the loop is allowed to create."""

    organization_id, user_id = await _tenant(async_session)
    run = await _run(async_session, organization_id, user_id)

    recommendation = AgentRecommendation(
        run_id=run.id,
        ordinal=0,
        title="Qualify a second source for injection modules",
        rationale="The incumbent has an open quality recall and a strike at its main plant.",
        evidence_event_keys=["acme-quality-2026-08", "acme-strike-2026-08"],
    )
    async_session.add(recommendation)
    await async_session.flush()

    assert recommendation.status == "proposed"
    assert recommendation.decided_by_user_id is None
    assert recommendation.decided_at is None


async def test_a_recommendation_carries_the_events_it_rests_on(
    async_session: AsyncSession,
) -> None:
    """Evidence is `RiskEvent.event_key` values, not free text, so "show me the
    evidence" is a join rather than a reading exercise — and a fabricated citation is
    detectable instead of merely implausible."""

    organization_id, user_id = await _tenant(async_session)
    run = await _run(async_session, organization_id, user_id)

    async_session.add(
        AgentRecommendation(
            run_id=run.id,
            ordinal=0,
            title="Hold new orders",
            rationale="Sanctions designation is active.",
            evidence_event_keys=["designated-2026-08"],
        )
    )
    await async_session.flush()

    stored = (await async_session.execute(select(AgentRecommendation))).scalar_one()
    assert stored.evidence_event_keys == ["designated-2026-08"]


async def test_a_run_cannot_have_two_recommendations_in_the_same_position(
    async_session: AsyncSession,
) -> None:
    organization_id, user_id = await _tenant(async_session)
    run = await _run(async_session, organization_id, user_id)

    async_session.add(
        AgentRecommendation(
            run_id=run.id, ordinal=0, title="A", rationale="", evidence_event_keys=[]
        )
    )
    await async_session.flush()

    async_session.add(
        AgentRecommendation(
            run_id=run.id, ordinal=0, title="B", rationale="", evidence_event_keys=[]
        )
    )
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_public_ids_are_unique_across_runs(async_session: AsyncSession) -> None:
    """The API addresses a run by public id; two runs sharing one would let a member of
    the wrong organization reach somebody else's analysis by guessing."""

    organization_id, user_id = await _tenant(async_session)
    await _run(async_session, organization_id, user_id, public_id="duplicate")

    with pytest.raises(IntegrityError):
        await _run(async_session, organization_id, user_id, public_id="duplicate")


async def test_a_failed_run_says_why(async_session: AsyncSession) -> None:
    """A truncated analysis presented as a finished one is worse than an error, so the
    reason a run stopped is a column rather than something to infer from step count."""

    organization_id, user_id = await _tenant(async_session)
    run = await _run(async_session, organization_id, user_id)

    run.status = "failed"
    run.failure_reason = "step_ceiling"
    run.finished_at = datetime.utcnow()
    await async_session.flush()

    assert run.failure_reason == "step_ceiling"
