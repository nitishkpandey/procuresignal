"""Append-only audit writer."""

from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import AuditLog

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from api.dependencies import AuthenticatedUser

REDACTED = "[redacted]"

# Matched as substrings against lower-cased keys, so `new_password` and `X-Auth-Token`
# are caught as well as the exact names.
_SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "credential",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def scrub(value: Any) -> Any:
    """Replace credential-bearing values anywhere in a nested structure.

    The key is kept and the value replaced, so the record still shows that something was
    supplied without storing it.
    """

    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else scrub(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    outcome: str,
    actor: Optional["AuthenticatedUser"] = None,
    organization_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Append one audit record. Never updates or deletes an existing row.

    `actor` is optional because failed sign-ins and anonymous rejections still need a
    trail, and at that point there is nobody authenticated to attribute them to.
    """

    session.add(
        AuditLog(
            organization_id=organization_id or (actor.organization_id if actor else None),
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            detail=scrub(detail or {}),
            client_ip=client_ip,
            user_agent=user_agent[:300] if user_agent else None,
        )
    )
