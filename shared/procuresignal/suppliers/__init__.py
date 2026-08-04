"""Supplier master data: normalization, resolution, and registry operations."""

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
]
