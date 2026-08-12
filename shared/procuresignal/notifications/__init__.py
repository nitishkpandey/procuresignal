"""Alerting: rules, and later the outbox and its transports."""

from .digest import Digest, DigestItem, DigestSection, build_digest, render_text
from .rules import (
    SEVERITY_ORDER,
    AlertRuleError,
    DuplicateAlertRuleError,
    RuleMatch,
    create_alert_rule,
    evaluate_rules,
    meets_severity,
)

__all__ = [
    "SEVERITY_ORDER",
    "RuleMatch",
    "evaluate_rules",
    "meets_severity",
    "create_alert_rule",
    "AlertRuleError",
    "DuplicateAlertRuleError",
    "Digest",
    "DigestItem",
    "DigestSection",
    "build_digest",
    "render_text",
]
