# Custom auto-apply sidecar image for Joblign.
#
# Sibling to jobapp-fetcher. Same Playwright base image (chromium +
# its OS deps are pre-installed), so we add the playwright Python
# package pinned to the base image's bundled browser binaries
# (v1.45.0) plus the FastAPI/uvicorn/httpx runtime on top.
#
# Build context (assembled on the host at /srv/jobapp/autoapply-img):
#   autoapply.py       the FastAPI server (this repo)
#   Dockerfile         this file (renamed from autoapply.Dockerfile
#                      on the remote so `docker buildx build .` picks
#                      it up — same pattern as the fetcher)
#
# The container is internal-only: it runs on the `proxy` Docker
# network and is reachable as http://auto-apply:8081 from the
# jobapp container. It is NOT published through Traefik.
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# FastAPI + uvicorn + httpx + playwright. The playwright package MUST
# be pinned to match the base image's pre-installed browser binaries
# (v1.45.0); a mismatched version would trigger a "browser binary
# not found" error. The base image ships the OS deps + chromium
# binaries but NOT the Python package itself, so we install it here.
RUN pip install --no-cache-dir \
      fastapi==0.111.0 \
      "uvicorn[standard]==0.30.1" \
      httpx==0.27.0 \
      playwright==1.45.0

COPY autoapply.py /app/autoapply.py

# Chromium runs as a non-root user without sandbox unless --no-sandbox
# is passed (it is, in autoapply.py). The container is internal-only
# and the read-only + cap_drop posture comes from the compose stack,
# not here.
EXPOSE 8081
CMD ["uvicorn", "autoapply:app", "--host", "0.0.0.0", "--port", "8081"]
