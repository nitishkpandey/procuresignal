"""Record tasks that exhausted their retries.

Reuses the audit log's scrubber rather than defining a second idea of what counts as
sensitive. Two definitions drift, and the stale one is always the one holding a token.
"""

import logging
import traceback as traceback_module

from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.auth.audit import scrub
from procuresignal.models import DeadLetter

logger = logging.getLogger(__name__)

_MESSAGE_LIMIT = 4000
_TRACEBACK_LIMIT = 20000


def _serializable(payload: dict | None) -> dict:
    """Scrub the payload and drop anything that will not survive JSON.

    A dead letter must never fail to record because the arguments that killed the task
    also cannot be stored.
    """

    scrubbed = scrub(payload or {})
    safe: dict = {}
    for key, value in scrubbed.items():
        if isinstance(value, (str, int, float, bool, type(None), list, dict)):
            safe[str(key)] = value
        else:
            safe[str(key)] = repr(value)[:200]
    return safe


async def record_dead_letter(
    session: AsyncSession,
    *,
    task_name: str,
    task_id: str | None,
    payload: dict | None,
    error: BaseException,
    retries: int,
) -> None:
    """Store one exhausted task. Never raises.

    A failure while recording a failure would replace the original error with a less
    useful one, so problems here are logged and swallowed.
    """

    try:
        session.add(
            DeadLetter(
                task_name=task_name,
                task_id=task_id,
                payload=_serializable(payload),
                error_type=type(error).__name__,
                error_message=str(error)[:_MESSAGE_LIMIT],
                traceback="".join(
                    traceback_module.format_exception(type(error), error, error.__traceback__)
                )[:_TRACEBACK_LIMIT],
                retries=retries,
            )
        )
    except Exception:  # noqa: BLE001 - must not mask the failure being recorded
        logger.exception("could not record dead letter for %s", task_name)
