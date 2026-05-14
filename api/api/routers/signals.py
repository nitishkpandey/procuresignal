from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from shared.procuresignal.config import database
from shared.procuresignal.models import Signal as SignalModel
from shared.procuresignal.models import SignalMetadata

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _serialize_signal(obj: SignalModel) -> dict:
    return {
        "id": str(obj.id),
        "signal_type": obj.signal_type,
        "entity_id": str(obj.entity_id) if obj.entity_id else None,
        "article_id": str(obj.article_id) if obj.article_id else None,
        "confidence": obj.confidence,
        "severity": obj.severity,
        "impact_areas": obj.impact_areas,
        "raw_signal": obj.raw_signal,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
    }


@router.get("/")
async def list_signals(
    signal_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50),
):
    if not database.db_config:
        return {"items": [], "skip": skip, "limit": limit}

    async with database.db_config.session_maker() as session:
        stmt = select(SignalModel)
        if signal_type:
            stmt = stmt.where(SignalModel.signal_type == signal_type)
        if entity_id:
            stmt = stmt.where(SignalModel.entity_id == entity_id)
        if severity:
            stmt = stmt.where(SignalModel.severity == severity)

        stmt = stmt.offset(skip).limit(limit)

        result = await session.execute(stmt)
        items = result.scalars().all()

        return {"items": [_serialize_signal(i) for i in items], "skip": skip, "limit": limit}


@router.get("/{signal_id}")
async def get_signal(signal_id: str):
    if not database.db_config:
        raise HTTPException(status_code=404, detail="DB not configured")

    async with database.db_config.session_maker() as session:
        stmt = select(SignalModel).where(SignalModel.id == signal_id)
        result = await session.execute(stmt)
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail="signal not found")
        return _serialize_signal(obj)


@router.get("/entity/{entity_id}/signals")
async def get_entity_signals(entity_id: str):
    if not database.db_config:
        return {"entity_id": entity_id, "signals": []}

    async with database.db_config.session_maker() as session:
        stmt = select(SignalModel).where(SignalModel.entity_id == entity_id)
        result = await session.execute(stmt)
        items = result.scalars().all()
        return {"entity_id": entity_id, "signals": [_serialize_signal(i) for i in items]}


@router.post("/{signal_id}/acknowledge")
async def acknowledge_signal(signal_id: str):
    if not database.db_config:
        raise HTTPException(status_code=500, detail="DB not configured")

    async with database.db_config.session_maker() as session:
        meta = SignalMetadata(signal_id=signal_id, key="acknowledged", value="true")
        session.add(meta)
        await session.commit()
        return {"id": signal_id, "acknowledged": True}


@router.get("/stats/summary")
async def get_signal_stats():
    if not database.db_config:
        return {"total": 0, "by_type": {}, "by_severity": {}}

    async with database.db_config.session_maker() as session:
        total = await session.scalar(select(func.count()).select_from(SignalModel))

        by_type_stmt = select(SignalModel.signal_type, func.count()).group_by(
            SignalModel.signal_type
        )
        by_sev_stmt = select(SignalModel.severity, func.count()).group_by(SignalModel.severity)

        by_type_res = await session.execute(by_type_stmt)
        by_sev_res = await session.execute(by_sev_stmt)

        by_type = {row[0]: row[1] for row in by_type_res.all()}
        by_severity = {row[0]: row[1] for row in by_sev_res.all()}

        return {"total": int(total or 0), "by_type": by_type, "by_severity": by_severity}
