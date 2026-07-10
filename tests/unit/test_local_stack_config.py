"""Tests for local Docker stack defaults."""

from pathlib import Path

import yaml

SUPPLIERMIND_RESERVED_HOST_PORTS = {"5433", "6379"}


def _defaulted_port(value: str) -> str:
    if value.startswith("${") and value.endswith("}") and ":-" in value:
        return value.rsplit(":-", maxsplit=1)[1].rstrip("}")
    return value


def _host_ports(service: dict) -> set[str]:
    ports = service.get("ports", [])
    host_ports: set[str] = set()
    for mapping in ports:
        if not isinstance(mapping, str) or ":" not in mapping:
            continue
        host_ports.add(_defaulted_port(mapping.split(":", maxsplit=1)[0].strip('"')))
    return host_ports


def test_procuresignal_compose_does_not_bind_suppliermind_ports() -> None:
    """ProcureSignal should coexist with SupplierMind's local database/cache."""

    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    services = compose["services"]
    bound_ports = {port for service in services.values() for port in _host_ports(service)}

    assert bound_ports.isdisjoint(SUPPLIERMIND_RESERVED_HOST_PORTS)
