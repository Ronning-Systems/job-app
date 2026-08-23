# Joblign — Get aligned for success

A personal job application tracking system with AI-powered job description
parsing, resume generation, and ATS analysis. Track applications, generate
tailored cover letters, and align your resume to each role.

> **Branding:** The app name is **Joblign**, tagline **"Get aligned for
> success"**. The legacy name "JobSync" no longer appears in user-visible
> text. The opaque Auth0 API identifier `https://jobsync/api` is kept
> intentionally (renaming it requires reconfiguring the Auth0 dashboard
> and breaks active sessions).

## Features

### Job Tracking
- Track jobs through 9 stages: Saved, Applied, Phone Screen, Interview, Executive Call, Offered, Rejected, Withdrawn, Closed
- Add jobs via URL (auto-fetches and parses job details) or plain text
- Store job descriptions, requirements, and extracted keywords
- Structured pay range + application deadline parsed from postings (sortable; no deadline reminders in v1)
- Sort-by-attribute on the jobs list (company, position, location, stage, applied_date, deadline, pay, created)
- History tracking with automatic stage change logging

### Resume Management
- Create and manage multiple resumes (example and template types)
- ATS optimization via ATS Expert Agent
- Technical fit analysis via Technical Hiring Manager Agent
- Industry panel review (4 personas, single LLM call) via Industry Panel Agent
- Resume generation tailored to specific jobs using example resumes and templates

### Cover Letter Management
- Upload example cover letters (voice/tone reference for the generator)
- Generate tailored cover letters grounded in the candidate's resume and the job description
- Revision via text feedback (appends a versioned revision)
- ATS + industry panel scoring for cover letters too

### AI Agents
- **Job Description Parser**: Parses job postings from URLs or text via Ollama Cloud
- **ATS Expert Agent**: Analyzes resumes or cover letters for ATS compatibility and keyword matching (structured scores persisted)
- **Technical Hiring Manager Agent**: Evaluates technical fit against job requirements
- **Industry Panel Agent**: Simulates 4 reviewers (engineering/technical leader, product leader, domain expert, recruiter) in a single call; returns composite + per-persona scores + recommendation
- **Resume Generator Agent**: Creates tailored resumes using example resumes and templates
- **Cover Letter Generator Agent**: Creates tailored cover letters grounded in the resume; revises on feedback

## Architecture

```
┌────────────────────────────────────────────────────────┐
│            patrick-mini (homelab, Tailscale)            │
│                                                        │
│  ┌──────────────────────────────────────────┐          │
│  │  Traefik v3 (HTTPS, Let's Encrypt)       │          │
│  │  joblign.ronning.systems → jobapp:8080   │          │
│  └──────────────────────┬───────────────────┘          │
│                         │                              │
│  ┌──────────────────────▼───────────────────┐          │
│  │  Joblign app container (job-app image)   │          │
│  │  uvicorn backend.main:app --port 8080    │          │
│  │                                          │          │
│  │  /api/*       → backend routes           │          │
│  │  /            → static/index.html        │          │
│  │  /api/jobs/from-url → URL fetch + parse  │          │
│  │                                          │          │
│  │  Env from Vault (secret materializer):   │          │
│  │    DATABASE_URL  → postgres service      │          │
│  │    MODEL_ENDPOINT → Ollama Cloud         │          │
│  │    AUTH0_*  → Auth0                      │          │
│  │    FETCHER_URL → fetcher sidecar         │          │
│  └──────────┬─────────────────┬────────────┘          │
│             │                 │                        │
│  ┌──────────▼─────┐  ┌───────▼──────────────┐         │
│  │  Postgres 16   │  │  Vault (secrets KV)  │         │
│  │  (jobapp PG)    │  │  jobapp/prod path    │         │
│  │  tables:       │  └──────────────────────┘         │
│  │   users, jobs, │                                    │
│  │   job_applications,                              │
│  │   base_resumes,                                  │
│  │   generated_resumes,                             │
│  │   base_cover_letters,                           │
│  │   generated_cover_letters,                      │
│  │   artifact_scores                                │
│  └────────────────┘         ┌──────────────────┐    │
│                              │  fetcher sidecar  │    │
│                              │  (Playwright+     │    │
│                              │   chromium)       │    │
│                              │  internal-only,   │    │
│                              │  not in Traefik   │    │
│                              └──────────────────┘    │
└────────────────────────────────────────────────────────┘
          │
          │ HTTPS (MODEL_ENDPOINT)
          │
┌────────▼────────────────────────────────────────────────┐
│  Ollama Cloud                                          │
│  (models: minimax-m2.5, glm-5, kimi-k2.5)              │
└────────────────────────────────────────────────────────┘
```

### Tech Stack
- **Backend**: Python 3.11, FastAPI, SQLAlchemy
- **Database**: PostgreSQL 16 in production, SQLite for local dev
- **Frontend**: Single-page HTML/CSS/JS (no build step)
- **AI**: Ollama Cloud API (minimax-m2.5, glm-5, kimi-k2.5)
- **Deployment**: Docker, self-hosted on `patrick-mini` via the
  `my-stack/deploy-patrick-mini.sh` orchestrator; Traefik v3 reverse proxy
  with automatic Let's Encrypt TLS; Vault for secrets. **Cloud Run / GCP
  is no longer a deploy target** — the Cloud Run scripts, `cloudbuild.yaml`,
  and `DEPLOYMENT.md` have been removed.

### API Endpoints

#### Jobs
- `POST /api/jobs` - Create a new job (from text)
- `POST /api/jobs/from-url` - Fetch, parse, and create a job from a URL in one call (httpx first, fetcher sidecar fallback)
- `GET /api/jobs` - List all jobs (with optional stage/search filters + sort/order)
- `GET /api/jobs/{id}` - Get job details
- `PUT /api/jobs/{id}` - Update job
- `DELETE /api/jobs/{id}` - Delete job
- `PATCH /api/jobs/{id}/stage` - Update application stage

#### Resumes
- `POST /api/resumes/base` - Upload a base resume (example or template)
- `GET /api/resumes/base` - List base resumes
- `DELETE /api/resumes/base/{id}` - Delete a base resume
- `POST /api/jobs/{id}/generate-resume` - Generate a tailored resume (background + progress poll)
- `GET /api/jobs/{id}/generate-resume/status` - Poll resume generation status
- `POST /api/jobs/{id}/revise-resume` - Revise a generated resume from feedback

#### Cover Letters
- `POST /api/cover-letters/base` - Upload an example cover letter (voice/tone reference)
- `GET /api/cover-letters/base` - List base cover letters
- `DELETE /api/cover-letters/base/{id}` - Delete a base cover letter
- `POST /api/jobs/{id}/generate-cover-letter` - Generate a cover letter (background + progress poll)
- `GET /api/jobs/{id}/generate-cover-letter/status` - Poll cover letter generation status
- `POST /api/jobs/{id}/revise-cover-letter` - Revise a cover letter from feedback (appends a versioned revision)
- `DELETE /api/jobs/{id}/cover-letter` - Delete a job's generated cover letter

#### Scoring (ATS + Industry Panel)
- `POST /api/jobs/{id}/resumes/{resume_id}/score-ats` - ATS-score a resume
- `POST /api/jobs/{id}/resumes/{resume_id}/score-industry-panel` - Industry-panel-score a resume
- `POST /api/jobs/{id}/cover-letters/{cl_id}/score-ats` - ATS-score a cover letter
- `POST /api/jobs/{id}/cover-letters/{cl_id}/score-industry-panel` - Industry-panel-score a cover letter
- `GET /api/jobs/{id}/scores` - Latest ATS + industry-panel scores for a job's resume/cover letter

#### Agents
- `POST /api/agents/ats-analysis` - ATS analysis
- `POST /api/agents/technical-fit` - Technical fit analysis
- `POST /api/agents/generate-resume` - Generate a tailored resume

#### Other
- `POST /api/fetch-job` - Fetch and parse a job posting from a URL
- `GET /api/health` - Health check
- `GET /api/stats` - Dashboard statistics

## Local Development

### Prerequisites
- Python 3.9+
- [Ollama](https://ollama.ai) (for local LLM inference)

### Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running Locally

```bash
# Backend (with local SQLite and Ollama)
cd backend
source venv/bin/activate
python main.py
# Runs on http://localhost:8000

# Frontend is served by the backend at http://localhost:8000
```

Without `DATABASE_URL` set, the app falls back to SQLite. Without `OLLAMA_API_KEY` set, it assumes local Ollama (no auth required).

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | SQLite fallback |
| `MODEL_ENDPOINT` | LLM API endpoint | `http://localhost:11434` |
| `MODEL_PARSING` | Model for job parsing | `llama3.2:latest` |
| `MODEL_AGENTS` | Model for agent analysis | `llama3.2:latest` |
| `MODEL_COMMANDS` | Model for commands | `llama3.2:latest` |
| `OLLAMA_API_KEY` | API key for Ollama Cloud | (none — local dev) |
| `AUTH0_DOMAIN` | Auth0 tenant domain | (empty = local dev bypass) |
| `AUTH0_AUDIENCE` | Auth0 API identifier (opaque, do not rename) | `https://jobsync/api` |
| `CORS_ORIGIN` | Comma-separated allowed origins | `http://localhost:8765,https://joblign.ronning.systems` |
| `FETCHER_URL` | Headless-browser sidecar for blocked job boards (Playwright+chromium, owned by my-stack, internal-only) | `http://fetcher:8080` |

## Deployment

Production deploys to `patrick-mini` (homelab server on Tailscale) using the
`my-stack/deploy-patrick-mini.sh` orchestrator. The deploy path is owned by
the **`my-stack`** repo — see `my-stack/AGENTS.md` for the canonical workflow.

### Routine deploy

```bash
# from my-stack/ (not job-app/)
git add -A && git commit -m "<message>" && git push origin main
./deploy-patrick-mini.sh
```

The script builds the image on `patrick-mini` via `docker buildx`, renders
the Traefik config and compose files with `envsubst`, and brings up the
five stacks (network → traefik → fetcher → vault → jobapp) with `docker compose`.

### Production URL

- `https://joblign.ronning.systems` — public, via Traefik + Let's Encrypt
- `https://job-app.patrick-mini.ts.net` — Tailscale-only fallback

### Rollback

```bash
git checkout <sha> -- portainer/
./deploy-patrick-mini.sh
```

## Project Structure

```
job-app/
├── static/                    # Frontend SPA + brand assets
│   ├── index.html             # Single-page frontend
│   ├── joblign-logo.png       # Joblign logo (header)
│   ├── joblign-logo.webp      #   WebP variant
│   ├── joblign-favicon.png    # Favicon
│   └── joblign-favicon.webp   #   WebP variant
├── Dockerfile                 # Container build config (patrick-mini target)
├── .dockerignore              # Docker build exclusions
│
├── backend/
│   ├── main.py                # FastAPI application (API + static serving)
│   ├── auth.py                # Auth0 JWT validation
│   ├── models.py              # SQLAlchemy models (PostgreSQL/SQLite)
│   ├── job_parser.py          # Job description parser (Ollama-powered)
│   ├── agents.py              # Agent service (ATS, tech fit, resume gen)
│   └── requirements.txt        # Python dependencies
│
├── agents/                    # Agent prompt definitions
│   ├── ats-expert.md
│   ├── resume-generator.md
│   ├── technical-hiring-manager.md
│   ├── cover-letter-generator.md   # Cover letter generation + revision
│   └── industry-panel.md           # 4-persona industry panel scoring
│
├── mcp_server.py              # Standalone MCP server (local dev only)
├── run_local.sh               # Local dev server (SQLite, hot reload)
├── run_local_docker.sh        # Local Docker dev (joblign-local image)
└── setup.sh                   # First-time venv setup
```

## License

MIT License