# Project Conventions — Joblign

This file captures project-specific conventions and preferences the user
has stated explicitly. Read this before taking action that might conflict.

## Branding

- The app is **Joblign**, tagline **"Get aligned for success"**.
- The legacy name "JobSync" no longer appears in user-visible text. The
  only intentional "jobsync" string left in the codebase is the Auth0 API
  audience identifier `https://jobsync/api` — it is an opaque identifier
  registered in the Auth0 dashboard, not a brand string. Renaming it
  requires reconfiguring the Auth0 dashboard API identifier and breaks
  all active sessions. **Do not** mass-replace `jobsync` without keeping
  this exception in mind.
- Brand assets live in `static/`: `joblign-logo.{png,webp}` (header) and
  `joblign-favicon.{png,webp}` (favicon). Served at the app root via
  explicit routes in `backend/main.py` (the SPA catch-all would otherwise
  return index.html for these paths).

## Deploy workflow — owned by `my-stack`, not this repo

**This repo (`job-app`) is the application source. It does not contain
the deploy orchestrator.** The canonical deploys are
`my-stack/deploy-patrick-mini.sh` (prod) and
`my-stack/deploy-patrick-mini-test.sh` (test). Both build the image
on `patrick-mini` via `docker buildx` and bring the env up with
`docker compose -p <name> up -d`.

Before 2026-08-03 the test deploy was a `--test` flag on the prod
script. The flag was removed because the shared code path let a
broken test deploy clobber the prod Traefik routing (Pitfall #25).
Now the test env has its own Traefik instance, its own compose
network (`proxy-test`, separate from prod's `proxy`), and its own
deploy script. See `my-stack/AGENTS.md` for the full architecture
notes.

### Hotfix workflow — commit and push to main for small prod bugs

For small production bug fixes (one or two file changes, no schema
or migration), **commit and push directly to `main`** so the next
prod deploy picks them up. Do not wait for a separate PR or test
deploy — the goal is to unblock production.

- Commit with a clear `fix(...):` prefix and a one-line body
  explaining the symptom (so the next person reading the log knows
  what was broken and why the change was safe).
- Push to `origin main` immediately after the commit.
- If `main` has diverged (e.g. commits ahead on a feature branch),
  cherry-pick the fix onto `main` rather than merging — keep the
  hotfix commit isolated and easy to revert.
- For anything touching schema, auth, or deploy plumbing, stop and
  ask; those go through the normal sync → my-stack → test → prod
  path.

### Test-env network topology

The test stack attaches to TWO Docker networks:

- `proxy-test` — created by `my-stack/compose/network-test.yml`.
  Carries the test Traefik + all 5 test services. Test-side DNS
  isolation: api-test cannot resolve prod's services by name.
- `proxy` — the SHARED prod network. Only `secrets-fetcher-test`
  attaches here, because it needs to reach the shared Vault
  container at `http://vault:8200`. The vault token file at
  `/srv/jobapp/vault/jobapp.token` is also shared between envs
  (chmod 644, root-owned, written by both deploy scripts).

Locked in by `backend/tests/test_compose.py::test_uses_external_proxy_network`.

To redeploy after edits to `job-app`:

```bash
# 1. Sync app changes into my-stack (from my-stack/):
git fetch job-app
git merge --allow-unrelated-histories -X theirs job-app/main
git checkout HEAD -- AGENTS.md .gitignore   # restore ops-only overrides
git commit -m "Sync app code from job-app@<sha>"

# 2a. Deploy prod (from my-stack/):
./deploy-patrick-mini.sh

# 2b. OR deploy test (from my-stack/):
./deploy-patrick-mini-test.sh
```

### Cloud Run is retired

GCP / Cloud Run is **no longer a deploy target**. The Cloud Run scripts
(`deploy.sh`, `deploy-setup.sh`, `migrate-traffic.sh`, `rollback.sh`,
`status.sh`), `cloudbuild.yaml`, and `DEPLOYMENT.md` have been removed
from this repo. If they resurface after a sync, delete them again —
they are stale. The canonical deploy paths are
`deploy-patrick-mini.sh` (prod) and `deploy-patrick-mini-test.sh`
(test) in `my-stack`, full stop. See `my-stack/AGENTS.md` for the
authoritative ops conventions.

### Production URL

- Public (prod): `https://joblign.ronning.systems` (Traefik + Let's Encrypt)
- Tailscale-only fallback (prod): `https://job-app.patrick-mini.ts.net`
- Tailscale-only (test): `https://joblign.test.ronning.systems:9444/` — **must be
  on the tailnet to reach** (test Traefik binds ONLY to the Tailscale
  interface at the host level, on non-standard port :9444 because
  the prod Traefik owns :80/:443 on this host; no public DNS, no
  Let's Encrypt). Resolves via Tailscale split-DNS to `patrick-mini`'s
  Tailscale IP.

## Database migrations — Alembic

Schema migrations are managed by **Alembic** (config in `backend/alembic.ini`,
migrations in `backend/alembic/versions/`). The app runs migrations
automatically on startup via `models.init_db()` → `alembic upgrade head`.

- **Adding a column/table**: change the model in `backend/models.py`, then
  generate a migration with `cd backend && python3 -m alembic revision
  --autogenerate -m "<description>"`. Review the generated file (autogenerate
  is not perfect — check for dropped columns it shouldn't touch), commit it,
  redeploy. `init_db` applies it on next startup.
- **Existing DB that predates Alembic**: `init_db` detects the absence of the
  `alembic_version` table and `stamp`s the DB at the current head (marks the
  schema as current without trying to recreate existing tables), so the
  production DB was a one-time `stamp` — done. Subsequent deploys just
  `upgrade head`.
- **Never hand-write `ALTER TABLE`** in `_run_migrations`-style blocks —
  the old hand-rolled migration system was removed (it had a DATETIME-vs-
  TIMESTAMP dialect bug that broke the prod deploy for 5 runs). Use Alembic.
- The baseline revision is `453348d81a12` (matches the schema as of the
  2026-07-25 redesign). The production DB is stamped at that revision.

## Other notes

- **Single template per user**: `BaseResume` table enforces one row with
  `resume_type='template'` per user. Upload via Resume Settings replaces
  any existing template atomically. The frontend confirms before save.
- **Example resumes are voice/tone only**: don't try to extract formatting
  from them. The template DOCX is the only formatting source.
- **Globally unique public_job_id**: jobs have a short alphanumeric code
  (e.g. `JOB-A7K2M9P3`) shown on the home screen and detail modal.
- **Structured resume editor** uses per-atom editable cards derived from
  the template's captured style atoms. Empty structured tab means the
  resume was generated before template atoms existed — Regenerate once
  to populate both tabs from a single LLM call.
- **README/agent docs**: `docs/superpowers/` contains design notes. The
  appliance-convention spec (`docs/appliance-spec.md` in my-stack)
  describes the current architecture; the older
  (`2026-07-18-portainer-deploy-design.md`) is historical only.

## New tables, agents, and routes (2026-07-25 redesign)

- **New tables** (in `backend/models.py`):
  - `BaseCoverLetter` — example cover letters for voice/tone (v1 has no
    template/DOCX variant; `letter_type='example'` only).
  - `GeneratedCoverLetter` — one row per job; mirrors `GeneratedResume`
    with versioned `revisions` (each carries the feedback that produced it).
  - `ArtifactScore` — persisted ATS + industry-panel scores for BOTH
    resumes and cover letters. Polymorphic via `artifact_type`
    (`'resume'` | `'cover_letter'`) + soft-FK `artifact_id`; no DB-level
    FK so deleting an artifact doesn't orphan-block. Index on
    `(artifact_type, artifact_id, score_type)`.
- **New agent prompts** (in `agents/`):
  - `cover-letter-generator.md` — generation + revision in one prompt
    (revision mode preserves unchanged content; do not fabricate beyond
    the resume).
  - `industry-panel.md` — 4 personas (engineering/technical leader,
    product leader, domain expert, recruiter) in a single LLM call;
    returns per-persona scores + composite + strengths/gaps + a
    `recommendation` ∈ {strong yes, yes, maybe, no, strong no}.
  - `ats-expert.md` — extended to return structured JSON scores
    (overall/parseability/keyword_match/search_relevance, 0-10) consumed
    by `ArtifactScore`.
- **URL-only entry:** `POST /api/jobs/from-url` fetches → parses →
  creates a job in one call. Tries httpx first, falls back to the
  fetcher sidecar (Playwright+chromium) for blocked boards (LinkedIn,
  Indeed).
- **`FETCHER_URL` env var** (default `http://fetcher:8080`): the
  headless-browser sidecar. The sidecar source lives in
  `my-stack/appliances/fetcher/` (the single source of truth — the
  my-stack deploy script's step 6 enforces this with a drift check
  that fails the build if `sidecars/fetcher/` re-appears in this
  repo). Internal-only; not exposed by Traefik.
- **Parser extensions** in `backend/job_parser.py`:
  `_extract_pay_range`, `_extract_application_deadline`, improved
  `_extract_credentials`. Structured pay range (`pay_range_min/max`,
  `pay_currency`, `pay_period`) + `application_deadline` are stored on
  the `Job` and are sortable; no deadline reminders/badges in v1.
- **Sort-by-attribute:** `GET /api/jobs?sort=company|position|location|
  stage|applied_date|deadline|pay|created&order=asc|desc`.

## Sidecars (added 2026-07-28, refactored 2026-08-24 to appliance convention)

- **Source location:** sidecar source (Dockerfile + .py + manifest)
  lives in `my-stack/appliances/<name>/`, NOT in this repo. As of
  2026-08-24, the single source of truth is the appliance convention
  under `my-stack/appliances/<name>/` (Dockerfile + source + manifest).
  The my-stack deploy script (`deploy-patrick-mini.sh` step 6) enforces
  this with a drift check that fails the build if a `sidecars/<name>/`
  subtree re-appears in either repo.
- **Layout:** `my-stack/appliances/<name>/{Dockerfile,<name>.py,
  appliance.md[,requirements.txt,tests/]}` — every appliance is a
  directory with the Dockerfile inside (not a flat-file tree).
- **Build:** the my-stack deploy script rsyncs each appliance's tree
  to patrick-mini and runs `docker buildx build`. Image names are
  `ronning/<name>:${IMAGE_TAG}`.
- **Runtime:** declared in this repo's `docker-compose.yml`
  (prod) and `docker-compose.test.yml` (test) as services on
  the external `proxy` network. The my-stack deploy script
  brings them up as part of the `jobapp` (prod) or `jobapp-test`
  (test) compose project. The test compose uses `-test`
  suffixes on every service + container_name so prod and test
  can run in parallel on the same `proxy` network without DNS
  collisions.
- **Auth:** the fetcher has no auth (callable only from the internal
  proxy network).
- **Health:** every sidecar exposes `GET /healthz` (unauth).
  `GET /api/health/system` on the api service probes every
  sidecar + postgres + ollama and returns one 200/503 the
  deploy script polls. Adding a new sidecar = add a Dockerfile +
  service in compose + probe in `backend/health.py`.

## Health rollup endpoint

`GET /api/health/system` (added 2026-07-28) runs every registered
probe concurrently and returns 200 with `{"overall":"ok", ...}` if
all components are healthy, or 503 with `{"overall":"degraded", ...}`
if any are down. The shallow `GET /api/health` endpoint stays for
backward compat with the Traefik healthcheck.

Probes live in `backend/health.py` and are registered in the
`PROBES` dict there. Each probe returns `(status, detail)`. Adding
a new sidecar = add `_probe_<name>` + an entry in `PROBES`.