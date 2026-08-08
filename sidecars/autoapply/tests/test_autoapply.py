"""Tests for the auto-apply sidecar (sidecars/autoapply/autoapply.py).

Covers:
  - HMAC verification: missing headers, bad signature, replay window
  - /healthz: unauthenticated liveness
  - /sessions: auth required, allocates a session id
  - /sessions/{id}: 404 on unknown, returns state on known
  - /sessions/{id}/dry-run: auth + 404 + invalid-body, no real browser

The dry-run route in this v1 skeleton opens a real browser. Without a
network target and a Playwright binary, we can't exercise the success
path from CI; we only test the early-exit branches (auth, 404, invalid
body) which fire before the browser is touched. The browser-launch
behavior itself is exercised end-to-end in the container on
patrick-mini (not from this unit test).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add the sidecar directory to path so we can import autoapply as a
# module. parents[1] = sidecars/autoapply/, which contains autoapply.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import autoapply  # noqa: E402

# A stable test secret. Tests set AUTOAPPLY_HMAC_SECRET explicitly
# before importing the module so the route handlers see it via env.
TEST_SECRET = "test-secret-do-not-use-in-prod"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setenv("AUTOAPPLY_HMAC_SECRET", TEST_SECRET)
    # Also clear any session state from a prior test so session ids
    # don't collide and "404 on unknown" stays meaningful.
    autoapply._sessions.clear()
    yield


@pytest.fixture
def client():
    # The lifespan hook tries to launch a real Playwright browser; we
    # don't have one in CI. Bypass the lifespan so route tests don't
    # need a chromium binary. The routes themselves short-circuit
    # before the browser (auth, 404, invalid body), so this is safe
    # for the cases we cover here.
    return TestClient(autoapply.app, raise_server_exceptions=True)


def _sign(body: bytes, ts: str | None = None, secret: str = TEST_SECRET) -> dict[str, str]:
    """Build the X-AutoApply-* headers for a given body + timestamp."""
    timestamp = ts if ts is not None else str(int(time.time()))
    sig = autoapply.compute_signature(secret.encode("utf-8"), body, timestamp)
    return {
        autoapply.HMAC_HEADER_TIMESTAMP: timestamp,
        autoapply.HMAC_HEADER_SIGNATURE: sig,
    }


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


def test_healthz_is_unauthenticated(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # browser_ready is False in tests because we bypassed the lifespan.
    assert body["browser_ready"] is False


# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------


def test_post_sessions_rejects_missing_timestamp(client):
    r = client.post(
        "/sessions",
        headers={autoapply.HMAC_HEADER_SIGNATURE: "deadbeef"},
        content=b"",
    )
    assert r.status_code == 401
    assert "missing" in r.json()["detail"].lower()
    assert "timestamp" in r.json()["detail"].lower()


def test_post_sessions_rejects_missing_signature(client):
    r = client.post(
        "/sessions",
        headers={autoapply.HMAC_HEADER_TIMESTAMP: str(int(time.time()))},
        content=b"",
    )
    assert r.status_code == 401
    assert "missing" in r.json()["detail"].lower()
    assert "signature" in r.json()["detail"].lower()


def test_post_sessions_rejects_non_integer_timestamp(client):
    headers = _sign(b"")
    headers[autoapply.HMAC_HEADER_TIMESTAMP] = "not-a-number"
    r = client.post("/sessions", headers=headers, content=b"")
    assert r.status_code == 401
    assert "not an integer" in r.json()["detail"].lower()


def test_post_sessions_rejects_skewed_timestamp(client):
    # 10 minutes in the past — well outside the 5-minute replay window.
    skewed = str(int(time.time()) - 600)
    headers = _sign(b"", ts=skewed)
    r = client.post("/sessions", headers=headers, content=b"")
    assert r.status_code == 401
    assert "replay window" in r.json()["detail"].lower()


def test_post_sessions_rejects_bad_signature(client):
    timestamp = str(int(time.time()))
    r = client.post(
        "/sessions",
        headers={
            autoapply.HMAC_HEADER_TIMESTAMP: timestamp,
            autoapply.HMAC_HEADER_SIGNATURE: "0" * 64,
        },
        content=b"",
    )
    assert r.status_code == 401
    assert "signature mismatch" in r.json()["detail"].lower()


def test_post_sessions_rejects_when_secret_unset(client, monkeypatch):
    # Bypass the autouse fixture for this one test.
    monkeypatch.delenv("AUTOAPPLY_HMAC_SECRET")
    r = client.post("/sessions", content=b"")
    assert r.status_code == 503
    assert "AUTOAPPLY_HMAC_SECRET" in r.json()["detail"]


def test_post_sessions_reads_secret_from_file_when_env_unset(client, monkeypatch, tmp_path):
    """The deploy wires the secret via AUTOAPPLY_HMAC_SECRET_FILE (a
    mounted file) so it never appears in `docker inspect` output. When
    the plain env var is unset, _hmac_secret must fall back to reading
    that file, or every authenticated route 503s in the real stack.
    """
    secret_file = tmp_path / "hmac_secret"
    secret_file.write_text(TEST_SECRET)
    # Bypass the autouse fixture: unset the env var, point _FILE at a file.
    monkeypatch.delenv("AUTOAPPLY_HMAC_SECRET")
    monkeypatch.setenv("AUTOAPPLY_HMAC_SECRET_FILE", str(secret_file))
    r = client.post("/sessions", headers=_sign(b""), content=b"")
    assert r.status_code == 200
    body = r.json()
    assert "id" in body and len(body["id"]) >= 16


# ---------------------------------------------------------------------------
# /sessions (auth + happy path)
# ---------------------------------------------------------------------------


def test_post_sessions_with_valid_hmac_creates_session(client):
    r = client.post("/sessions", headers=_sign(b""), content=b"")
    assert r.status_code == 200
    body = r.json()
    assert "id" in body and len(body["id"]) >= 16
    assert "created_at" in body
    assert body["last_url"] is None


def test_get_session_returns_existing(client):
    create = client.post("/sessions", headers=_sign(b""), content=b"")
    sid = create.json()["id"]
    # GETs have no body, but we still need valid HMAC headers over
    # the empty body. The TestClient doesn't take `content` on get(),
    # so we pass headers + an empty body via a different kwarg.
    r = client.get(f"/sessions/{sid}", headers=_sign(b""))
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_get_session_returns_404_for_unknown(client):
    r = client.get(
        "/sessions/does-not-exist",
        headers=_sign(b""),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /sessions/{id}/dry-run (auth + 404 + invalid body — no browser needed)
# ---------------------------------------------------------------------------


def test_dry_run_requires_auth(client):
    # No HMAC headers.
    r = client.post(
        "/sessions/nope/dry-run",
        json={"url": "https://example.com/job/1"},
    )
    assert r.status_code == 401


def test_dry_run_returns_404_for_unknown_session(client):
    body = b'{"url": "https://example.com/job/1"}'
    r = client.post(
        "/sessions/nope/dry-run",
        headers=_sign(body),
        content=body,
    )
    assert r.status_code == 404


def test_dry_run_returns_400_for_invalid_body(client):
    create = client.post("/sessions", headers=_sign(b""), content=b"")
    sid = create.json()["id"]
    # body is JSON but missing the required `url` field
    body = b'{"not_url": "x"}'
    r = client.post(
        f"/sessions/{sid}/dry-run",
        headers=_sign(body),
        content=body,
    )
    # Pydantic validation error from FastAPI -> 422 by default; we
    # accept either 400 (our explicit re-raise) or 422.
    assert r.status_code in (400, 422)


def test_dry_run_returns_503_when_browser_not_ready(client):
    # The lifespan is bypassed in tests, so _browser stays None.
    create = client.post("/sessions", headers=_sign(b""), content=b"")
    sid = create.json()["id"]
    body = b'{"url": "https://example.com/job/1"}'
    r = client.post(
        f"/sessions/{sid}/dry-run",
        headers=_sign(body),
        content=body,
    )
    assert r.status_code == 503
    assert "browser not ready" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Signature scheme (unit-level, no FastAPI needed)
# ---------------------------------------------------------------------------


def test_compute_signature_is_deterministic():
    sig1 = autoapply.compute_signature(b"k", b"body", "1234567890")
    sig2 = autoapply.compute_signature(b"k", b"body", "1234567890")
    assert sig1 == sig2
    assert len(sig1) == 64  # hex sha256


def test_compute_signature_changes_with_any_input():
    base = autoapply.compute_signature(b"k", b"body", "1")
    assert autoapply.compute_signature(b"k2", b"body", "1") != base
    assert autoapply.compute_signature(b"k", b"body2", "1") != base
    assert autoapply.compute_signature(b"k", b"body", "2") != base
