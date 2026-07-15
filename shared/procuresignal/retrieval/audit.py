"""Atomic, short-lived claims and sanitized retrieval outcomes."""

import re
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from ..models import NewsRetrievalRun, NewsRetrievalSourceOutcome

_SAFE_DETAIL = re.compile(r"^[a-z0-9_.:-]{1,100}$", re.IGNORECASE)


def run_candidate_statement(now: datetime, *, skip_locked: bool = False) -> Select[tuple[int]]:
    statement = (
        select(NewsRetrievalRun.id)
        .where(
            or_(
                NewsRetrievalRun.status == "pending",
                and_(
                    NewsRetrievalRun.status == "running",
                    NewsRetrievalRun.lease_expires_at < now,
                ),
            )
        )
        .order_by(NewsRetrievalRun.started_at, NewsRetrievalRun.id)
        .limit(1)
    )
    return statement.with_for_update(skip_locked=True) if skip_locked else statement


class RetrievalAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_run(
        self, owner: str, now: datetime, lease_duration: timedelta
    ) -> NewsRetrievalRun | None:
        postgres = self.session.bind is not None and self.session.bind.dialect.name == "postgresql"
        candidate = run_candidate_statement(now, skip_locked=postgres)
        candidate_id = await self.session.scalar(candidate)
        if candidate_id is None:
            return None
        statement = (
            update(NewsRetrievalRun)
            .where(
                NewsRetrievalRun.id == candidate_id,
                or_(
                    NewsRetrievalRun.status == "pending",
                    and_(
                        NewsRetrievalRun.status == "running",
                        NewsRetrievalRun.lease_expires_at < now,
                    ),
                ),
            )
            .values(status="running", lease_owner=owner, lease_expires_at=now + lease_duration)
        )
        result = cast(CursorResult[object], await self.session.execute(statement))
        if result.rowcount != 1:
            await self.session.rollback()
            return None
        await self.session.commit()
        return await self.session.get(NewsRetrievalRun, candidate_id)

    async def claim_source(self, run_id: int, source_id: str, now: datetime) -> bool:
        nested = await self.session.begin_nested()
        self.session.add(
            NewsRetrievalSourceOutcome(
                run_id=run_id,
                source_id=source_id,
                status="running",
                started_at=now,
                attempted_count=1,
            )
        )
        try:
            await self.session.flush()
            await nested.commit()
            await self.session.commit()
            return True
        except IntegrityError:
            await nested.rollback()
            await self.session.rollback()
            return False

    async def complete_source(self, run_id: int, source_id: str, **counts: int) -> bool:
        values: dict[str, object] = {"status": "completed", "finished_at": datetime.utcnow()}
        values.update(counts)
        return await self._update_source(run_id, source_id, values)

    async def fail_source(
        self, run_id: int, source_id: str, failure_code: str, detail: str | None = None
    ) -> bool:
        safe_detail = detail if detail is not None and _SAFE_DETAIL.fullmatch(detail) else None
        return await self._update_source(
            run_id,
            source_id,
            {
                "status": "failed",
                "failed_count": 1,
                "failure_code": failure_code[:50],
                "outcome_detail": safe_detail,
                "finished_at": datetime.utcnow(),
            },
        )

    async def _update_source(self, run_id: int, source_id: str, values: dict[str, object]) -> bool:
        result = cast(
            CursorResult[object],
            await self.session.execute(
                update(NewsRetrievalSourceOutcome)
                .where(
                    NewsRetrievalSourceOutcome.run_id == run_id,
                    NewsRetrievalSourceOutcome.source_id == source_id,
                )
                .values(**values)
            ),
        )
        await self.session.commit()
        return result.rowcount == 1

    async def complete_run(self, run_id: int, **counts: int) -> bool:
        values: dict[str, object] = {
            "status": "completed",
            "finished_at": datetime.utcnow(),
            "lease_owner": None,
            "lease_expires_at": None,
        }
        values.update(counts)
        result = cast(
            CursorResult[object],
            await self.session.execute(
                update(NewsRetrievalRun).where(NewsRetrievalRun.id == run_id).values(**values)
            ),
        )
        await self.session.commit()
        return result.rowcount == 1
