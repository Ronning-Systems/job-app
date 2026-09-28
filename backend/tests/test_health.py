"""Tests for the /api/health/system rollup endpoint.

The rollup probes every job-app-owned dependency (fetcher, postgres,
ollama) and returns one 200/503 the deploy script can poll.
The shallow /api/health endpoint stays unchanged for backward compat
with the Traefik healthcheck and the existing my-stack deploy
script's per-container healthcheck loop.

Adding a new sidecar = adding a probe to backend/health.py. The
component map in the response is the source of truth for what the
deploy script trusts.

Test strategy: we don't import main.py (it pulls in sqlalchemy +
models + the whole DB stack, which is heavy and irrelevant for a
probe-rollup test). We mount the health router on a minimal
FastAPI app and exercise it in isolation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Add backend/ to sys.path so we can import health as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def app():
    """Minimal FastAPI app with the health router mounted. Avoids
    importing main.py (which pulls in the full DB stack)."""
    from health import router
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


def _patch_probes(**probe_returns):
    """Return a list of patch() contexts that override each probe to
    return the given (status, detail) tuple. Unspecified probes
    default to ("ok", None)."""
    defaults = {
        "fetcher": ("ok", None),
        "postgres": ("ok", None),
        "ollama": ("ok", None),
    }
    defaults.update(probe_returns)
    return [
        patch(f"health._probe_{name}", AsyncMock(return_value=value))
        for name, value in defaults.items()
    ]


def test_health_system_reports_overall_ok_when_all_components_ok(client):
    patches = _patch_probes()
    for p in patches:
        p.start()
    try:
        r = client.get("/api/health/system")
    finally:
        for p in patches:
            p.stop()

    assert r.status_code == 200
    body = r.json()
    assert body["overall"] == "ok"
    assert set(body["components"].keys()) == {"fetcher", "postgres", "ollama"}
    for name, comp in body["components"].items():
        assert comp["status"] == "ok", f"{name} should be ok: {comp}"
        assert comp["detail"] is None


def test_health_system_reports_degraded_when_one_component_down(client):
    patches = _patch_probes(fetcher=("down", "connection refused"))
    for p in patches:
        p.start()
    try:
        r = client.get("/api/health/system")
    finally:
        for p in patches:
            p.stop()

    assert r.status_code == 503
    body = r.json()
    assert body["overall"] == "degraded"
    assert body["components"]["fetcher"]["status"] == "down"
    assert body["components"]["fetcher"]["detail"] == "connection refused"
    # The other two should still report ok
    for name in ("postgres", "ollama"):
        assert body["components"][name]["status"] == "ok"


def test_health_system_returns_503_when_all_components_down(client):
    patches = _patch_probes(
        fetcher=("down", "connection refused"),
        postgres=("down", "OperationalError"),
        ollama=("down", "timeout"),
    )
    for p in patches:
        p.start()
    try:
        r = client.get("/api/health/system")
    finally:
        for p in patches:
            p.stop()

    assert r.status_code == 503
    body = r.json()
    assert body["overall"] == "degraded"
    for name in ("fetcher", "postgres", "ollama"):
        assert body["components"][name]["status"] == "down"


def test_health_system_handles_probe_exception_as_down(client):
    """If a probe raises (e.g. network misconfigured, import error),
    the rollup should treat it as 'down' and report the error type
    + message as detail, not crash the endpoint."""
    with patch("health._probe_fetcher", AsyncMock(side_effect=ConnectionError("simulated"))), \
         patch("health._probe_postgres", AsyncMock(return_value=("ok", None))), \
         patch("health._probe_ollama", AsyncMock(return_value=("ok", None))):
        r = client.get("/api/health/system")

    assert r.status_code == 503
    body = r.json()
    assert body["overall"] == "degraded"
    assert body["components"]["fetcher"]["status"] == "down"
    assert "ConnectionError" in body["components"]["fetcher"]["detail"]


def test_health_system_component_set_is_stable(client):
    """The set of components reported must be stable across calls.
    The deploy script's log parsers depend on a known key set."""
    patches = _patch_probes()
    for p in patches:
        p.start()
    try:
        keys_1 = set(client.get("/api/health/system").json()["components"].keys())
        keys_2 = set(client.get("/api/health/system").json()["components"].keys())
    finally:
        for p in patches:
            p.stop()
    assert keys_1 == keys_2
    assert keys_1 == {"fetcher", "postgres", "ollama"}
