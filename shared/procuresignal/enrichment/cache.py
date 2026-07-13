"""Validated async repository for versioned enrichment cache entries."""

import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Select, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.enrichment.output_parser import EnrichmentOutput
from procuresignal.models.enrichment import EnrichmentCacheEntry

logger = logging.getLogger(__name__)
_ALLOWED_ORIGINAL_METHODS = frozenset({"deterministic", "llm"})


@dataclass(frozen=True)
class CachedEnrichment:
    """A validated cached output and the method that originally produced it."""

    output: EnrichmentOutput
    original_method: str


class EnrichmentCache:
    """Read and write cache entries without owning the surrounding transaction."""

    @staticmethod
    def _query(
        *, fingerprint: str, policy_version: str, taxonomy_version: str
    ) -> Select[tuple[EnrichmentCacheEntry]]:
        return select(EnrichmentCacheEntry).where(
            EnrichmentCacheEntry.content_fingerprint == fingerprint,
            EnrichmentCacheEntry.policy_version == policy_version,
            EnrichmentCacheEntry.taxonomy_version == taxonomy_version,
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        fingerprint: str,
        policy_version: str,
        taxonomy_version: str,
    ) -> CachedEnrichment | None:
        """Return a validated compatible entry, recording a successful hit."""
        entry = await session.scalar(
            self._query(
                fingerprint=fingerprint,
                policy_version=policy_version,
                taxonomy_version=taxonomy_version,
            )
        )
        if entry is None:
            return None
        try:
            output = EnrichmentOutput.model_validate(entry.payload)
        except ValidationError:
            logger.warning("Ignoring corrupt enrichment cache payload for %s", fingerprint)
            return None

        await session.execute(
            update(EnrichmentCacheEntry)
            .where(EnrichmentCacheEntry.id == entry.id)
            .values(hit_count=EnrichmentCacheEntry.hit_count + 1)
        )
        return CachedEnrichment(output=output, original_method=entry.original_method)

    async def put(
        self,
        session: AsyncSession,
        *,
        fingerprint: str,
        policy_version: str,
        taxonomy_version: str,
        output: EnrichmentOutput,
        original_method: str,
    ) -> None:
        """Insert or update a validated entry, leaving commit to the caller."""
        if original_method not in _ALLOWED_ORIGINAL_METHODS:
            raise ValueError("original_method must be 'deterministic' or 'llm'")

        query = self._query(
            fingerprint=fingerprint,
            policy_version=policy_version,
            taxonomy_version=taxonomy_version,
        )
        payload = output.model_dump(mode="json")
        entry = await session.scalar(query)
        if entry is not None:
            entry.payload = payload
            entry.original_method = original_method
            await session.flush()
            return

        try:
            async with session.begin_nested():
                session.add(
                    EnrichmentCacheEntry(
                        content_fingerprint=fingerprint,
                        policy_version=policy_version,
                        taxonomy_version=taxonomy_version,
                        payload=payload,
                        original_method=original_method,
                    )
                )
                await session.flush()
        except IntegrityError:
            # A concurrent writer may have inserted the same versioned identity.
            entry = await session.scalar(query)
            if entry is None:
                raise
            entry.payload = payload
            entry.original_method = original_method
            await session.flush()
