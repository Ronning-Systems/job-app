#!/usr/bin/env python3
"""Auto-apply sidecar for Joblign.

A sibling service to the existing URL-rendering fetcher
(``portainer/fetcher.py``). Where the fetcher is a *read-only* browser
sidecar that renders job-board HTML for the Joblign backend, this
service is the *write* sidecar: it opens external job-application
forms, fills them from the user's profile + generated artifacts, and
(once a future slice lands) submits them on the user's approval.

This is the v1 *skeleton*. It implements:

  GET  /healthz                  — unauthenticated liveness probe
  POST /sessions                 — allocate a new session id
  GET  /sessions/{id}            — return session state
  POST /sessions/{id}/dry-run    — navigate to the target URL and
                                   return {title, final_url, status}
                                   WITHOUT filling or submitting
                                   anything. The end-to-end "is
                                   Playwright alive + is the URL
                                   reachable" probe the Joblign
                                   backend can hit from CI.

Auth (TR-2): all routes except ``/healthz`` require an HMAC-SHA256
signature computed over ``body_bytes + "." + unix_timestamp_seconds``
with a shared secret sourced from ``AUTOAPPLY_HMAC_SECRET``. Headers:

  X-AutoApply-Timestamp: 1700000000
  X-AutoApply-Signature: <hex>

Replay window: 5 minutes (configurable via env). Comparison is
constant-time.

Sessions are in-memory and do NOT survive container restart. The
spec calls for persistent browser profiles under ``/data/sessions``
(TR-1, TR-9); that lands in a follow-up slice once the auth +
transport story is proven end-to-end.

Security posture (TR-1, mirrors jobapp-fetcher):
  - read-only root filesystem
  - tmpfs /tmp
  - no-new-privileges
  - all caps dropped
  - no Traefik labels, only on the internal ``proxy`` Docker network
  - exposed internally as http://auto-apply:8081

DELIBERATELY DIFFERENT from the fetcher: this service navigates to
*any* URL the user provides (job boards, login pages, OAuth
providers). It does NOT enforce the fetcher's SSRF guard, because the
whole point of auto-apply is to open third-party sites. The
HMAC auth + internal-only network + read-only rootfs are the
defenses that gate who can drive this browser.
"""
from __future__ import annotations

import hashlib
import hmac
import json as _json
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from playwright.async_api import Browser, Error as PlaywrightError, async_playwright
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HMAC_HEADER_TIMESTAMP = "X-AutoApply-Timestamp"
HMAC_HEADER_SIGNATURE = "X-AutoApply-Signature"

# Replay window: requests with a timestamp more than this many seconds
# away from server time are rejected. 5 minutes matches the fetcher's
# no-replay posture (the fetcher has no headers at all, but a 5-minute
# window is a common safe default for HMAC schemes).
REPLAY_WINDOW_SECONDS = 300

# Navigation timeout for dry-run. Job-board pages can be slow; 30s
# matches the fetcher's NAV_TIMEOUT_MS.
NAV_TIMEOUT_MS = 30_000

USER_AGENT = (
    # Same UA string as the fetcher so we look like the same browser
    # to CDNs that fingerprint. If a job board blocks the fetcher,
    # it'll block us too — and the user sees a consistent error.
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# In-memory session table. Process-local by design for v1; persistence
# lives in a follow-up slice.
_sessions: dict[str, "Session"] = {}

# Shared browser instance, populated by the lifespan startup hook.
_browser: Browser | None = None


def _hmac_secret() -> bytes:
    """Return the shared HMAC secret. Raises 503 if not configured —
    the container is misconfigured and we want a loud failure, not a
    silent acceptance of empty signatures."""
    raw = os.environ.get("AUTOAPPLY_HMAC_SECRET", "")
    if not raw:
        raise HTTPException(
            status_code=503,
            detail="AUTOAPPLY_HMAC_SECRET is not set on the server",
        )
    return raw.encode("utf-8")


# ---------------------------------------------------------------------------
# HMAC verification
# ---------------------------------------------------------------------------


def compute_signature(secret: bytes, body: bytes, timestamp: str) -> str:
    """Compute the hex HMAC-SHA256 signature for a request.

    Signing string: ``body_bytes + "." + timestamp_str``. The body
    MUST be the raw request body bytes (not the parsed JSON), so the
    signature covers the exact wire bytes and any re-serialization
    can't accidentally pass.
    """
    msg = body + b"." + timestamp.encode("ascii")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


async def verify_hmac(request: Request) -> bytes:
    """FastAPI dependency: validate HMAC headers + replay window and
    return the raw request body so the handler can parse it.

    Rejection modes (all 401, with distinct reasons so debugging the
    Joblign-side signer is easy):
      - missing timestamp header
      - missing signature header
      - non-numeric timestamp
      - timestamp outside the replay window
      - signature mismatch (constant-time)
    """
    secret = _hmac_secret()
    timestamp = request.headers.get(HMAC_HEADER_TIMESTAMP)
    signature = request.headers.get(HMAC_HEADER_SIGNATURE)
    if not timestamp:
        raise HTTPException(status_code=401, detail=f"missing {HMAC_HEADER_TIMESTAMP}")
    if not signature:
        raise HTTPException(status_code=401, detail=f"missing {HMAC_HEADER_SIGNATURE}")
    try:
        ts_int = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="timestamp is not an integer")
    skew = abs(int(time.time()) - ts_int)
    if skew > REPLAY_WINDOW_SECONDS:
        raise HTTPException(
            status_code=401,
            detail=f"timestamp outside replay window (skew={skew}s)",
        )
    # Read the body ONCE here so the handler can re-parse it. We
    # intentionally do this AFTER the cheap header checks so a
    # malformed-auth request doesn't pay the body-read cost.
    body = await request.body()
    expected = compute_signature(secret, body, timestamp)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="signature mismatch")
    return body


# ---------------------------------------------------------------------------
# Session model
# ---------------------------------------------------------------------------


class Session(BaseModel):
    id: str
    created_at: float
    last_url: str | None = None
    last_title: str | None = None
    last_status: int | None = None


def _new_session() -> Session:
    sid = secrets.token_urlsafe(16)
    s = Session(id=sid, created_at=time.time())
    _sessions[sid] = s
    return s


def _get_session(sid: str) -> Session:
    s = _sessions.get(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class DryRunRequest(BaseModel):
    url: str = Field(..., description="Target job-application URL to navigate to")


class DryRunResponse(BaseModel):
    session_id: str
    final_url: str
    title: str
    status: int


class HealthResponse(BaseModel):
    status: str
    browser_ready: bool


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Launch one chromium browser on startup, reuse it for every
    request, close it on shutdown. Same pattern as the fetcher so the
    two services look operationally identical from the host's POV.
    """
    global _browser
    async with async_playwright() as pw:
        _browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            yield
        finally:
            await _browser.close()
            _browser = None


app = FastAPI(title="jobapp-auto-apply", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Unauthenticated liveness probe. Returns 200 once the browser is
    up; the orchestrator's healthcheck treats any 200 as healthy
    regardless of the body shape."""
    return HealthResponse(status="ok", browser_ready=_browser is not None)


@app.post("/sessions", response_model=Session)
async def create_session(_body: Annotated[bytes, Depends(verify_hmac)]) -> Session:
    """Allocate a new session. The request body is allowed to be
    empty; the dependency still verifies the HMAC over the empty
    body so callers can't skip signing by sending POST /sessions with
    no payload.
    """
    return _new_session()


@app.get("/sessions/{sid}", response_model=Session)
async def get_session(sid: str, _=Depends(verify_hmac)) -> Session:
    return _get_session(sid)


@app.post("/sessions/{sid}/dry-run", response_model=DryRunResponse)
async def dry_run(
    sid: str,
    body: Annotated[bytes, Depends(verify_hmac)],
) -> DryRunResponse:
    """Open the target URL in a fresh context, return the final URL,
    page title, and HTTP status. Does NOT fill, click, or submit
    anything. This is the end-to-end "is the browser alive + can we
    reach the target" probe that CI can hit to prove the sidecar
    stack is wired up correctly.

    Returns 404 if ``sid`` is unknown, 503 if the browser isn't
    ready, 502 if Playwright surfaces a navigation error.
    """
    session = _get_session(sid)

    # We can't use a Pydantic body= parameter because the verify_hmac
    # dependency already consumed the request stream; re-parse the
    # raw bytes the dependency returned. Validate the body BEFORE
    # touching the browser so a malformed request can't waste a
    # 30-second navigation timeout.
    try:
        payload = DryRunRequest.model_validate(_json.loads(body or b"{}"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid body: {e}")

    if _browser is None:
        raise HTTPException(status_code=503, detail="browser not ready")

    # Fresh context per call, closed in the finally block. Same
    # posture as the fetcher: cookies/storage from one job board
    # must never leak into another.
    context = await _browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()
    try:
        resp = await page.goto(payload.url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
        if resp is None:
            raise HTTPException(status_code=502, detail="navigation returned no response")
        title = await page.title()
        session.last_url = page.url
        session.last_title = title
        session.last_status = resp.status
        return DryRunResponse(
            session_id=session.id,
            final_url=page.url,
            title=title,
            status=resp.status,
        )
    except PlaywrightError as e:
        raise HTTPException(status_code=502, detail=f"playwright error: {e}")
    finally:
        await page.close()
        await context.close()
