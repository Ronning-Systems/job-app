# job-app sidecars

This directory holds the source code for the in-process sidecars the
Joblign backend depends on at runtime. Each subdirectory is a
self-contained service with its own Dockerfile, source, and tests.

## Layout

- `fetcher/` — URL-rendering sidecar (Playwright + chromium). No
  auth; on the internal `proxy` Docker network only. Called by
  `backend/main.py:POST /api/jobs/from-url` as the fallback for
  JS-heavy job boards (LinkedIn, Indeed) that block plain httpx.
  Healthz: `GET /healthz` (unauthenticated).
- `autoapply/` — Auto-apply sidecar (Playwright + chromium + HMAC).
  Drives external job-board forms on the user's behalf. Auth:
  `X-AutoApply-Signature: hex(hmac_sha256(secret, body + "." + ts))`.
  Healthz: `GET /healthz` (unauthenticated).

## Build contract

Each subdirectory is a Docker build context. The my-stack deploy
script (`deploy-patrick-mini.sh`) is responsible for:
  1. Copying the subdirectory to `/srv/jobapp/<name>-img/` on
     patrick-mini (rsync)
  2. Running `docker buildx build --platform linux/amd64 --tag
     jobapp-<name>:${IMAGE_TAG} --load .` in that directory
  3. Bringing up the service via the job-app compose project
     (`docker-compose.yml` in this repo's root)

Image names: `jobapp-fetcher:${IMAGE_TAG}` and
`jobapp-auto-apply:${IMAGE_TAG}`. Pin `IMAGE_TAG` to match the main
job-app image so a single deploy swaps the whole stack atomically.

## Tests

Run from the job-app repo root:

```bash
/opt/data/.venv-autoapply/bin/python -m pytest \
  sidecars/autoapply/tests/ -v
```

The URL-rendering fetcher does not yet have unit tests; its
behaviour is exercised end-to-end against real job boards via the
container on patrick-mini (not from this repo).

## Adding a new sidecar

1. Create `sidecars/<name>/` with `Dockerfile`, `<name>.py`, and
   (if applicable) `tests/`.
2. Add a service entry to `docker-compose.yml` in the job-app repo
   root. Internal-only: no Traefik labels, `proxy` network only,
   read-only rootfs + tmpfs `/tmp` + no-new-privileges + cap_drop ALL.
3. If the sidecar needs auth from joblign, document the scheme in
   `sidecars/<name>/README.md` (or this README if a pattern emerges).
4. Add a probe in `backend/health.py` so `/api/health/system`
   knows about it.
5. Add the image build step + service bring-up to
   `my-stack/deploy-patrick-mini.sh` (this script is still the
   orchestrator, even though it now delegates the *what* to
   job-app).
