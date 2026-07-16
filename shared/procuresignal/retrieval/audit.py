"""Atomic leases, durable circuits, and sanitized retrieval outcomes."""

import re
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, and_, case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable, Select

from ..models import NewsRetrievalCircuit, NewsRetrievalRun, NewsRetrievalSourceOutcome
from .base import FetchFailureCode

LEASE_DURATION = timedelta(minutes=65)
CIRCUIT_COOLDOWN = timedelta(minutes=30)
CIRCUIT_THRESHOLD = 5
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

    async def claim_run(self, owner: str, now: datetime) -> NewsRetrievalRun | None:
        postgres = self.session.bind is not None and self.session.bind.dialect.name == "postgresql"
        candidate_id = await self.session.scalar(run_candidate_statement(now, skip_locked=postgres))
        if candidate_id is None:
            return None
        result = await self._execute(
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
            .values(
                status="running",
                lease_owner=owner,
                lease_expires_at=now + LEASE_DURATION,
                attempted_count=NewsRetrievalRun.attempted_count + 1,
            )
        )
        if result.rowcount != 1:
            await self.session.rollback()
            return None
        await self.session.commit()
        return await self.session.get(NewsRetrievalRun, candidate_id)

    async def fence_run(self, run_id: int, owner: str, now: datetime) -> bool:
        result = await self._execute(
            update(NewsRetrievalRun)
            .where(
                NewsRetrievalRun.id == run_id,
                NewsRetrievalRun.status == "running",
                NewsRetrievalRun.lease_owner == owner,
                NewsRetrievalRun.lease_expires_at >= now,
            )
            .values(lease_expires_at=NewsRetrievalRun.lease_expires_at)
        )
        return result.rowcount == 1

    async def claim_source(self, run_id: int, source_id: str, owner: str, now: datetime) -> bool:
        existing = await self.session.scalar(
            select(NewsRetrievalSourceOutcome).where(
                NewsRetrievalSourceOutcome.run_id == run_id,
                NewsRetrievalSourceOutcome.source_id == source_id,
            )
        )
        if (
            existing is not None
            and existing.status == "running"
            and existing.lease_owner == owner
            and existing.lease_expires_at is not None
            and existing.lease_expires_at >= now
        ):
            renewed = await self._execute(
                update(NewsRetrievalSourceOutcome)
                .where(
                    NewsRetrievalSourceOutcome.id == existing.id,
                    NewsRetrievalSourceOutcome.status == "running",
                    NewsRetrievalSourceOutcome.lease_owner == owner,
                )
                .values(
                    lease_expires_at=now + LEASE_DURATION,
                    attempted_count=NewsRetrievalSourceOutcome.attempted_count + 1,
                )
            )
            await self.session.commit()
            return renewed.rowcount == 1
        await self.session.commit()
        result = await self._execute(
            update(NewsRetrievalSourceOutcome)
            .where(
                NewsRetrievalSourceOutcome.run_id == run_id,
                NewsRetrievalSourceOutcome.source_id == source_id,
                NewsRetrievalSourceOutcome.status == "running",
                NewsRetrievalSourceOutcome.lease_expires_at < now,
            )
            .values(
                lease_owner=owner,
                lease_expires_at=now + LEASE_DURATION,
                started_at=now,
                attempted_count=NewsRetrievalSourceOutcome.attempted_count + 1,
            )
        )
        if result.rowcount == 1:
            await self.session.commit()
            return True
        nested = await self.session.begin_nested()
        self.session.add(
            NewsRetrievalSourceOutcome(
                run_id=run_id,
                source_id=source_id,
                status="running",
                started_at=now,
                attempted_count=1,
                lease_owner=owner,
                lease_expires_at=now + LEASE_DURATION,
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

    async def complete_source(
        self,
        run_id: int,
        source_id: str,
        owner: str,
        *,
        now: datetime,
        commit: bool = True,
        **counts: int,
    ) -> bool:
        values: dict[str, object] = {
            "status": "completed",
            "finished_at": now,
            "lease_owner": None,
            "lease_expires_at": None,
        }
        values.update(counts)
        return await self._update_source(run_id, source_id, owner, now, values, commit=commit)

    async def fail_source(
        self,
        run_id: int,
        source_id: str,
        owner: str,
        failure_code: FetchFailureCode,
        detail: str | None = None,
        *,
        now: datetime,
    ) -> bool:
        if not isinstance(failure_code, FetchFailureCode):
            raise ValueError("failure_code must be a FetchFailureCode")
        safe_detail = detail if detail is not None and _SAFE_DETAIL.fullmatch(detail) else None
        return await self._update_source(
            run_id,
            source_id,
            owner,
            now,
            {
                "status": "failed",
                "failed_count": 1,
                "failure_code": failure_code.value,
                "outcome_detail": safe_detail,
                "finished_at": now,
                "lease_owner": None,
                "lease_expires_at": None,
            },
        )

    async def _update_source(
        self,
        run_id: int,
        source_id: str,
        owner: str,
        now: datetime,
        values: dict[str, object],
        *,
        commit: bool = True,
    ) -> bool:
        result = await self._execute(
            update(NewsRetrievalSourceOutcome)
            .where(
                NewsRetrievalSourceOutcome.run_id == run_id,
                NewsRetrievalSourceOutcome.source_id == source_id,
                NewsRetrievalSourceOutcome.status == "running",
                NewsRetrievalSourceOutcome.lease_owner == owner,
                NewsRetrievalSourceOutcome.lease_expires_at >= now,
            )
            .values(**values)
        )
        if commit:
            await self.session.commit()
        return result.rowcount == 1

    async def complete_run(self, run_id: int, owner: str, *, now: datetime, **counts: int) -> bool:
        values: dict[str, object] = {
            "status": "completed",
            "finished_at": now,
            "lease_owner": None,
            "lease_expires_at": None,
        }
        values.update(counts)
        result = await self._execute(
            update(NewsRetrievalRun)
            .where(
                NewsRetrievalRun.id == run_id,
                NewsRetrievalRun.status == "running",
                NewsRetrievalRun.lease_owner == owner,
                NewsRetrievalRun.lease_expires_at >= now,
            )
            .values(**values)
        )
        await self.session.commit()
        return result.rowcount == 1

    async def record_circuit_failure(self, source_id: str, now: datetime) -> None:
        circuit = await self.session.scalar(
            select(NewsRetrievalCircuit).where(NewsRetrievalCircuit.source_id == source_id)
        )
        if circuit is None:
            nested = await self.session.begin_nested()
            self.session.add(NewsRetrievalCircuit(source_id=source_id, failure_count=0))
            try:
                await self.session.flush()
                await nested.commit()
            except IntegrityError:
                await nested.rollback()
        await self._execute(
            update(NewsRetrievalCircuit)
            .where(NewsRetrievalCircuit.source_id == source_id)
            .values(
                failure_count=NewsRetrievalCircuit.failure_count + 1,
                open_until=case(
                    (
                        NewsRetrievalCircuit.failure_count + 1 >= CIRCUIT_THRESHOLD,
                        now + CIRCUIT_COOLDOWN,
                    ),
                    else_=NewsRetrievalCircuit.open_until,
                ),
                probe_owner=None,
                probe_expires_at=None,
            )
        )
        await self.session.commit()

    async def claim_circuit_probe(self, source_id: str, owner: str, now: datetime) -> bool:
        result = await self._execute(
            update(NewsRetrievalCircuit)
            .where(
                NewsRetrievalCircuit.source_id == source_id,
                NewsRetrievalCircuit.failure_count >= CIRCUIT_THRESHOLD,
                NewsRetrievalCircuit.open_until <= now,
                or_(
                    NewsRetrievalCircuit.probe_owner.is_(None),
                    NewsRetrievalCircuit.probe_expires_at < now,
                ),
            )
            .values(probe_owner=owner, probe_expires_at=now + LEASE_DURATION)
        )
        await self.session.commit()
        return result.rowcount == 1

    async def allow_circuit_request(self, source_id: str, owner: str, now: datetime) -> bool:
        circuit = await self.session.scalar(
            select(NewsRetrievalCircuit).where(NewsRetrievalCircuit.source_id == source_id)
        )
        if circuit is None or circuit.failure_count < CIRCUIT_THRESHOLD:
            await self.session.commit()
            return True
        if circuit.open_until is not None and circuit.open_until > now:
            await self.session.commit()
            return False
        if (
            circuit.probe_owner == owner
            and circuit.probe_expires_at is not None
            and circuit.probe_expires_at >= now
        ):
            await self.session.commit()
            return True
        return await self.claim_circuit_probe(source_id, owner, now)

    async def record_circuit_success(self, source_id: str, owner: str) -> bool:
        result = await self._execute(
            update(NewsRetrievalCircuit)
            .where(
                NewsRetrievalCircuit.source_id == source_id,
                or_(
                    NewsRetrievalCircuit.probe_owner == owner,
                    NewsRetrievalCircuit.failure_count < 5,
                ),
            )
            .values(failure_count=0, open_until=None, probe_owner=None, probe_expires_at=None)
        )
        await self.session.commit()
        return result.rowcount == 1

    async def circuit_state(self, source_id: str, now: datetime) -> str:
        circuit = await self.session.scalar(
            select(NewsRetrievalCircuit).where(NewsRetrievalCircuit.source_id == source_id)
        )
        await self.session.commit()
        if circuit is None or circuit.failure_count < CIRCUIT_THRESHOLD:
            return "closed"
        if circuit.open_until is not None and circuit.open_until > now:
            return "open"
        return "half_open"

    async def _execute(self, statement: Executable) -> CursorResult[object]:
        return cast(CursorResult[object], await self.session.execute(statement))
