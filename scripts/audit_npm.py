"""Block npm vulnerabilities except exact, unexpired development-tool exceptions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE_DIR = ROOT / "frontend"
DEFAULT_POLICY = ROOT / ".github" / "npm-audit-exceptions.json"
BLOCKING_SEVERITIES = {"high", "critical"}
SEVERITY_RANK = {"high": 1, "critical": 2}


@dataclass(frozen=True)
class AuditException:
    maximum_severity: str
    packages: frozenset[str]


def validate_policy(policy: Mapping[str, Any], *, today: date) -> dict[str, AuditException]:
    """Return narrowly scoped exceptions after validating review metadata."""

    try:
        reviewed = date.fromisoformat(str(policy["reviewed"]))
        next_review = date.fromisoformat(str(policy["next_review"]))
        advisories = policy["advisories"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("npm audit policy has invalid review metadata") from exc

    if reviewed > today:
        raise RuntimeError("npm audit policy review date is in the future")
    if next_review < today:
        raise RuntimeError(f"npm audit policy expired on {next_review.isoformat()}")
    if not isinstance(advisories, Mapping) or not advisories:
        raise RuntimeError("npm audit policy must name at least one advisory")

    approved: dict[str, AuditException] = {}
    for advisory_id, decision in advisories.items():
        if not isinstance(advisory_id, str) or not advisory_id.startswith("GHSA-"):
            raise RuntimeError("npm audit policy contains an invalid advisory ID")
        if not isinstance(decision, Mapping) or not str(decision.get("reason", "")).strip():
            raise RuntimeError(f"npm audit exception {advisory_id} needs a reason")
        maximum_severity = str(decision.get("maximum_severity", ""))
        if maximum_severity not in BLOCKING_SEVERITIES:
            raise RuntimeError(f"npm audit exception {advisory_id} needs a valid maximum severity")
        packages = decision.get("packages")
        if (
            not isinstance(packages, list)
            or not packages
            or not all(isinstance(package, str) and package for package in packages)
        ):
            raise RuntimeError(f"npm audit exception {advisory_id} needs an exact package list")
        approved[advisory_id] = AuditException(
            maximum_severity=maximum_severity,
            packages=frozenset(packages),
        )
    return approved


def _advisory_ids(
    package: str,
    vulnerabilities: Mapping[str, Any],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    if package in seen:
        return set()
    details = vulnerabilities.get(package, {})
    if not isinstance(details, Mapping):
        return set()

    found: set[str] = set()
    for source in details.get("via", []):
        if isinstance(source, str):
            found.update(_advisory_ids(source, vulnerabilities, seen | {package}))
            continue
        if isinstance(source, Mapping):
            url = str(source.get("url", ""))
            advisory_id = url.rstrip("/").rsplit("/", 1)[-1]
            if advisory_id.startswith("GHSA-"):
                found.add(advisory_id)
    return found


def unapproved_vulnerabilities(
    report: Mapping[str, Any], *, allowed: Mapping[str, AuditException]
) -> list[str]:
    """Return blocking package/advisory pairs not covered by the exact policy."""

    vulnerabilities = report.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, Mapping):
        raise RuntimeError("npm audit returned no vulnerability map")

    failures: list[str] = []
    for package, details in sorted(vulnerabilities.items()):
        if not isinstance(details, Mapping):
            failures.append(f"{package}: malformed audit entry")
            continue
        if details.get("severity") not in BLOCKING_SEVERITIES:
            continue
        advisory_ids = _advisory_ids(str(package), vulnerabilities)
        if not advisory_ids:
            failures.append(f"{package}: unresolved advisory chain")
            continue
        for advisory_id in sorted(advisory_ids):
            decision = allowed.get(advisory_id)
            if decision is None:
                failures.append(f"{package}: {advisory_id}")
                continue
            if package not in decision.packages:
                failures.append(f"{package}: package path not approved for {advisory_id}")
                continue
            severity = str(details["severity"])
            if SEVERITY_RANK[severity] > SEVERITY_RANK[decision.maximum_severity]:
                failures.append(
                    f"{package}: {severity} exceeds approved "
                    f"{decision.maximum_severity} for {advisory_id}"
                )
    return failures


def _run_audit(package_dir: Path, *, production_only: bool) -> Mapping[str, Any]:
    command = ["npm", "audit", "--json"]
    if production_only:
        command.append("--omit=dev")
    result = subprocess.run(
        command,
        cwd=package_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "npm audit could not run")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("npm audit did not return JSON") from exc
    if not isinstance(report, Mapping):
        raise RuntimeError("npm audit returned an invalid report")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    allowed = validate_policy(policy, today=date.today())

    production_failures = unapproved_vulnerabilities(
        _run_audit(args.package_dir, production_only=True), allowed={}
    )
    full_failures = unapproved_vulnerabilities(
        _run_audit(args.package_dir, production_only=False), allowed=allowed
    )
    failures = sorted(set(production_failures + full_failures))
    if failures:
        for failure in failures:
            print(f"unapproved npm vulnerability: {failure}", file=sys.stderr)
        return 1

    print(
        "npm audit passed: production clean; "
        f"{len(allowed)} exact development advisory exception(s) active"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
