"""Turn the name an article used into a canonical supplier."""

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import Supplier, SupplierAlias

from .normalization import normalize

# Exact alias match is the only way to resolve, so there is nothing to be uncertain
# about. The field exists so that a future source with genuine uncertainty — an LEI
# import, say — has somewhere to record it without a schema change.
EXACT_MATCH_CONFIDENCE = 1.0


@dataclass(frozen=True)
class Resolution:
    """What one supplier name in the wild turned out to be."""

    surface_form: str
    supplier_id: Optional[int]
    public_id: Optional[str]
    confidence: float

    @property
    def resolved(self) -> bool:
        return self.supplier_id is not None


def _unresolved(surface_form: str) -> Resolution:
    return Resolution(surface_form=surface_form, supplier_id=None, public_id=None, confidence=0.0)


async def resolve_many(session: AsyncSession, surface_forms: Iterable[str]) -> list[Resolution]:
    """Resolve a batch of names, preserving input order.

    One query for the whole batch. Enrichment resolves every name an article mentions,
    and a round trip per name turns one article into a dozen queries.
    """

    forms = list(surface_forms)
    if not forms:
        return []

    normalized = {normalize(form) for form in forms}
    normalized.discard("")
    if not normalized:
        return [_unresolved(form) for form in forms]

    rows = (
        await session.execute(
            select(SupplierAlias.normalized_alias, Supplier.id, Supplier.public_id)
            .join(Supplier, Supplier.id == SupplierAlias.supplier_id)
            .where(SupplierAlias.normalized_alias.in_(normalized))
            # A supplier merged away must stop answering for its old names.
            .where(Supplier.is_active.is_(True))
        )
    ).all()
    by_alias = {alias: (supplier_id, public_id) for alias, supplier_id, public_id in rows}

    resolutions: list[Resolution] = []
    for form in forms:
        found = by_alias.get(normalize(form))
        if found is None:
            resolutions.append(_unresolved(form))
        else:
            supplier_id, public_id = found
            resolutions.append(
                Resolution(
                    surface_form=form,
                    supplier_id=supplier_id,
                    public_id=public_id,
                    confidence=EXACT_MATCH_CONFIDENCE,
                )
            )
    return resolutions


async def resolve(session: AsyncSession, surface_form: str) -> Resolution:
    """Resolve one name."""

    return (await resolve_many(session, [surface_form]))[0]
