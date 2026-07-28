# Custom URL-rendering fetcher image for Joblign.
#
# Built on the host every deploy by deploy-patrick-mini.sh (same pattern
# as job-app, secrets-fetcher, and traefik-custom). The base image is the
# official Playwright Python image, which has chromium + its OS deps
# pre-installed — we add the playwright Python package (pinned to match
# the base image's bundled browser binaries) plus the FastAPI/uvicorn/httpx
# runtime on top.
#
# Build context (assembled on the host at /srv/jobapp/fetcher-img):
#   fetcher.py        the FastAPI server
#   Dockerfile        this file
#
# The container is internal-only: it runs on the `proxy` Docker network
# and is reachable as http://fetcher:8080 from the jobapp container. It
# is NOT published through Traefik.
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# FastAPI + uvicorn + httpx + playwright. The playwright package MUST be
# pinned to match the base image's pre-installed browser binaries (v1.45.0);
# a mismatched version would trigger a "browser binary not found" error.
# The base image ships the OS deps + chromium binaries but NOT the Python
# package itself, so we install it here.
RUN pip install --no-cache-dir \
      fastapi==0.111.0 \
      "uvicorn[standard]==0.30.1" \
      httpx==0.27.0 \
      playwright==1.45.0

COPY fetcher.py /app/fetcher.py

# Chromium runs as a non-root user without sandbox unless --no-sandbox is
# passed (it is, in fetcher.py). The container is internal-only and the
# read-only + cap_drop posture comes from the compose stack, not here.
EXPOSE 8080
CMD ["uvicorn", "fetcher:app", "--host", "0.0.0.0", "--port", "8080"]