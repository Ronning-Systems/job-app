# Project Conventions — JobSync

This file captures project-specific conventions and preferences the user
has stated explicitly. Read this before taking action that might conflict.

## Deploy workflow — use `deploy.sh`, not Cloud Build

**Always deploy by running `./deploy.sh` from the project root.** Do not
use `gcloud builds submit` even though `cloudbuild.yaml` exists.

Reasons:
- The user prefers local Docker builds (`docker build --platform linux/amd64`)
  + `docker push` + `gcloud run deploy` rather than Cloud Build to avoid
  Cloud Build costs and keep iteration in one script.
- `deploy.sh` is the canonical deploy entrypoint — it builds, pushes,
  deploys, and migrates traffic in one shot.

To redeploy after edits:

```bash
git add -A && git commit -m "<message>" && git push origin main
./deploy.sh
```

`deploy.sh` deploys with `--no-traffic` and then migrates with
`gcloud run services update-traffic --to-latest` itself, so no extra
traffic-migration step is required.

If you ever need to migrate traffic independently (e.g., to roll back
without rebuilding), the script `migrate-traffic.sh` exists but it had
a `describe-traffic` bug fixed in commit history — the simple working
incantation is:

```bash
gcloud run services update-traffic job-app --region=us-west1 --to-latest
```

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
- **README/agent docs**: `docs/superpowers/` contains design notes for
  the original auth migration and Cloud Run setup — useful context for
  understanding architectural choices but treat as historical, not
  prescriptive.
