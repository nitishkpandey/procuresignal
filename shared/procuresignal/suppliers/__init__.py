"""Supplier master data: normalization, resolution, and registry operations."""

from .backfill import BackfillSummary, backfill_supplier_identity
from .mentions import record_mentions
from .normalization import (
    LEGAL_FORMS,
    MINIMUM_DERIVED_ALIAS_LENGTH,
    alias_forms,
    normalize,
    strip_legal_form,
)
from .registry import (
    AmbiguousAliasError,
    DuplicateSupplierError,
    SupplierRegistryError,
    add_alias,
    merge_suppliers,
    register_supplier,
    seed_suppliers,
)
from .resolver import Resolution, resolve, resolve_many
from .screening import ScreeningHit, ScreeningResult, screen_designation

__all__ = [
    "LEGAL_FORMS",
    "MINIMUM_DERIVED_ALIAS_LENGTH",
    "normalize",
    "strip_legal_form",
    "alias_forms",
    "Resolution",
    "resolve",
    "resolve_many",
    "register_supplier",
    "add_alias",
    "merge_suppliers",
    "seed_suppliers",
    "SupplierRegistryError",
    "DuplicateSupplierError",
    "AmbiguousAliasError",
    "record_mentions",
    "screen_designation",
    "ScreeningHit",
    "ScreeningResult",
    "backfill_supplier_identity",
    "BackfillSummary",
]
