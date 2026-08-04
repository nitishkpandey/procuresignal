"""Screen sanctions designations against the supplier registry.

A designation names one entity in several ways: a primary registry spelling plus the
aliases the issuing authority recorded. Comparing only the primary name is how a
screening control reports a false negative, which in the EU is a compliance failure
rather than a poor feed. Every name is resolved.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .resolver import resolve_many


@dataclass(frozen=True)
class ScreeningHit:
    """A registered supplier named by a designation."""

    supplier_id: int
    public_id: str
    matched_name: str


@dataclass(frozen=True)
class ScreeningResult:
    """What screening one designation found, and what it could not place."""

    hits: list[ScreeningHit] = field(default_factory=list)
    # Names that resolved to nothing. Reported rather than discarded: screening that
    # silently finds nothing looks exactly like screening that works.
    unmatched_names: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return bool(self.hits)


async def screen_designation(
    session: AsyncSession,
    *,
    primary_name: str,
    aliases: Optional[Iterable[str]] = None,
) -> ScreeningResult:
    """Resolve every name a designation carries against the registry."""

    names = [name for name in [primary_name, *(aliases or [])] if (name or "").strip()]
    if not names:
        return ScreeningResult()

    resolutions = await resolve_many(session, names)

    hits: list[ScreeningHit] = []
    unmatched: list[str] = []
    seen_suppliers: set[int] = set()

    for resolution in resolutions:
        if resolution.supplier_id is None or resolution.public_id is None:
            unmatched.append(resolution.surface_form)
            continue
        # One supplier is reported once however many of its spellings the designation
        # happens to list.
        if resolution.supplier_id in seen_suppliers:
            continue
        seen_suppliers.add(resolution.supplier_id)
        hits.append(
            ScreeningHit(
                supplier_id=resolution.supplier_id,
                public_id=resolution.public_id,
                matched_name=resolution.surface_form,
            )
        )

    return ScreeningResult(hits=hits, unmatched_names=unmatched)
