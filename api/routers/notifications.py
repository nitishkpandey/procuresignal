"""Notification feed and alert-rule endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from procuresignal.auth.audit import record_audit
from procuresignal.models import AlertRule, Notification, RiskEvent, Role
from procuresignal.notifications.rules import (
    SEVERITY_ORDER,
    AlertRuleError,
    DuplicateAlertRuleError,
    create_alert_rule,
)
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
from api.schemas.notification import (
    AlertRuleCreate,
    AlertRuleItem,
    AlertRuleListResponse,
    NotificationItem,
    NotificationListResponse,
)

router = APIRouter(prefix="/api", tags=["notifications"], dependencies=[Depends(get_current_user)])

_MEMBER = Depends(require_role(Role.MEMBER))


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationListResponse:
    """The caller's own delivered alerts, newest first.

    Only delivered ones. A queued notification is owed rather than sent, and showing it
    here would notify the user twice — once early and once when the transport catches up.
    """

    rows = (
        await session.execute(
            select(Notification, AlertRule.name, RiskEvent.risk_type, RiskEvent.severity)
            .join(AlertRule, AlertRule.id == Notification.alert_rule_id)
            .join(RiskEvent, RiskEvent.id == Notification.risk_event_id)
            .where(Notification.recipient_user_id == current_user.id)
            .where(Notification.status == "delivered")
            .order_by(Notification.delivered_at.desc(), Notification.id.desc())
            .limit(limit)
        )
    ).all()

    unread = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_user_id == current_user.id)
        .where(Notification.status == "delivered")
        .where(Notification.read_at.is_(None))
    )

    items = [
        NotificationItem(
            public_id=notification.public_id,
            subject=notification.subject,
            body=notification.body,
            rule_name=rule_name,
            risk_type=risk_type,
            severity=severity,
            supplier_public_ids=list(notification.supplier_public_ids or []),
            delivered_at=notification.delivered_at,
            read_at=notification.read_at,
        )
        for notification, rule_name, risk_type, severity in rows
    ]

    return NotificationListResponse(
        items=items, total_count=len(items), unread_count=int(unread or 0)
    )


@router.post("/notifications/{public_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    public_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Mark one of the caller's own alerts read.

    Scoped to the recipient, so someone else's id is a 404 rather than a 403 that
    confirms it exists.
    """

    notification = (
        await session.execute(
            select(Notification)
            .where(Notification.public_id == public_id)
            .where(Notification.recipient_user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if notification.read_at is None:
        from datetime import datetime

        notification.read_at = datetime.utcnow()
    await session.commit()


@router.get("/alert-rules", response_model=AlertRuleListResponse)
async def list_rules(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlertRuleListResponse:
    rules = (
        (
            await session.execute(
                select(AlertRule)
                .where(AlertRule.organization_id == current_user.organization_id)
                .order_by(AlertRule.name)
            )
        )
        .scalars()
        .all()
    )

    items = [
        AlertRuleItem(
            public_id=rule.public_id,
            name=rule.name,
            min_severity=rule.min_severity,
            risk_types=list(rule.risk_types or []),
            is_enabled=rule.is_enabled,
        )
        for rule in rules
    ]
    return AlertRuleListResponse(items=items, total_count=len(items))


@router.post(
    "/alert-rules",
    response_model=AlertRuleItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MEMBER],
)
async def create_rule(
    payload: AlertRuleCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    context: ClientContext = Depends(get_client_context),
    session: AsyncSession = Depends(get_session),
) -> AlertRuleItem:
    try:
        rule = await create_alert_rule(
            session,
            organization_id=current_user.organization_id,
            name=payload.name,
            min_severity=payload.min_severity,
            risk_types=payload.risk_types,
            created_by_user_id=current_user.id,
        )
    except DuplicateAlertRuleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except AlertRuleError as exc:
        # The message names the accepted severities, so the caller can fix it without
        # reading the source.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    await record_audit(
        session,
        action="alert_rule.create",
        outcome="success",
        actor=current_user,
        resource_type="alert_rule",
        resource_id=rule.public_id,
        detail={
            "name": rule.name,
            "min_severity": rule.min_severity,
            "risk_types": rule.risk_types,
            "severities_available": list(SEVERITY_ORDER),
        },
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    await session.commit()

    return AlertRuleItem(
        public_id=rule.public_id,
        name=rule.name,
        min_severity=rule.min_severity,
        risk_types=list(rule.risk_types or []),
        is_enabled=rule.is_enabled,
    )
