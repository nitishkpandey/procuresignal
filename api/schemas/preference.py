"""User preference schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    else:
        items = list(value)

    normalized: list[str] = []
    for item in items:
        text = str(item).strip().lower()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


class PreferenceUpdate(BaseModel):
    """Request to update preferences."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., min_length=1, max_length=100)
    interested_categories: Optional[list[str]] = None
    interested_suppliers: Optional[list[str]] = None
    interested_regions: Optional[list[str]] = None
    interested_signals: Optional[list[str]] = None
    excluded_categories: Optional[list[str]] = None
    excluded_suppliers: Optional[list[str]] = None
    excluded_regions: Optional[list[str]] = None
    excluded_signals: Optional[list[str]] = None
    platform_language: str = Field("en", min_length=2, max_length=10)

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("platform_language", mode="before")
    @classmethod
    def normalize_platform_language(cls, value: Any) -> str:
        text = str(value or "en").strip().lower()
        return text or "en"

    @field_validator(
        "interested_categories",
        "interested_suppliers",
        "interested_regions",
        "interested_signals",
        "excluded_categories",
        "excluded_suppliers",
        "excluded_regions",
        "excluded_signals",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: Any) -> list[str]:
        return _normalize_list(value)


class PreferenceResponse(BaseModel):
    """User preferences response."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    interested_categories: list[str] = Field(default_factory=list)
    interested_suppliers: list[str] = Field(default_factory=list)
    interested_regions: list[str] = Field(default_factory=list)
    interested_signals: list[str] = Field(default_factory=list)
    excluded_categories: list[str] = Field(default_factory=list)
    excluded_suppliers: list[str] = Field(default_factory=list)
    excluded_regions: list[str] = Field(default_factory=list)
    excluded_signals: list[str] = Field(default_factory=list)
    platform_language: str = "en"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PreferenceLanguageUpdate(BaseModel):
    """Request to update only the saved platform language."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., min_length=1, max_length=100)
    platform_language: str = Field("en", min_length=2, max_length=10)

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("platform_language", mode="before")
    @classmethod
    def normalize_platform_language(cls, value: Any) -> str:
        text = str(value or "en").strip().lower()
        return text or "en"


class PreferenceBulkUpdate(BaseModel):
    """Bulk preference update request."""

    model_config = ConfigDict(from_attributes=True)

    items: list[PreferenceUpdate] = Field(default_factory=list, min_length=1)


class PreferenceBulkResponse(BaseModel):
    """Bulk preference update response."""

    model_config = ConfigDict(from_attributes=True)

    updated_count: int = Field(..., ge=0)
    preferences: list[PreferenceResponse] = Field(default_factory=list)
