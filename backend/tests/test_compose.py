"""Smoke tests for docker-compose.yml (prod) and
docker-compose.test.yml (test).

The compose files declare the runtime contract between job-app
and my-stack: which images, which networks, which secrets, which
dependency chain. If they stop parsing, the next deploy breaks.
If the service set changes accidentally, the deploy script's
image build loop won't match. These tests are cheap insurance.

The prod and test composes are structurally identical: same five
services, same security posture, same healthchecks, same
dependency chain. The differences are the names + paths (test
uses -test suffixes on every service and container_name so prod
and test can run in parallel on the same `proxy` Docker network
without DNS collisions).

Run from the job-app repo root:

    /opt/data/.venv-autoapply/bin/pytest backend/tests/test_compose.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


COMPOSE_DIR = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict:
    path = COMPOSE_DIR / name
    assert path.exists(), f"{name} not found at {path}"
    with open(path) as f:
        return yaml.safe_load(f)


# Map filename -> service-name suffix. The prod compose uses bare
# names (postgres, fetcher, etc.); the test compose uses -test
# suffixed names (postgres-test, fetcher-test, etc.). The collision
# avoidance test verifies that no service name appears in BOTH
# files; this dict tells the per-file tests which names to look
# for.
SERVICE_NAMES = {
    "docker-compose.yml": {
        "postgres": "postgres",
        "secrets-fetcher": "secrets-fetcher",
        "fetcher": "fetcher",
        "auto-apply": "auto-apply",
        "api": "api",
    },
    "docker-compose.test.yml": {
        "postgres": "postgres-test",
        "secrets-fetcher": "secrets-fetcher-test",
        "fetcher": "fetcher-test",
        "auto-apply": "auto-apply-test",
        "api": "api-test",
    },
}


# ---------------------------------------------------------------------------
# Parametrized fixtures: every test that follows runs once per compose file.
# The fixture gives each test a (filename, compose_dict, service_names)
# triple so assertions can look up the right per-file names.
# ---------------------------------------------------------------------------


@pytest.fixture(params=["docker-compose.yml", "docker-compose.test.yml"])
def compose_pair(request):
    filename = request.param
    return (filename, _load(filename), SERVICE_NAMES[filename])


# ---------------------------------------------------------------------------
# Tests that apply to BOTH compose files.
# ---------------------------------------------------------------------------


def test_declares_all_five_services(compose_pair):
    """The runtime contract: postgres, secrets-fetcher, fetcher,
    auto-apply, and api. Adding a new service should be a conscious
    change; this test fails if anyone accidentally drops one."""
    filename, compose, names = compose_pair
    expected = set(names.values())
    assert set(compose["services"].keys()) == expected, \
        f"{filename} is missing or has extra services. Expected {expected}, got {set(compose['services'].keys())}"


def test_declares_required_secrets(compose_pair):
    filename, compose, _ = compose_pair
    expected = {"vault_token", "pg_password", "autoapply_hmac_secret"}
    assert set(compose["secrets"].keys()) == expected, \
        f"{filename} is missing or has extra secrets"


def test_uses_external_proxy_network(compose_pair):
    """The proxy network is created by the my-stack deploy script
    (one-time setup), not by this compose. The 'external: true'
    declaration prevents `docker compose up` from trying to create
    it (which would fail silently on a fresh host)."""
    filename, compose, _ = compose_pair
    assert compose["networks"]["proxy"]["external"] is True, \
        f"{filename} proxy network must be external"
    assert compose["networks"]["proxy"]["name"] == "proxy", \
        f"{filename} proxy network name must be 'proxy'"


def test_api_depends_on_all_components(compose_pair):
    """The api service must wait for postgres to be healthy,
    secrets-fetcher to complete (it runs once), and the two
    sidecars to be healthy."""
    filename, compose, names = compose_pair
    deps = compose["services"][names["api"]]["depends_on"]
    assert deps[names["postgres"]]["condition"] == "service_healthy", \
        f"{filename} api must depend on postgres healthy"
    assert deps[names["secrets-fetcher"]]["condition"] == "service_completed_successfully", \
        f"{filename} api must depend on secrets-fetcher completed"
    assert deps[names["fetcher"]]["condition"] == "service_healthy", \
        f"{filename} api must depend on fetcher healthy"
    assert deps[names["auto-apply"]]["condition"] == "service_healthy", \
        f"{filename} api must depend on auto-apply healthy"


def test_sidecars_have_healthchecks(compose_pair):
    filename, compose, names = compose_pair
    for sidecar in (names["fetcher"], names["auto-apply"]):
        assert "healthcheck" in compose["services"][sidecar], \
            f"{filename} {sidecar} is missing a healthcheck"


def test_sidecars_have_security_posture(compose_pair):
    """Both sidecars must run with read-only rootfs + cap_drop ALL
    + no-new-privileges."""
    filename, compose, names = compose_pair
    for sidecar in (names["fetcher"], names["auto-apply"]):
        svc = compose["services"][sidecar]
        assert svc.get("read_only") is True, f"{filename} {sidecar} must be read_only"
        assert svc.get("security_opt") == ["no-new-privileges:true"], \
            f"{filename} {sidecar} must have no-new-privileges"
        assert svc.get("cap_drop") == ["ALL"], \
            f"{filename} {sidecar} must drop all caps"
        assert "/tmp" in svc.get("tmpfs", []), \
            f"{filename} {sidecar} must have tmpfs /tmp for chromium scratch"


def test_api_uses_secret_file_for_hmac(compose_pair):
    filename, compose, names = compose_pair
    api = compose["services"][names["api"]]
    assert api["environment"]["AUTOAPPLY_HMAC_SECRET_FILE"] == "/run/secrets/autoapply_hmac_secret", \
        f"{filename} api must reference /run/secrets/autoapply_hmac_secret"
    assert "autoapply_hmac_secret" in api["secrets"], \
        f"{filename} api must mount autoapply_hmac_secret"
    autoapply = compose["services"][names["auto-apply"]]
    assert autoapply["environment"]["AUTOAPPLY_HMAC_SECRET_FILE"] == "/run/secrets/autoapply_hmac_secret", \
        f"{filename} auto-apply must reference /run/secrets/autoapply_hmac_secret"


# ---------------------------------------------------------------------------
# Tests that compare the two compose files against each other.
# ---------------------------------------------------------------------------


def test_container_names_avoid_collision_on_proxy_network():
    """When prod and test run in parallel on the same `proxy` Docker
    network, their container_name values must not collide. If two
    containers from different compose projects share a name, Docker
    refuses to start the second one with 'container name is already
    in use'.

    Also verify service names don't collide (Docker DNS on a custom
    network resolves by service name as well as container name; a
    service-name collision would cause unpredictable DNS resolution
    between the two envs).
    """
    prod = _load("docker-compose.yml")
    test = _load("docker-compose.test.yml")

    prod_container_names = {svc["container_name"] for svc in prod["services"].values() if "container_name" in svc}
    test_container_names = {svc["container_name"] for svc in test["services"].values() if "container_name" in svc}
    overlap = prod_container_names & test_container_names
    assert not overlap, f"container_name collision between prod and test: {overlap}"

    prod_service_names = set(prod["services"].keys())
    test_service_names = set(test["services"].keys())
    overlap_services = prod_service_names & test_service_names
    assert not overlap_services, f"service name collision between prod and test: {overlap_services}"


def test_api_uses_service_names_for_sidecar_urls():
    """Sidecar URLs must use the docker-compose service name (not
    localhost or 127.0.0.1). For prod: http://fetcher:8080; for
    test: http://fetcher-test:8080. The api container's
    /api/health/system rollup probes these same URLs."""
    prod = _load("docker-compose.yml")
    test = _load("docker-compose.test.yml")

    assert prod["services"]["api"]["environment"]["FETCHER_URL"] == "http://fetcher:8080", \
        "prod api must use http://fetcher:8080"
    assert prod["services"]["api"]["environment"]["AUTOAPPLY_URL"] == "http://auto-apply:8081", \
        "prod api must use http://auto-apply:8081"

    assert test["services"]["api-test"]["environment"]["FETCHER_URL"] == "http://fetcher-test:8080", \
        "test api must use http://fetcher-test:8080"
    assert test["services"]["api-test"]["environment"]["AUTOAPPLY_URL"] == "http://auto-apply-test:8081", \
        "test api must use http://auto-apply-test:8081"


def test_test_compose_uses_separate_vault_path():
    """The test env reads from a different Vault KV path so prod
    rotations don't accidentally hit test. Both paths are
    readable by the same jobapp policy token."""
    test = _load("docker-compose.test.yml")
    sf = test["services"]["secrets-fetcher-test"]
    assert sf["environment"]["SECRET_PATH"] == "jobapp/test", \
        "test secrets-fetcher must read from jobapp/test Vault KV path"


def test_test_compose_uses_separate_host_paths():
    """The test env's host volume paths live under /srv/jobapp-test/
    so they don't share postgres data + secrets with prod."""
    test = _load("docker-compose.test.yml")
    pg = test["services"]["postgres-test"]
    # Volume is bind-mounted from /srv/jobapp-test/postgres
    assert any("/srv/jobapp-test/" in str(v) for v in pg.get("volumes", [])), \
        "test postgres must bind-mount from /srv/jobapp-test/"
    # pg_password secret file path is /srv/jobapp-test/secrets/pg_password
    pg_pw = test["secrets"]["pg_password"]["file"]
    assert pg_pw.startswith("/srv/jobapp-test/"), \
        f"test pg_password must be under /srv/jobapp-test/, got {pg_pw}"
    # HMAC secret file path is also under /srv/jobapp-test/
    hmac = test["secrets"]["autoapply_hmac_secret"]["file"]
    assert hmac.startswith("/srv/jobapp-test/"), \
        f"test HMAC secret must be under /srv/jobapp-test/, got {hmac}"


def test_test_compose_uses_separate_postgres_db():
    """The test env uses a separate postgres DB name (jobapp_test)
    so even if a misconfigured DATABASE_URL ever points test at
    the prod postgres, the queries go to a different schema and
    don't corrupt prod data."""
    test = _load("docker-compose.test.yml")
    pg = test["services"]["postgres-test"]
    assert pg["environment"]["POSTGRES_DB"] == "jobapp_test", \
        f"test postgres DB must be 'jobapp_test', got {pg['environment']['POSTGRES_DB']}"
