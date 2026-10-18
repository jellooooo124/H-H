"""Regression tests for the private-only demo Compose host-port contract."""
import json
import subprocess
import sys
from pathlib import Path

from scripts.check_compose_ports import validate_ports

ROOT = Path(__file__).resolve().parents[1]


def safe_config():
    return {
        "services": {
            "frontend": {"ports": [{"host_ip": "127.0.0.1", "target": 80, "published": "8080", "protocol": "tcp"}]},
            "api": {"ports": [{"host_ip": "127.0.0.1", "target": 8000, "published": "8000", "protocol": "tcp"}]},
            "n8n": {"ports": [{"host_ip": "127.0.0.1", "target": 5678, "published": "5678", "protocol": "tcp"}]},
            "postgres": {},
        }
    }


def test_only_loopback_services_and_unpublished_postgres_are_accepted():
    assert validate_ports(safe_config()) == []


def test_exposed_frontend_fails_closed():
    config = safe_config()
    config["services"]["frontend"]["ports"][0]["host_ip"] = "0.0.0.0"
    assert "frontend" in " ".join(validate_ports(config))


def test_extra_public_api_binding_is_rejected_even_if_one_is_private():
    config = safe_config()
    config["services"]["api"]["ports"].append({"host_ip": "0.0.0.0", "target": 8000, "published": "18000"})
    assert "api" in " ".join(validate_ports(config))


def test_unpublished_api_or_missing_service_fails_closed():
    config = safe_config()
    config["services"]["api"]["ports"] = []
    del config["services"]["n8n"]
    errors = " ".join(validate_ports(config))
    assert "api" in errors and "n8n" in errors


def test_exposed_postgres_is_rejected():
    config = safe_config()
    config["services"]["postgres"]["ports"] = [{"host_ip": "127.0.0.1", "target": 5432, "published": "5432"}]
    assert "postgres" in " ".join(validate_ports(config))


def test_wrong_target_ipv6_or_missing_host_bind_is_rejected():
    for mutation in [{"target": 1234}, {"host_ip": "::1"}, {"host_ip": ""}]:
        config = safe_config()
        config["services"]["n8n"]["ports"][0].update(mutation)
        assert validate_ports(config)


def test_cli_returns_failure_without_revealing_config_secrets():
    config = safe_config()
    config["services"]["frontend"]["ports"][0]["host_ip"] = "0.0.0.0"
    config["services"]["frontend"]["environment"] = {"APP_TOKEN_SECRET": "do-not-print"}
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_compose_ports.py")],
        input=json.dumps(config), text=True, capture_output=True, check=False,
    )
    assert run.returncode == 1
    assert "frontend" in run.stderr
    assert "do-not-print" not in run.stdout + run.stderr
