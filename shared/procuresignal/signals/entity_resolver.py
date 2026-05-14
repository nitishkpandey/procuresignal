from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, List, Optional


@dataclass
class ResolvedEntity:
    entity_id: str
    entity_name: str
    match_confidence: float
    entity_type: str  # company, person, location, etc.


class EntityResolver:
    """Resolves entity names to database records.

    This implementation is a thin wrapper that expects a DB session
    with a `companies` table or similar. If `db_session` is None the
    resolver will be a no-op and return None.
    """

    def __init__(self, db_session: Optional[Any] = None) -> None:
        self.db = db_session

    def resolve_company(
        self, company_name: str, context: Optional[str] = None
    ) -> Optional[ResolvedEntity]:
        if not company_name:
            return None

        # Exact match
        exact = self._exact_match(company_name)
        if exact:
            return exact

        # Fuzzy match
        candidates = self._fuzzy_match(company_name, threshold=0.75)
        if candidates:
            return candidates[0]

        return None

    def _exact_match(self, name: str) -> Optional[ResolvedEntity]:
        # If a DB is available, query for exact match. Otherwise return None.
        if not self.db:
            return None

        # Example pseudo-query (implementation depends on ORM):
        # row = self.db.query(Company).filter(func.lower(Company.name) == name.lower()).first()
        # if row:
        #     return ResolvedEntity(entity_id=row.id, entity_name=row.name, match_confidence=1.0, entity_type='company')
        return None

    def _fuzzy_match(self, name: str, threshold: float = 0.75) -> List[ResolvedEntity]:
        if not self.db:
            return []

        # If DB access is provided, fetch candidate company names and score them.
        # This is a placeholder implementation using difflib for similarity.
        # rows = self.db.query(Company).all()
        rows: List[Any] = []

        scored = []
        for r in rows:
            score = SequenceMatcher(None, name.lower(), r.name.lower()).ratio()
            if score >= threshold:
                scored.append(
                    ResolvedEntity(
                        entity_id=r.id,
                        entity_name=r.name,
                        match_confidence=score,
                        entity_type="company",
                    )
                )

        scored.sort(key=lambda x: x.match_confidence, reverse=True)
        return scored
