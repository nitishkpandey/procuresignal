"""Supplier analyses, and the human decisions about what they proposed.

Asking for an analysis is ordinary procurement work, so a member can do it. Approving a
recommendation puts the organization's name behind an action, so it needs an admin — the
same line Phase 5 drew between giving search feedback and exporting everyone's queries.

Decisions are one-way. `proposed → approved | rejected`, and deciding again is a 409
rather than a silent overwrite: an approval that can be quietly re-made is not an approval
trail, and the earlier decision would have nowhere to live.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.agents.analysis import analyse_supplier
from procuresignal.agents.client import AgentClient, agent_client
from procuresignal.auth.audit import record_audit
from procuresignal.models import AgentRecommendation, AgentRun, AgentStep, Role
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    AuthenticatedUser,
    ClientContext,
    get_client_context,
    get_current_user,
    get_session,
    require_role,
)
from api.schemas.agents import (
    AnalysisDetail,
    AnalysisListResponse,
    AnalysisRequest,
    AnalysisSummary,
    DecisionRequest,
    RecommendationOut,
    StepOut,
)

router = APIRouter(
    prefix="/api/analyses", tags=["analyses"], dependencies=[Depends(get_current_user)]
)

_MEMBER = Depends(require_role(Role.MEMBER))
_ADMIN = Depends(require_role(Role.ADMIN))

DECISIONS = {"approve": "approved", "reject": "rejected"}


def get_agent_client() -> AgentClient | None:
    """A dependency so tests can supply a scripted client without a key or a network."""

    return agent_client()


def _summary(run: AgentRun, recommendation_count: int = 0) -> AnalysisSummary:
    return AnalysisSummary(
        public_id=run.public_id,
        supplier_public_id=run.supplier_public_id,
        status=run.status,
        model=run.model,
        step_count=run.step_count,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        started_at=run.started_at,
        finished_at=run.finished_at,
        failure_reason=run.failure_reason,
        recommendation_count=recommendation_count,
    )


async def _owned(session: AsyncSession, public_id: str, user: AuthenticatedUser) -> AgentRun:
    """A run belonging to the caller's organization.

    404 rather than 403 for someone else's: a run holds a supplier's risk profile and
    somebody's reasoning about it, and a 403 confirms the id exists, which is how ids
    get enumerated.
    """

    run = (
        await session.execute(
            select(AgentRun)
            .where(AgentRun.public_id == public_id)
            .where(AgentRun.organization_id == user.organization_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return run


@router.post(
    "", response_model=AnalysisSummary, status_code=status.HTTP_201_CREATED, dependencies=[_MEMBER]
)
async def run_analysis(
    payload: AnalysisRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
    client: AgentClient | None = Depends(get_agent_client),
) -> AnalysisSummary:
    """Analyse one supplier now.

    Synchronous: a person asked for this and is waiting for it, which is also what keeps
    the cost bounded by human attention. The loop's step ceiling bounds how long that
    wait can get.

    ponytail: runs inline, so a very slow model ties up a worker for the duration. Move
    to the Celery queue with polling if analyses ever become something people fire off in
    bulk — which they cannot today, because nothing schedules them.
    """

    if client is None:
        # No fake analysis, ever. The same rule search follows without an embedding
        # provider: say the capability is off rather than produce something plausible.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supplier analysis is not configured on this instance.",
        )

    try:
        run = await analyse_supplier(
            session,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            supplier_public_id=payload.supplier_public_id,
            client=client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None

    count = await session.scalar(
        select(func.count())
        .select_from(AgentRecommendation)
        .where(AgentRecommendation.run_id == run.id)
    )
    await record_audit(
        session,
        action="agent.analysis_run",
        outcome="success",
        actor=current_user,
        resource_type="agent_run",
        resource_id=run.public_id,
        detail={
            "supplier_public_id": run.supplier_public_id,
            "model": run.model,
            "status": run.status,
            "recommendations": int(count or 0),
        },
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return _summary(run, int(count or 0))


@router.get("", response_model=AnalysisListResponse)
async def list_analyses(
    limit: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisListResponse:
    runs = (
        (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.organization_id == current_user.organization_id)
                .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.organization_id == current_user.organization_id)
    )
    return AnalysisListResponse(items=[_summary(run) for run in runs], total=int(total or 0))


@router.get("/{public_id}", response_model=AnalysisDetail)
async def get_analysis(
    public_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetail:
    """One analysis with its transcript. The transcript is the audit trail — a
    recommendation nobody can trace back to the tool calls that produced it is not
    reviewable."""

    run = await _owned(session, public_id, current_user)

    steps = (
        (
            await session.execute(
                select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.ordinal)
            )
        )
        .scalars()
        .all()
    )
    recommendations = (
        (
            await session.execute(
                select(AgentRecommendation)
                .where(AgentRecommendation.run_id == run.id)
                .order_by(AgentRecommendation.ordinal)
            )
        )
        .scalars()
        .all()
    )

    return AnalysisDetail(
        **_summary(run, len(recommendations)).model_dump(),
        steps=[
            StepOut(
                ordinal=step.ordinal,
                kind=step.kind,
                tool_name=step.tool_name,
                payload=step.payload_json or {},
            )
            for step in steps
        ],
        recommendations=[RecommendationOut.model_validate(item) for item in recommendations],
    )


@router.post(
    "/{public_id}/recommendations/{ordinal}/{decision}",
    response_model=RecommendationOut,
    dependencies=[_ADMIN],
)
async def decide(
    public_id: str,
    ordinal: int,
    decision: str,
    payload: DecisionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> RecommendationOut:
    """Approve or reject one recommendation.

    Records the decision and nothing else — no notification fires and no tenant data
    changes. Wiring approval to an action is a decision worth making once these
    recommendations have a track record, and it is a small change on top of this.
    """

    if decision not in DECISIONS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown decision")

    run = await _owned(session, public_id, current_user)
    recommendation = (
        await session.execute(
            select(AgentRecommendation)
            .where(AgentRecommendation.run_id == run.id)
            .where(AgentRecommendation.ordinal == ordinal)
        )
    ).scalar_one_or_none()
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found"
        )

    if recommendation.status != "proposed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Already {recommendation.status} and decisions are not reversible.",
        )

    recommendation.status = DECISIONS[decision]
    recommendation.decided_by_user_id = current_user.id
    recommendation.decided_at = datetime.utcnow()
    recommendation.decision_note = payload.note or None

    # Naming the run and the ordinal matters as much as naming the actor: an audit line
    # that says only "approved something" is not evidence of anything.
    await record_audit(
        session,
        action=f"agent.recommendation_{DECISIONS[decision]}",
        outcome="success",
        actor=current_user,
        resource_type="agent_run",
        resource_id=run.public_id,
        detail={
            "ordinal": ordinal,
            "title": recommendation.title,
            "note": payload.note,
            "evidence_event_keys": recommendation.evidence_event_keys,
        },
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return RecommendationOut.model_validate(recommendation)
