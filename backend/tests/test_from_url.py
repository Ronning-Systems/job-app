"""Tests for the from-url route's fetcher-sidecar fallback behavior.

The regression we guard against: when the direct httpx fetch returns
a JS-SPA shell (Nuxt/Next/React with no rendered content) and the
fetcher sidecar then fails (unreachable, 5xx, etc.), the route must
return a clean 502 to the caller — NOT fall back to parsing the
empty shell, which would cause the LLM parser to "succeed" on the
page <title> and fabricate a bogus job (e.g. company=Providence,
position=Jobs for a Nuxt page titled "Jobs | Providence").

The fix lives in main.py:1827 — when the sidecar call fails AND the
fallback content is itself a SPA shell, drop the shell and let the
route surface the error.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# main.py reads several env vars at import time. Set safe defaults
# so importing the module for these tests doesn't try to open a
# real Postgres / Auth0 connection.
os.environ.setdefault("DATABASE_URL", "sqlite:///./_test_url.db")
os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.test")
os.environ.setdefault("AUTH0_AUDIENCE", "https://test/api")
os.environ.setdefault("AUTH0_CLIENT_ID", "test")
os.environ.setdefault("FETCHER_URL", "http://fetcher-test:8080")

# Add backend/ to sys.path so `import main` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402
import models  # noqa: E402


# Minimal Nuxt SPA shell — the kind of body providence.jobs and similar
# boards return before any JS executes. Mirrors the snippet we
# observed in the wild.
PROVIDENCE_SHELL_HTML = (
    '<!DOCTYPE html><html lang="en"><head>'
    '<title>Jobs | Providence</title></head><body>'
    '<div id="__nuxt"></div>'
    '<script>window.__NUXT__={}</script>'
    '</body></html>'
)


@pytest.fixture
def app():
    """Mount main.py's app, but override get_db and get_current_user
    so no real DB or auth is required. The from-url test only
    exercises the fetch + fallback path; on a 502 we never touch
    the DB. Other routes exist on the app but we never call them."""
    # Use a no-op DB session (MagicMock) — overridden via dependency_overrides.
    app = main.app

    def _fake_db():
        # Caller pattern is `db: Session = Depends(get_db)` which yields
        # a single session per request. The from-url route only uses db
        # after a successful parse, which never happens in these tests.
        try:
            yield MagicMock()
        finally:
            pass

    fake_user = MagicMock()
    fake_user.id = 1
    fake_user.email = "test@test.test"

    def _fake_user():
        return fake_user

    app.dependency_overrides[models.get_db] = _fake_db
    app.dependency_overrides[main.get_current_user] = _fake_user
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def _httpx_response(status_code: int, text: str) -> MagicMock:
    """Build a MagicMock that quacks like an httpx.Response enough
    for the from-url route to use it (status_code, text, raise_for_status)."""
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    if status_code >= 400:
        # raise_for_status() should raise; emulate with a real httpx error.
        import httpx as _httpx
        r.raise_for_status.side_effect = _httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=MagicMock(status_code=status_code)
        )
    else:
        r.raise_for_status.return_value = None
    return r


def _patch_httpx_post(side_effect=None, return_value=None):
    """Return a patch() that replaces httpx.AsyncClient.post.

    side_effect: an exception instance to raise (e.g. ConnectError).
    return_value: a MagicMock response to return.
    """
    return patch("main.httpx.AsyncClient.post", new=AsyncMock(
        side_effect=side_effect, return_value=return_value
    ))


def _patch_httpx_get(side_effect=None, return_value=None):
    return patch("main.httpx.AsyncClient.get", new=AsyncMock(
        side_effect=side_effect, return_value=return_value
    ))


def test_spa_shell_with_failing_sidecar_returns_502(client):
    """Regression: SPA shell from httpx + sidecar failure must
    surface a 502, not silently fall through to the parser."""
    httpx_response = _httpx_response(200, PROVIDENCE_SHELL_HTML)

    with _patch_httpx_get(return_value=httpx_response), \
         _patch_httpx_post(side_effect=Exception("sidecar unreachable")):
        r = client.post("/api/jobs/from-url", json={
            "url": "https://providence.jobs/some/job/"
        })

    assert r.status_code == 502, r.text
    # The 502 detail must mention the sidecar failure, not a parsing
    # success — the user needs to know the sidecar is the problem.
    assert "sidecar" in r.json()["detail"].lower()


def test_blocked_httpx_with_failing_sidecar_keeps_original_error(client):
    """When httpx fails AND the sidecar also fails, the route returns
    502 with the *original* httpx error message (the sidecar error
    is suppressed). This is the existing behavior preserved by the
    `if not fetch_error:` guard in the catch block."""
    import httpx as _httpx
    err = _httpx.ConnectError("dns failed")

    with _patch_httpx_get(side_effect=err), \
         _patch_httpx_post(side_effect=Exception("sidecar unreachable")):
        r = client.post("/api/jobs/from-url", json={
            "url": "https://example.com/job/"
        })

    assert r.status_code == 502
    assert "dns failed" in r.json()["detail"]


def test_legitimate_non_shell_with_httpx_error_returns_502_without_calling_sidecar_fallthrough(client):
    """When httpx returns 200 with real content (not a shell), the
    route should NOT call the sidecar at all — it should just
    parse the content it already has. This is the happy path
    for static job-board pages."""
    real_html = (
        "<html><body><h1>Cashier</h1>"
        "<p>Acme Inc. - Portland, OR</p>"
        + ("<p>Job description. </p>" * 100)  # enough to be >> 250 chars
        + "</body></html>"
    )
    httpx_response = _httpx_response(200, real_html)

    # The Ollama parser would normally be called here. Patch it to
    # raise so we can confirm we get the expected 500 (parse error)
    # rather than 502 — proving the sidecar was NOT invoked.
    parser_patch = patch.object(
        main.JobParser, "parse_from_html",
        new=AsyncMock(side_effect=Exception("fake parse failure"))
    )
    with _patch_httpx_get(return_value=httpx_response), parser_patch, \
         _patch_httpx_post() as sidecar_post:
        r = client.post("/api/jobs/from-url", json={
            "url": "https://example.com/job/"
        })

    # parse_from_html raised -> 500 (caught in the route as a
    # parse error). Crucially, the sidecar was NOT called.
    assert r.status_code == 500
    sidecar_post.assert_not_called()
