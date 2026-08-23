"""Supplier impact endpoints.

The list is what this organization watches, most exposed first — the screen a buyer opens
on Monday morning. The detail endpoint works for any supplier in the registry, watched or
not, because checking exposure before deciding whether to watch is the obvious use and
the registry is global read-only data.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from procuresignal.scoring.impact import SupplierImpact, supplier_impact, watched_impact
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import AuthenticatedUser, get_current_user, get_session
from api.schemas.impact import ImpactDriver, ImpactListResponse, SupplierImpactResponse

router = APIRouter(prefix="/api/impact", tags=["impact"], dependencies=[Depends(get_current_user)])


def _response(impact: SupplierImpact) -> SupplierImpactResponse:
    return SupplierImpactResponse(
        supplier_public_id=impact.supplier_public_id,
        supplier_name=impact.supplier_name,
        value=impact.score.value,
        band=impact.score.band,
        drivers=[ImpactDriver.model_validate(driver) for driver in impact.score.drivers],
    )


@router.get("", response_model=ImpactListResponse)
async def list_watched_impact(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ImpactListResponse:
    """Exposure across every supplier this organization watches."""

    impacts = await watched_impact(session, organization_id=current_user.organization_id)
    return ImpactListResponse(items=[_response(impact) for impact in impacts], total=len(impacts))


@router.get("/{supplier_public_id}", response_model=SupplierImpactResponse)
async def get_supplier_impact(
    supplier_public_id: str,
    session: AsyncSession = Depends(get_session),
) -> SupplierImpactResponse:
    """One supplier's exposure, with the events that produced it."""

    impact = await supplier_impact(session, supplier_public_id=supplier_public_id)
    if impact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return _response(impact)
