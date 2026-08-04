"""Supplier registry request/response schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    canonical_name: str = Field(..., min_length=1, max_length=300)
    country: Optional[str] = Field(None, min_length=2, max_length=2)
    lei: Optional[str] = Field(None, min_length=20, max_length=20)


class AliasCreate(BaseModel):
    alias: str = Field(..., min_length=1, max_length=300)


class MergeRequest(BaseModel):
    merge_public_id: str = Field(..., min_length=1, max_length=64)


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    canonical_name: str
    country: Optional[str] = None
    lei: Optional[str] = None
    is_active: bool


class SupplierListResponse(BaseModel):
    items: list[SupplierResponse]
    total_count: int


class AliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alias: str
    normalized_alias: str
    source: str


class UnresolvedName(BaseModel):
    """A supplier name the registry could not place, and how often it appeared."""

    surface_form: str
    mention_count: int


class UnresolvedListResponse(BaseModel):
    items: list[UnresolvedName]
    total_count: int
