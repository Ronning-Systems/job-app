#!/usr/bin/env python3
"""URL-rendering sidecar for Joblign.

A minimal FastAPI service that drives a headless Playwright chromium
browser to render JS-heavy job-board pages (LinkedIn, Indeed, etc.) to
static HTML, so the Joblign app can fetch URLs that block plain httpx.

Designed to run as an internal sidecar on the `proxy` Docker network,
callable only from the jobapp container as http://fetcher:8080. It is
NOT exposed publicly via Traefik.

Endpoints:
  GET  /healthz  -> {"status": "ok"}
  POST /fetch    -> {"html": <rendered html>, "status": <int>, "url": <final url>}
                    request body: {"url": "https://..."}

A single shared browser instance is launched on startup (via the
FastAPI lifespan) and reused across requests. Each request opens a
fresh browser context + page and closes both in a finally block, so
one bad URL can't poison the state of the next.

SSRF protection: /fetch rejects non-http(s) URLs and any URL whose
hostname resolves (via getaddrinfo) to a private, loopback, link-local,
reserved, multicast, or unspecified address. This prevents the fetcher
being used to probe the host's internal network. DNS rebinding is not
mitigated (the lookup happens once before navigation) — accepted risk
for a sidecar reachable only from the trusted jobapp container.
"""
from __future__ import annotations

import ipaddress
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from playwright.async_api import Browser, Error as PlaywrightError, async_playwright
from pydantic import BaseModel, HttpUrl

# Realistic desktop Chrome user-agent. Playwright's default chromium UA
# contains "HeadlessChrome", which many job-board CDNs fingerprint and
# block outright. This matches a current stable Linux Chrome build.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
NAV_TIMEOUT_MS = 30_000

# Shared browser instance, populated by the lifespan startup hook and
# torn down on shutdown. Stays None if startup failed (in which case
# /fetch returns 503 until the container is restarted).
_browser: Browser | None = None


class FetchRequest(BaseModel):
    url: HttpUrl


def _is_disallowed_host(hostname: str) -> bool:
    """Reject localhost and any host that resolves to a non-public IP.

    Catches literal localhost names without a DNS lookup, then resolves
    the hostname and rejects if ANY returned address is private /
    loopback / link-local / reserved / multicast / unspecified. A host
    with mixed public + private records is treated as disallowed (safe
    default for SSRF prevention).
    """
    if not hostname:
        return True
    if (
        hostname in {"localhost", "ip6-localhost", "ip6-loopback"}
        or hostname.endswith(".local")
    ):
        return True
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Unresolvable here -> let Playwright surface a clearer nav error.
        return False
    for _family, _stype, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def _validate_url(raw: str) -> str:
    """Validate scheme + hostname and run the SSRF check. Raises
    HTTPException(400) on rejection so the caller gets a clean error
    instead of a pydantic 422 or a Playwright timeout."""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="url must be http(s)")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="url must have a hostname")
    if _is_disallowed_host(parsed.hostname):
        raise HTTPException(
            status_code=400,
            detail="url resolves to a disallowed (private/loopback) address",
        )
    return raw


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Launch one chromium browser on startup, reuse it for every
    request, close it on shutdown."""
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


app = FastAPI(title="jobapp-fetcher", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/fetch")
async def fetch(req: FetchRequest) -> dict:
    url = _validate_url(str(req.url))
    if _browser is None:
        raise HTTPException(status_code=503, detail="browser not ready")
    # Fresh context per request so cookies/storage don't leak between
    # calls. The context is closed in the finally block below.
    context = await _browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()
    try:
        resp = await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
        # page.goto returns None if navigation was cancelled before any
        # response arrived — surface as a 502 rather than a 200 with null.
        if resp is None:
            raise HTTPException(status_code=502, detail="navigation returned no response")
        html = await page.content()
        return {
            "html": html,
            "status": resp.status,
            "url": page.url,
        }
    except PlaywrightError as e:
        raise HTTPException(status_code=502, detail=f"playwright error: {e}")
    finally:
        await page.close()
        await context.close()