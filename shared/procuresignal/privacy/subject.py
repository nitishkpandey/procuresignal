"""What is held about one person, gathered from the registry.

The export walks `INVENTORY` rather than a hand-written set of queries, because the
failure to guard against is omission: a table the export forgot looks exactly like a
table with nothing in it, and the person receiving the file has no way to tell the
difference. Registering a table is what puts it in the export.

Two things are deliberately shaped this way. Tables erasure will never touch are
included anyway — access and erasure are different rights, and hiding the audit entries
about someone because they cannot be deleted answers a question nobody asked. And
credential columns are replaced rather than omitted, so the file shows that something is
held without handing it over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.auth.audit import is_sensitive_key
from procuresignal.models import Base, User
from procuresignal.privacy.inventory import INVENTORY, SubjectLink

REDACTED = "[redacted]"


@dataclass
class SubjectExport:
    subject: dict[str, Any]
    generated_at: datetime
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _jsonable(value: Any) -> Any:
    """Article 20 asks for a machine-readable format.

    A datetime that will not serialise turns the deliverable into a stack trace at the
    moment somebody needs it, so conversion happens here rather than at the API edge
    where a script calling this directly would miss it.
    """

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return REDACTED
    return value


def _row_to_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    return {
        name: REDACTED if is_sensitive_key(name) else _jsonable(getattr(row, name))
        for name in columns
    }


def _subject_value(user: User, link: SubjectLink) -> Any:
    # The two shapes this codebase uses. An export that follows one and not the other
    # returns half a person's data, and the half it returns looks complete.
    return user.public_id if link is SubjectLink.USER_PUBLIC_ID else user.id


async def export_subject(session: AsyncSession, *, user: User) -> SubjectExport:
    """Everything held about one person, table by table."""

    tables: dict[str, list[dict[str, Any]]] = {}

    for entry in INVENTORY:
        if entry.link is SubjectLink.NONE or entry.link_column is None:
            continue

        table = Base.metadata.tables[entry.table]
        columns = [column.name for column in table.columns]
        rows = await session.execute(
            select(table).where(table.c[entry.link_column] == _subject_value(user, entry.link))
        )
        # Present and empty rather than missing: "we hold nothing about you here" is an
        # answer, and a shorter file is an ambiguity.
        tables[entry.table] = [_row_to_dict(row, columns) for row in rows]

    return SubjectExport(
        subject={
            "public_id": user.public_id,
            "email": user.email,
            "full_name": user.full_name,
        },
        generated_at=datetime.utcnow(),
        tables=tables,
    )
