"""Component health probes and the /api/health/system rollup.

The deploy script on patrick-mini polls one endpoint
(``GET /api/health/system``) to know whether the job-app stack is
healthy enough to call "deployed". This module:

  - defines one probe per job-app-owned dependency
  - exposes a single ``/api/health/system`` route that runs all
    probes concurrently and returns one 200/503 with a per-component
    status map

Adding a new sidecar = adding a probe function here and registering
it in ``PROBES``. The shape of the response is stable: the set of
component keys is the contract the deploy script parses.

Probes return ``(status, detail)``:
  - status: ``"ok"`` | ``"down"``
  - detail: ``None`` on ok, error string on down

The endpoint is intentionally synchronous-style async (httpx +
asyncio.gather). Probes have a 2-5s timeout each so a hung
sidecar can't block the whole rollup.
"""
from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

# NOTE: sqlalchemy + SessionLocal are imported lazily inside
# _probe_postgres so the test suite can run without sqlalchemy
# installed in the test venv. The health module is imported at
# process start by main.py, so the lazy import only fires when
# the rollup endpoint is actually hit (and only for the postgres
# probe).


router = APIRouter()


# ---------------------------------------------------------------------------
# Generic HTTP probe
# ---------------------------------------------------------------------------


async def _http_probe(url: str, timeout: float = 2.0) -> tuple[str, str | None]:
    """Probe an HTTP healthz-style endpoint. Returns (status, detail).

    The probe never raises — all exceptions are caught and turned into
    a ``("down", "<ExceptionType>: <msg>")`` tuple. The rollup endpoint
    catches exceptions too, but having the probe be exception-safe
    means a bug in asyncio.gather handling can't crash the endpoint.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
        if 200 <= r.status_code < 300:
            return "ok", None
        return "down", f"HTTP {r.status_code}"
    except Exception as e:
        return "down", f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Component probes
# ---------------------------------------------------------------------------


async def _probe_fetcher() -> tuple[str, str | None]:
    """URL-rendering sidecar. No auth; healthz is unauthenticated."""
    url = os.getenv("FETCHER_URL", "http://fetcher:8080").rstrip("/")
    return await _http_probe(url + "/healthz")


async def _probe_autoapply() -> tuple[str, str | None]:
    """Auto-apply sidecar. HMAC-authed for write routes, but healthz
    is unauthenticated like the fetcher's."""
    url = os.getenv("AUTOAPPLY_URL", "http://auto-apply:8081").rstrip("/")
    return await _http_probe(url + "/healthz")


async def _probe_postgres() -> tuple[str, str | None]:
    """``SELECT 1`` against the live DB. Returns (status, detail).

    SessionLocal is imported lazily so the test suite can mock the
    whole DB layer (via ``patch("health._probe_postgres", ...)``)
    without needing sqlalchemy installed in the test venv.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    from models import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return "ok", None
    except SQLAlchemyError as e:
        return "down", f"{type(e).__name__}: {e}"
    except Exception as e:
        # Catch-all so a DB-driver or network error never crashes the
        # rollup endpoint.
        return "down", f"{type(e).__name__}: {e}"
    finally:
        db.close()


async def _probe_ollama() -> tuple[str, str | None]:
    """Ollama /api/tags. Slightly longer timeout because Ollama cold
    starts can be slow on a small box."""
    url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip("/")
    return await _http_probe(url + "/api/tags", timeout=5.0)


# ---------------------------------------------------------------------------
# Rollup
# ---------------------------------------------------------------------------


PROBES: dict[str, Callable[[], Awaitable[tuple[str, str | None]]]] = {
    "fetcher": _probe_fetcher,
    "autoapply": _probe_autoapply,
    "postgres": _probe_postgres,
    "ollama": _probe_ollama,
}


@router.get("/api/health/system")
async def health_system() -> JSONResponse:
    """Run every probe concurrently and return the rollup.

    Returns HTTP 200 if every component is ok, HTTP 503 if any are
    down. The body always lists every component (stable key set;
    the deploy script's log parsers depend on this) so partial
    degradations are visible in the body, not just the status code.

    The probe functions are looked up via ``globals()`` at call
    time (rather than via the ``PROBES`` dict) so unit tests can
    ``patch("health._probe_xxx", ...)`` and have the change take
    effect for the duration of the request.
    """
    names = list(PROBES.keys())
    # Resolve probes through globals() so monkeypatching
    # ``health._probe_xxx`` actually replaces the called function.
    # If a probe is missing from globals (e.g. due to a typo in
    # PROBES), AttributeError is caught by gather's
    # return_exceptions=True and surfaces as "down".
    results = await asyncio.gather(
        *(globals()[f"_probe_{name}"]() for name in names),
        return_exceptions=True,
    )

    components: dict[str, dict] = {}
    overall = "ok"
    for name, result in zip(names, results):
        if isinstance(result, BaseException):
            # asyncio.gather(..., return_exceptions=True) wraps raised
            # exceptions. Treat any exception as "down" with a
            # human-readable detail string.
            components[name] = {
                "status": "down",
                "detail": f"{type(result).__name__}: {result}",
            }
            overall = "degraded"
            continue
        status, detail = result
        components[name] = {"status": status, "detail": detail}
        if status != "ok":
            overall = "degraded"

    status_code = 200 if overall == "ok" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "overall": overall,
            "components": components,
        },
    )
