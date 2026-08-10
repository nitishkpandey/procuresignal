"""Notification and alert-rule schemas."""

from datetime import datetime
from typing import Optional

from procuresignal.notifications.rules import SEVERITY_ORDER
from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    public_id: str
    subject: str
    body: str
    # Provenance travels with the alert. Without it a buyer cannot tell why they were
    # told, and an alert they cannot explain is one they mute.
    rule_name: Optional[str] = None
    risk_type: Optional[str] = None
    severity: Optional[str] = None
    supplier_public_ids: list[str] = Field(default_factory=list)
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    total_count: int
    unread_count: int


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    min_severity: str = Field("high", max_length=20)
    risk_types: list[str] = Field(default_factory=list)

    @property
    def severities(self) -> tuple[str, ...]:
        return SEVERITY_ORDER


class AlertRuleItem(BaseModel):
    public_id: str
    name: str
    min_severity: str
    risk_types: list[str]
    is_enabled: bool


class AlertRuleListResponse(BaseModel):
    items: list[AlertRuleItem]
    total_count: int
