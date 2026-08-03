"""Tests for supplier master data models."""

import pytest
from procuresignal.models import ArticleSupplierMention, Supplier, SupplierAlias
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def test_two_suppliers_cannot_claim_one_alias(async_session: AsyncSession) -> None:
    """Ambiguity must fail loudly at registration, not resolve to an arbitrary winner."""
    first = Supplier(public_id="s1", canonical_name="Apple Inc", normalized_name="apple inc")
    second = Supplier(public_id="s2", canonical_name="Apple Bank", normalized_name="apple bank")
    async_session.add_all([first, second])
    await async_session.flush()

    async_session.add(
        SupplierAlias(
            supplier_id=first.id, alias="Apple", normalized_alias="apple", source="derived"
        )
    )
    await async_session.flush()

    async_session.add(
        SupplierAlias(
            supplier_id=second.id, alias="Apple", normalized_alias="apple", source="derived"
        )
    )
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_entities_differing_only_by_legal_form_stay_distinct(
    async_session: AsyncSession,
) -> None:
    """Siemens AG and Siemens Energy AG carry different risk and must not merge."""
    async_session.add_all(
        [
            Supplier(public_id="s1", canonical_name="Siemens AG", normalized_name="siemens ag"),
            Supplier(
                public_id="s2",
                canonical_name="Siemens Energy AG",
                normalized_name="siemens energy ag",
            ),
        ]
    )
    await async_session.flush()

    rows = (await async_session.execute(select(Supplier))).scalars().all()
    assert len(rows) == 2


async def test_normalized_name_is_unique(async_session: AsyncSession) -> None:
    async_session.add(
        Supplier(public_id="s1", canonical_name="Siemens AG", normalized_name="siemens ag")
    )
    await async_session.flush()

    async_session.add(
        Supplier(public_id="s2", canonical_name="SIEMENS AG", normalized_name="siemens ag")
    )
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_lei_is_unique_when_present(async_session: AsyncSession) -> None:
    async_session.add(
        Supplier(
            public_id="s1",
            canonical_name="Siemens AG",
            normalized_name="siemens ag",
            lei="W38RGI023J3WT1HWRP38",
        )
    )
    await async_session.flush()

    async_session.add(
        Supplier(
            public_id="s2",
            canonical_name="Other AG",
            normalized_name="other ag",
            lei="W38RGI023J3WT1HWRP38",
        )
    )
    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_several_suppliers_may_have_no_lei(async_session: AsyncSession) -> None:
    """Most suppliers will never have one, so null must not collide."""
    async_session.add_all(
        [
            Supplier(public_id="s1", canonical_name="A Ltd", normalized_name="a ltd", lei=None),
            Supplier(public_id="s2", canonical_name="B Ltd", normalized_name="b ltd", lei=None),
        ]
    )
    await async_session.flush()

    assert len((await async_session.execute(select(Supplier))).scalars().all()) == 2


async def test_supplier_defaults_to_active(async_session: AsyncSession) -> None:
    supplier = Supplier(public_id="s1", canonical_name="A Ltd", normalized_name="a ltd")
    async_session.add(supplier)
    await async_session.flush()

    assert supplier.is_active is True


async def test_unresolved_mentions_are_recorded_rather_than_dropped(
    async_session: AsyncSession,
) -> None:
    """An unresolved name is the evidence that tells an operator which alias is missing."""
    mention = ArticleSupplierMention(
        processed_article_id=1,
        supplier_id=None,
        surface_form="Unbekannte Lieferant GmbH",
        confidence=0.0,
    )
    async_session.add(mention)
    await async_session.flush()

    assert mention.supplier_id is None
    assert mention.surface_form == "Unbekannte Lieferant GmbH"


async def test_one_mention_per_article_and_surface_form(async_session: AsyncSession) -> None:
    """Re-running enrichment must not accumulate duplicate rows."""
    for _ in range(2):
        async_session.add(
            ArticleSupplierMention(
                processed_article_id=7, supplier_id=None, surface_form="Acme Ltd", confidence=0.0
            )
        )

    with pytest.raises(IntegrityError):
        await async_session.flush()


async def test_the_same_name_may_appear_in_different_articles(
    async_session: AsyncSession,
) -> None:
    async_session.add_all(
        [
            ArticleSupplierMention(
                processed_article_id=1, supplier_id=None, surface_form="Acme Ltd", confidence=0.0
            ),
            ArticleSupplierMention(
                processed_article_id=2, supplier_id=None, surface_form="Acme Ltd", confidence=0.0
            ),
        ]
    )
    await async_session.flush()

    rows = (await async_session.execute(select(ArticleSupplierMention))).scalars().all()
    assert len(rows) == 2


async def test_preferences_carry_resolved_supplier_ids(async_session: AsyncSession) -> None:
    """Resolved ids sit beside the text the user typed, they do not replace it."""
    from procuresignal.models import UserNewsPreference

    preference = UserNewsPreference(
        user_id="u1",
        preferred_categories=[],
        preferred_suppliers=["Siemens"],
        preferred_regions=[],
        preferred_signals=[],
        excluded_categories=[],
        excluded_suppliers=[],
        excluded_regions=[],
        excluded_signals=[],
        excluded_topics=[],
        preferred_supplier_ids=["supplier-public-id"],
    )
    async_session.add(preference)
    await async_session.flush()

    assert preference.preferred_suppliers == ["Siemens"]
    assert preference.preferred_supplier_ids == ["supplier-public-id"]
    assert preference.excluded_supplier_ids == []
