"""Tests for the JS-SPA shell detection used by /api/jobs/from-url.

When a job board is rendered as a client-side SPA (Nuxt, Next, React,
Vue), a direct httpx fetch returns 200 with a near-empty body that
contains only the SPA root marker. The parser cannot extract a job
from that, so the from-url route must detect the shell and route the
fetch through the Playwright sidecar instead. _looks_like_spa_shell
encapsulates that detection.

These tests are pure-function tests of the helper — no DB, no
auth, no HTTP. The helper is reached via a lazy import of main so
that the (heavy) DB-driven module isn't pulled in unless the tests
actually run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# main.py reads several env vars at import time. Set safe defaults
# so importing the module for these tests doesn't try to open a
# real Postgres / Auth0 connection.
os.environ.setdefault("DATABASE_URL", "sqlite:///./_test_shell.db")
os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.test")
os.environ.setdefault("AUTH0_AUDIENCE", "https://test/api")
os.environ.setdefault("AUTH0_CLIENT_ID", "test")

# Add backend/ to sys.path so `import main` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import main  # noqa: E402


@pytest.fixture(scope="module")
def shell_detector():
    return main._looks_like_spa_shell


def test_empty_string_is_a_shell(shell_detector):
    assert shell_detector("") is True


def test_nuxt_shell_with_no_text_is_detected(shell_detector):
    # Mirror the kind of body providence.jobs returns: a Nuxt app
    # configured with data-ssr="false" renders an empty <div id="__nuxt">.
    html = (
        '<!DOCTYPE html><html lang="en"><head><title>Jobs | Providence</title>'
        '</head><body><div id="__nuxt"></div><script>window.__NUXT__={}</script>'
        "</body></html>"
    )
    assert shell_detector(html) is True


def test_react_root_with_no_children_is_detected(shell_detector):
    html = '<html><body><div id="root"></div></body></html>'
    assert shell_detector(html) is True


def test_next_root_with_no_children_is_detected(shell_detector):
    html = '<html><body><div id="__next"></div></body></html>'
    assert shell_detector(html) is True


def test_short_page_without_spa_root_is_not_a_shell(shell_detector):
    # A small but legitimate posting must NOT trip the shell detector;
    # otherwise the parser would unnecessarily bounce through the sidecar.
    html = (
        "<html><body><h1>Greeter</h1><p>Walmart</p>"
        "<p>Requirements: friendly attitude.</p></body></html>"
    )
    assert shell_detector(html) is False


def test_full_rendered_job_posting_is_not_a_shell(shell_detector):
    # Real posting with enough visible text — must be a clear non-shell.
    body = (
        "<h1>Cashier</h1><p>Acme Inc.</p>"
        "<p>Apply by sending a resume to jobs@acme.example.</p>"
        "<p>Requirements: 1 year customer service experience.</p>"
    ) * 5
    assert shell_detector(f"<html><body>{body}</body></html>") is False


def test_shell_with_some_visible_text_below_threshold_is_detected(shell_detector):
    # Visible text under the threshold plus an SPA root -> still a shell.
    visible = "Jobs | Providence"  # 19 chars
    html = f'<html><head><title>{visible}</title></head><body><div id="__nuxt"></div></body></html>'
    assert shell_detector(html) is True
