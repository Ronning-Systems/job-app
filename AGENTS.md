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
the deploy orchestrator.** The canonical deploy is
`my-stack/deploy-patrick-mini.sh`, which builds the image on
`patrick-mini` via `docker buildx`, renders the Traefik config and the
five compose stacks with `envsubst`, and brings them up with
`docker compose -p <name> up -d`.

To redeploy after edits to `job-app`:

```bash
# 1. Sync app changes into my-stack (from my-stack/):
git fetch job-app
git merge --allow-unrelated-histories -X theirs job-app/main
git checkout HEAD -- AGENTS.md .gitignore   # restore ops-only overrides
git commit -m "Sync app code from job-app@<sha>"

# 2. Deploy (from my-stack/):
./deploy-patrick-mini.sh
```

### Cloud Run is retired

GCP / Cloud Run is **no longer a deploy target**. The Cloud Run scripts
(`deploy.sh`, `deploy-setup.sh`, `migrate-traffic.sh`, `rollback.sh`,
`status.sh`), `cloudbuild.yaml`, and `DEPLOYMENT.md` have been removed
from this repo. If they resurface after a sync, delete them again —
they are stale. The canonical deploy path is `deploy-patrick-mini.sh`
in `my-stack`, full stop. See `my-stack/AGENTS.md` for the authoritative
ops conventions.

### Production URL

- Public: `https://joblign.ronning.systems` (Traefik + Let's Encrypt)
- Tailscale-only fallback: `https://job-app.patrick-mini.ts.net`

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

## Billing / Stripe (my-stack only)

Stripe integration lives in this repo (routes under `/api/billing/*`,
client UI in `static/index.html`, logic in `backend/billing.py`). The
**only** deploy target that wires Stripe in is `my-stack/deploy-patrick-mini.sh`,
which materializes secrets from Vault into the app container. Cloud Run
is retired (see above) — do not reintroduce a Cloud Run deploy path.

- **Plans**: `free` (3 generations/month) and `pro` (50/month). Caps are
  configurable via `BILLING_FREE_CAP` / `BILLING_PRO_CAP` env vars; price
  label via `BILLING_PRO_PRICE_LABEL`. All counted as resume-generation
  events against `usage_events` (one per successful generation).
- **Grandfathering**: any user that existed at the time the `plan` column
  was first added gets `plan='pro', plan_grandfathered=TRUE` permanently
  — no card required. Gated by a `schema_migrations` row so it's
  idempotent across redeploys.
- **Disable billing locally**: leave `STRIPE_SECRET_KEY` unset in `.env`.
  All billing routes return 503; cap enforcement is skipped (every user
  is treated as effectively pro) so dev isn't blocked.
- **Webhook events handled**: `customer.subscription.{created,updated,
  deleted,trial_will_end}`, `checkout.session.completed`,
  `invoice.payment_{succeeded,failed}`. Subscription status maps to
  `user.plan` on every event; grandfathered users are never overridden.
- **Cap check** is at `POST /api/jobs/{id}/generate-resume` (returns 402
  with `{code, plan, cap, used}` so the SPA can open the paywall). The
  UsageEvent row is only written on success (in the background task
  after `db.commit()`).

### Wiring Stripe secrets on patrick-mini

The Stripe secrets must be added to Vault at `jobapp/prod` (or
`jobapp/test` for the test env):

```bash
# On patrick-mini, with vault CLI:
vault kv put jobapp/prod \
  STRIPE_SECRET_KEY=sk_live_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  STRIPE_PUBLISHABLE_KEY=pk_live_... \
  STRIPE_PRICE_ID_PRO=price_... \
  PUBLIC_SITE_URL=https://joblign.ronning.systems
```

After adding/updating secrets, restart the `app` (and `secrets-fetcher`
if it caches them) in the `jobapp` compose project so the app picks up
the new env files. See `my-stack/AGENTS.md` for the compose layout.

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
  Portainer / patrick-mini deploy spec
  (`2026-07-18-portainer-deploy-design.md`) describes the architecture
  still in use today. Older Cloud Run specs/plans are historical only.

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
  headless-browser sidecar. The sidecar itself is owned by `my-stack`
  (`portainer/stacks/fetcher.yml`), not this repo — this repo just calls
  it. Internal-only; not exposed by Traefik. The 4-stack deploy became 5
  (network → traefik → fetcher → vault → jobapp).
- **Parser extensions** in `backend/job_parser.py`:
  `_extract_pay_range`, `_extract_application_deadline`, improved
  `_extract_credentials`. Structured pay range (`pay_range_min/max`,
  `pay_currency`, `pay_period`) + `application_deadline` are stored on
  the `Job` and are sortable; no deadline reminders/badges in v1.
- **Sort-by-attribute:** `GET /api/jobs?sort=company|position|location|
  stage|applied_date|deadline|pay|created&order=asc|desc`.