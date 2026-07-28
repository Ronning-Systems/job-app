"""Smoke tests for docker-compose.yml.

The compose file declares the runtime contract between job-app
and my-stack: which images, which networks, which secrets, which
dependency chain. If it stops parsing, the next deploy breaks. If
the service set changes accidentally, the deploy script's image
build loop won't match. These tests are cheap insurance.

Run from the job-app repo root:

    /opt/data/.venv-autoapply/bin/pytest backend/tests/test_compose.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose():
    assert COMPOSE_PATH.exists(), f"docker-compose.yml not found at {COMPOSE_PATH}"
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


def test_compose_declares_all_five_services(compose):
    """The runtime contract: postgres, secrets-fetcher, fetcher,
    auto-apply, and api. Adding a new service should be a conscious
    change; this test fails if anyone accidentally drops one."""
    expected = {"postgres", "secrets-fetcher", "fetcher", "auto-apply", "api"}
    assert set(compose["services"].keys()) == expected


def test_compose_declares_required_secrets(compose):
    """vault_token, pg_password, and autoapply_hmac_secret are the
    three secrets the my-stack deploy script materializes on the
    host. Each must be declared here so the api + sidecar
    containers can mount them."""
    expected = {"vault_token", "pg_password", "autoapply_hmac_secret"}
    assert set(compose["secrets"].keys()) == expected


def test_compose_uses_external_proxy_network(compose):
    """The proxy network is created by the my-stack deploy script
    (one-time setup), not by this compose. The 'external: true'
    declaration prevents `docker compose up` from trying to create
    it (which would fail silently on a fresh host)."""
    assert compose["networks"]["proxy"]["external"] is True
    assert compose["networks"]["proxy"]["name"] == "proxy"


def test_api_depends_on_all_components(compose):
    """The api service must wait for postgres to be healthy,
    secrets-fetcher to complete (it runs once), and the two
    sidecars to be healthy. If a sidecar's healthcheck fails,
    the api shouldn't start — that way the rollup endpoint
    never reports 'api ok' while a sidecar is down."""
    deps = compose["services"]["api"]["depends_on"]
    assert deps["postgres"]["condition"] == "service_healthy"
    assert deps["secrets-fetcher"]["condition"] == "service_completed_successfully"
    assert deps["fetcher"]["condition"] == "service_healthy"
    assert deps["auto-apply"]["condition"] == "service_healthy"


def test_sidecars_have_healthchecks(compose):
    """Every sidecar must define a healthcheck so the api's
    depends_on health-gate fires correctly."""
    for sidecar in ("fetcher", "auto-apply"):
        assert "healthcheck" in compose["services"][sidecar], \
            f"{sidecar} is missing a healthcheck"


def test_sidecars_have_security_posture(compose):
    """Both sidecars must run with read-only rootfs + cap_drop ALL
    + no-new-privileges. This is the security posture the my-stack
    fetcher + autoapply stacks had; moving the compose to job-app
    must not lose it."""
    for sidecar in ("fetcher", "auto-apply"):
        svc = compose["services"][sidecar]
        assert svc.get("read_only") is True, f"{sidecar} must be read_only"
        assert svc.get("security_opt") == ["no-new-privileges:true"], \
            f"{sidecar} must have no-new-privileges"
        assert svc.get("cap_drop") == ["ALL"], \
            f"{sidecar} must drop all caps"
        assert "/tmp" in svc.get("tmpfs", []), \
            f"{sidecar} must have tmpfs /tmp for chromium scratch"


def test_api_uses_secret_file_for_hmac(compose):
    """The api must reference the same secret file as the auto-apply
    sidecar. Both containers sign/verify with the same secret."""
    api = compose["services"]["api"]
    assert api["environment"]["AUTOAPPLY_HMAC_SECRET_FILE"] == "/run/secrets/autoapply_hmac_secret"
    assert "autoapply_hmac_secret" in api["secrets"]
    autoapply = compose["services"]["auto-apply"]
    assert autoapply["environment"]["AUTOAPPLY_HMAC_SECRET_FILE"] == "/run/secrets/autoapply_hmac_secret"


def test_api_uses_service_names_for_sidecar_urls(compose):
    """Sidecar URLs must use the docker-compose service name, not
    localhost or 127.0.0.1. Service names resolve on the proxy
    network; localhost wouldn't work in a container."""
    api = compose["services"]["api"]
    assert api["environment"]["FETCHER_URL"] == "http://fetcher:8080"
    assert api["environment"]["AUTOAPPLY_URL"] == "http://auto-apply:8081"
