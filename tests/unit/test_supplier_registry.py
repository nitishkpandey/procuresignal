"""Tests for supplier registry operations."""

import pytest
from procuresignal.models import ArticleSupplierMention, Supplier, SupplierAlias
from procuresignal.suppliers.registry import (
    AmbiguousAliasError,
    DuplicateSupplierError,
    add_alias,
    merge_suppliers,
    register_supplier,
    seed_suppliers,
)
from procuresignal.suppliers.resolver import resolve
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def test_registering_creates_canonical_and_stripped_aliases(
    async_session: AsyncSession,
) -> None:
    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.flush()

    assert (await resolve(async_session, "Siemens AG")).supplier_id == supplier.id
    assert (await resolve(async_session, "Siemens")).supplier_id == supplier.id


async def test_registering_records_country_and_lei(async_session: AsyncSession) -> None:
    supplier = await register_supplier(
        async_session, canonical_name="Siemens AG", country="DE", lei="W38RGI023J3WT1HWRP38"
    )
    await async_session.flush()

    assert supplier.country == "DE"
    assert supplier.lei == "W38RGI023J3WT1HWRP38"
    assert supplier.public_id


async def test_registering_the_same_name_twice_is_refused(async_session: AsyncSession) -> None:
    await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.flush()

    with pytest.raises(DuplicateSupplierError):
        await register_supplier(async_session, canonical_name="  siemens   ag  ")


async def test_registering_a_name_whose_alias_is_taken_is_refused(
    async_session: AsyncSession,
) -> None:
    """ "Siemens Aktiengesellschaft" is a different string but the same company."""
    first = await register_supplier(async_session, canonical_name="Siemens AG")
    await add_alias(async_session, supplier_id=first.id, alias="Siemens Aktiengesellschaft")
    await async_session.flush()

    with pytest.raises(AmbiguousAliasError):
        await register_supplier(async_session, canonical_name="Siemens Aktiengesellschaft")


async def test_conflicting_alias_names_the_existing_holder(async_session: AsyncSession) -> None:
    """An operator needs to know which supplier already owns the alias."""
    first = await register_supplier(async_session, canonical_name="Apple Inc")
    second = await register_supplier(async_session, canonical_name="Apple Bank")
    await async_session.flush()

    with pytest.raises(AmbiguousAliasError) as exc:
        await add_alias(async_session, supplier_id=second.id, alias="Apple")

    assert first.public_id in str(exc.value)
    assert "Apple Inc" in str(exc.value)


async def test_re_adding_a_supplier_own_alias_is_harmless(async_session: AsyncSession) -> None:
    """Seeding twice, or an operator repeating themselves, must not blow up."""
    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.flush()

    await add_alias(async_session, supplier_id=supplier.id, alias="Siemens")
    await async_session.flush()

    aliases = (
        (
            await async_session.execute(
                select(SupplierAlias).where(SupplierAlias.normalized_alias == "siemens")
            )
        )
        .scalars()
        .all()
    )
    assert len(aliases) == 1


async def test_short_aliases_are_allowed_when_a_person_asks(
    async_session: AsyncSession,
) -> None:
    """Derivation refuses to guess a two-character alias; a deliberate one is fine."""
    supplier = await register_supplier(async_session, canonical_name="3M Co")
    await async_session.flush()

    await add_alias(async_session, supplier_id=supplier.id, alias="3M")
    await async_session.flush()

    assert (await resolve(async_session, "3M")).supplier_id == supplier.id


async def test_merging_moves_aliases_to_the_survivor(async_session: AsyncSession) -> None:
    keep = await register_supplier(async_session, canonical_name="Siemens AG")
    duplicate = await register_supplier(async_session, canonical_name="Siemens Aktiengesellschaft")
    await async_session.flush()

    await merge_suppliers(async_session, keep_id=keep.id, merge_id=duplicate.id)
    await async_session.flush()

    assert (await resolve(async_session, "Siemens Aktiengesellschaft")).supplier_id == keep.id
    assert (await resolve(async_session, "Siemens AG")).supplier_id == keep.id


async def test_merging_keeps_the_loser_for_audit(async_session: AsyncSession) -> None:
    """Deactivated rather than deleted, so what was merged stays visible."""
    keep = await register_supplier(async_session, canonical_name="Siemens AG")
    duplicate = await register_supplier(async_session, canonical_name="Siemens Aktiengesellschaft")
    await async_session.flush()

    await merge_suppliers(async_session, keep_id=keep.id, merge_id=duplicate.id)
    await async_session.flush()

    assert duplicate.is_active is False
    assert (await async_session.get(Supplier, duplicate.id)) is not None


async def test_merging_repoints_existing_article_mentions(
    async_session: AsyncSession,
) -> None:
    keep = await register_supplier(async_session, canonical_name="Siemens AG")
    duplicate = await register_supplier(async_session, canonical_name="Siemens Aktiengesellschaft")
    await async_session.flush()

    async_session.add(
        ArticleSupplierMention(
            processed_article_id=1,
            supplier_id=duplicate.id,
            surface_form="Siemens Aktiengesellschaft",
            confidence=1.0,
        )
    )
    await async_session.flush()

    await merge_suppliers(async_session, keep_id=keep.id, merge_id=duplicate.id)
    await async_session.flush()

    mention = (await async_session.execute(select(ArticleSupplierMention))).scalars().one()
    assert mention.supplier_id == keep.id


async def test_merging_a_supplier_into_itself_is_refused(async_session: AsyncSession) -> None:
    supplier = await register_supplier(async_session, canonical_name="Siemens AG")
    await async_session.flush()

    with pytest.raises(ValueError):
        await merge_suppliers(async_session, keep_id=supplier.id, merge_id=supplier.id)


async def test_seeding_registers_the_starting_catalogue(async_session: AsyncSession) -> None:
    created = await seed_suppliers(async_session)
    await async_session.flush()

    assert created > 0
    assert (await resolve(async_session, "Bosch")).supplier_id is not None
    assert (await resolve(async_session, "Siemens")).supplier_id is not None


async def test_seeding_twice_adds_nothing(async_session: AsyncSession) -> None:
    """It runs on every deployment, so it has to be idempotent."""
    first = await seed_suppliers(async_session)
    await async_session.flush()
    second = await seed_suppliers(async_session)
    await async_session.flush()

    assert first > 0
    assert second == 0

    suppliers = (await async_session.execute(select(Supplier))).scalars().all()
    assert len(suppliers) == first
