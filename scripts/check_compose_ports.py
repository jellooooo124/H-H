#!/usr/bin/env python3
"""Fail closed when the resolved Docker Compose config exposes demo services."""
from __future__ import annotations

import json
import sys

EXPECTED = {"frontend": 80, "api": 8000, "n8n": 5678}


def validate_ports(config: dict) -> list[str]:
    """Return actionable errors without logging environment variables or secrets."""
    errors: list[str] = []
    services = config.get("services")
    if not isinstance(services, dict):
        return ["resolved Compose config is missing services"]

    for name, target in EXPECTED.items():
        service = services.get(name)
        if not isinstance(service, dict):
            errors.append(f"required service {name} is missing")
            continue
        ports = service.get("ports", [])
        if not isinstance(ports, list) or len(ports) != 1:
            errors.append(f"{name} must publish exactly one loopback-only port")
            continue
        port = ports[0]
        if (
            not isinstance(port, dict)
            or str(port.get("host_ip", "")) != "127.0.0.1"
            or str(port.get("target", "")) != str(target)
            or str(port.get("protocol", "tcp")) != "tcp"
            or not str(port.get("published", "")).isdigit()
        ):
            errors.append(f"{name} must publish TCP target {target} to 127.0.0.1 only")

    postgres = services.get("postgres")
    if not isinstance(postgres, dict):
        errors.append("required service postgres is missing")
    elif postgres.get("ports"):
        errors.append("postgres must not publish any host port")
    return errors


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        print("FAIL: Docker Compose did not return valid JSON", file=sys.stderr)
        return 1
    errors = validate_ports(data)
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    print("PASS: frontend, API and n8n publish only to 127.0.0.1; PostgreSQL is unpublished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
