"""The npm audit exception is exact, reviewable, and temporary."""

import json
from datetime import date
from pathlib import Path

import pytest

from scripts.audit_npm import unapproved_vulnerabilities, validate_policy

ROOT = Path(__file__).resolve().parents[2]


def _report() -> dict:
    return {
        "vulnerabilities": {
            "braces": {
                "severity": "high",
                "via": [
                    {
                        "url": "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm",
                    }
                ],
            },
            "micromatch": {"severity": "high", "via": ["braces"]},
            "eslint-config-next": {"severity": "high", "via": ["micromatch"]},
        }
    }


def _policy() -> dict:
    return {
        "reviewed": "2026-10-10",
        "next_review": "2026-11-10",
        "advisories": {
            "GHSA-vfj7-8cjw-p6xm": {
                "reason": "No compatible upstream fix.",
                "maximum_severity": "high",
                "packages": ["braces", "micromatch", "eslint-config-next"],
            }
        },
    }


def test_one_advisory_approves_its_transitive_audit_chain() -> None:
    approved = validate_policy(_policy(), today=date(2026, 10, 10))

    assert unapproved_vulnerabilities(_report(), allowed=approved) == []


def test_an_unknown_high_severity_advisory_still_blocks() -> None:
    report = _report()
    report["vulnerabilities"]["axios"] = {
        "severity": "critical",
        "via": [{"url": "https://github.com/advisories/GHSA-new-risk"}],
    }

    approved = validate_policy(_policy(), today=date(2026, 10, 10))

    assert unapproved_vulnerabilities(report, allowed=approved) == ["axios: GHSA-new-risk"]


def test_exception_does_not_cover_a_new_package_path() -> None:
    report = _report()
    report["vulnerabilities"]["new-build-tool"] = {
        "severity": "high",
        "via": ["braces"],
    }
    approved = validate_policy(_policy(), today=date(2026, 10, 10))

    assert unapproved_vulnerabilities(report, allowed=approved) == [
        "new-build-tool: package path not approved for GHSA-vfj7-8cjw-p6xm"
    ]


def test_exception_does_not_cover_a_severity_increase() -> None:
    report = _report()
    report["vulnerabilities"]["braces"]["severity"] = "critical"
    approved = validate_policy(_policy(), today=date(2026, 10, 10))

    assert unapproved_vulnerabilities(report, allowed=approved) == [
        "braces: critical exceeds approved high for GHSA-vfj7-8cjw-p6xm"
    ]


def test_an_expired_exception_fails_before_the_audit_is_evaluated() -> None:
    policy = {
        "reviewed": "2026-10-01",
        "next_review": "2026-10-09",
        "advisories": {"GHSA-vfj7-8cjw-j7x9": {"reason": "No upstream fix."}},
    }

    with pytest.raises(RuntimeError, match="expired"):
        validate_policy(policy, today=date(2026, 10, 10))


def test_exception_without_a_reason_is_rejected() -> None:
    policy = {
        "reviewed": "2026-10-10",
        "next_review": "2026-11-10",
        "advisories": {"GHSA-vfj7-8cjw-j7x9": {"reason": ""}},
    }

    with pytest.raises(RuntimeError, match="reason"):
        validate_policy(policy, today=date(2026, 10, 10))


def test_committed_policy_has_not_expired() -> None:
    policy = json.loads((ROOT / ".github/npm-audit-exceptions.json").read_text(encoding="utf-8"))

    assert set(validate_policy(policy, today=date.today())) == {"GHSA-vfj7-8cjw-p6xm"}
