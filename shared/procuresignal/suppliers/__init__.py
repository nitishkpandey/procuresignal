"""Supplier master data: normalization, resolution, and registry operations."""

from .normalization import (
    LEGAL_FORMS,
    MINIMUM_DERIVED_ALIAS_LENGTH,
    alias_forms,
    normalize,
    strip_legal_form,
)

__all__ = [
    "LEGAL_FORMS",
    "MINIMUM_DERIVED_ALIAS_LENGTH",
    "normalize",
    "strip_legal_form",
    "alias_forms",
]
