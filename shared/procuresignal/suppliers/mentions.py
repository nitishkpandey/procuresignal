"""Record which suppliers an article names."""

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import ArticleSupplierMention

from .normalization import normalize
from .resolver import Resolution, resolve_many


def _distinct_surface_forms(surface_forms: Iterable[Optional[str]]) -> list[str]:
    """Drop blanks and keep one spelling per distinct name, in the order given.

    Deduplicated on the normalized form, so "Siemens AG" and "siemens ag" in one
    article produce a single mention rather than two rows pointing at the same
    supplier.
    """

    seen: set[str] = set()
    cleaned: list[str] = []

    for form in surface_forms:
        text = (form or "").strip()
        key = normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

    return cleaned


async def record_mentions(
    session: AsyncSession,
    *,
    processed_article_id: int,
    surface_forms: Iterable[Optional[str]],
) -> list[Resolution]:
    """Resolve the names an article used and store them against it.

    Idempotent: enrichment can run over an article more than once, and names already
    recorded are left alone rather than inserted again or treated as an error.

    Unresolved names are stored too. They are what tells an operator which alias is
    missing, and dropping them would make registry coverage unmeasurable.
    """

    cleaned = _distinct_surface_forms(surface_forms)
    if not cleaned:
        return []

    resolutions = await resolve_many(session, cleaned)

    already_recorded = set(
        (
            await session.execute(
                select(ArticleSupplierMention.surface_form).where(
                    ArticleSupplierMention.processed_article_id == processed_article_id
                )
            )
        )
        .scalars()
        .all()
    )

    for resolution in resolutions:
        if resolution.surface_form in already_recorded:
            continue
        session.add(
            ArticleSupplierMention(
                processed_article_id=processed_article_id,
                supplier_id=resolution.supplier_id,
                surface_form=resolution.surface_form,
                confidence=resolution.confidence,
            )
        )

    return resolutions
