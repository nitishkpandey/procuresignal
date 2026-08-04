"""Create, alias, merge, and seed suppliers."""

from typing import Optional
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from procuresignal.models import ArticleSupplierMention, Supplier, SupplierAlias

from .normalization import alias_forms, normalize


class SupplierRegistryError(Exception):
    """Base class for registry rejections."""


class DuplicateSupplierError(SupplierRegistryError):
    """A supplier with this canonical name already exists."""


class AmbiguousAliasError(SupplierRegistryError):
    """Another supplier already answers to this name."""


async def _alias_holder(session: AsyncSession, normalized_alias: str) -> Optional[Supplier]:
    return (
        await session.execute(
            select(Supplier)
            .join(SupplierAlias, SupplierAlias.supplier_id == Supplier.id)
            .where(SupplierAlias.normalized_alias == normalized_alias)
        )
    ).scalar_one_or_none()


async def _claim_alias(
    session: AsyncSession, *, supplier: Supplier, alias: str, source: str
) -> Optional[SupplierAlias]:
    """Attach one alias, or return None if this supplier already holds it.

    The conflict is checked before inserting rather than caught afterwards. A unique
    violation raised at flush would poison the whole session, and the error it produces
    names a constraint rather than the supplier an operator needs to look at.
    """

    normalized_alias = normalize(alias)
    if not normalized_alias:
        return None

    holder = await _alias_holder(session, normalized_alias)
    if holder is not None:
        if holder.id == supplier.id:
            return None
        raise AmbiguousAliasError(
            f"'{alias}' already resolves to {holder.canonical_name} "
            f"({holder.public_id}); merge the two suppliers or choose another alias"
        )

    record = SupplierAlias(
        supplier_id=supplier.id, alias=alias, normalized_alias=normalized_alias, source=source
    )
    session.add(record)
    await session.flush()
    return record


async def register_supplier(
    session: AsyncSession,
    *,
    canonical_name: str,
    country: str | None = None,
    lei: str | None = None,
) -> Supplier:
    """Create a supplier and the aliases derived from its name."""

    normalized_name = normalize(canonical_name)
    if not normalized_name:
        raise SupplierRegistryError("a supplier needs a name")

    existing = (
        await session.execute(select(Supplier).where(Supplier.normalized_name == normalized_name))
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateSupplierError(
            f"{existing.canonical_name} ({existing.public_id}) is already registered"
        )

    # Every derived alias is checked before anything is written, so a conflict leaves
    # no half-registered supplier behind.
    for form in alias_forms(canonical_name):
        holder = await _alias_holder(session, form)
        if holder is not None:
            raise AmbiguousAliasError(
                f"'{form}' already resolves to {holder.canonical_name} "
                f"({holder.public_id}); merge the two suppliers or choose another name"
            )

    supplier = Supplier(
        public_id=uuid4().hex,
        canonical_name=canonical_name.strip(),
        normalized_name=normalized_name,
        country=country,
        lei=lei,
    )
    session.add(supplier)
    await session.flush()

    for index, form in enumerate(alias_forms(canonical_name)):
        session.add(
            SupplierAlias(
                supplier_id=supplier.id,
                alias=canonical_name.strip() if index == 0 else form,
                normalized_alias=form,
                source="canonical" if index == 0 else "derived",
            )
        )
    await session.flush()

    return supplier


async def add_alias(
    session: AsyncSession, *, supplier_id: int, alias: str, source: str = "manual"
) -> Optional[SupplierAlias]:
    """Teach the registry another name for a supplier.

    Returns None when the supplier already holds it, so repeating yourself is harmless.
    """

    supplier = await session.get(Supplier, supplier_id)
    if supplier is None:
        raise SupplierRegistryError(f"no supplier with id {supplier_id}")

    return await _claim_alias(session, supplier=supplier, alias=alias, source=source)


async def merge_suppliers(session: AsyncSession, *, keep_id: int, merge_id: int) -> None:
    """Fold one supplier into another.

    The loser is deactivated rather than deleted, so the record of what was merged
    survives, and its aliases and article mentions move to the survivor.
    """

    if keep_id == merge_id:
        raise ValueError("a supplier cannot be merged into itself")

    keep = await session.get(Supplier, keep_id)
    merge = await session.get(Supplier, merge_id)
    if keep is None or merge is None:
        raise SupplierRegistryError("both suppliers must exist to merge them")

    await session.execute(
        update(SupplierAlias)
        .where(SupplierAlias.supplier_id == merge_id)
        .values(supplier_id=keep_id)
    )
    await session.execute(
        update(ArticleSupplierMention)
        .where(ArticleSupplierMention.supplier_id == merge_id)
        .values(supplier_id=keep_id)
    )

    merge.is_active = False
    await session.flush()


async def seed_suppliers(session: AsyncSession) -> int:
    """Register the starting catalogue. Returns how many were created.

    Idempotent, because it runs on every deployment. Names already present are skipped
    rather than treated as an error.
    """

    from procuresignal.enrichment.entities import KNOWN_SUPPLIERS

    created = 0
    for name in sorted(KNOWN_SUPPLIERS):
        try:
            await register_supplier(session, canonical_name=name)
        except (DuplicateSupplierError, AmbiguousAliasError):
            continue
        created += 1

    return created
