# JobSync Cloud Run Deployment Design

**Date:** 2026-06-12
**Status:** Approved

## Overview

Deploy JobSync to Google Cloud Run with Cloud SQL PostgreSQL and Ollama Cloud for LLM inference. No home infrastructure dependencies — the app is fully cloud-native.

## Architecture

```
┌──────────────────────────────────────────────┐
│              Google Cloud                     │
│                                               │
│  ┌──────────────────────────────────┐        │
│  │     Cloud Run Service            │        │
│  │     (jobsync)                    │        │
│  │                                  │        │
│  │  /api/*    → backend routes      │        │
│  │  /         → index.html          │        │
│  │  /api/fetch-job → (merged MCP)   │        │
│  │                                  │        │
│  │  Env vars:                       │        │
│  │    DATABASE_URL → Cloud SQL      │        │
│  │    MODEL_ENDPOINT → Ollama Cloud │        │
│  │    MODEL_PARSING/AGENTS/COMMANDS │        │
│  └──────┬──────────────┬───────────┘        │
│         │              │                     │
│  ┌──────▼──────┐  ┌───▼──────────────┐     │
│  │ Cloud SQL   │  │ Secret Manager    │     │
│  │ PostgreSQL  │  │ (DB creds, API    │     │
│  └─────────────┘  │  keys)            │     │
│                    └───────────────────┘     │
└──────────────────────────────────────────────┘
         │
         │ HTTPS (MODEL_ENDPOINT)
         │
┌────────▼────────────────────────────────────┐
│  Ollama Cloud                                │
│  (models: minimax-m2.5, glm-5, kimi-k2.5)   │
└──────────────────────────────────────────────┘
```

## Components

### 1. Cloud Run Service (`jobsync`)

Single container serving:
- **API routes** (`/api/*`) — FastAPI backend
- **Static frontend** (`/`) — `index.html`
- **Merged MCP endpoint** (`/api/fetch-job`) — URL fetching + HTML parsing, previously a separate service on port 8080

Port: `8080` (Cloud Run convention)

### 2. Cloud SQL PostgreSQL (`jobsync-db`)

- Persistent database replacing SQLite
- Connected via Unix socket (`/cloudsql/PROJECT:REGION:jobsync-db`)
- Built-in Cloud SQL Auth Proxy — no VPC connector needed
- Automatic backups, TLS, IAM auth available

### 3. Ollama Cloud (LLM)

- Replaces local Ollama/LM Studio
- Models configured via environment variables (same as current `.env`)
- API key stored in Secret Manager
- No home infrastructure dependency

### 4. Secret Manager

Two secrets:
1. `jobsync-database-url` — full PostgreSQL connection string
2. `ollama-api-key` — Ollama Cloud API key

Cloud Run accesses these via IAM — no credentials in container image or `.env`.

## Code Changes

### `backend/models.py`

Replace hardcoded SQLite connection with configurable `DATABASE_URL`:

```python
import os

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Production: PostgreSQL via Cloud SQL
    engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=10)
else:
    # Local dev: SQLite fallback
    engine = create_engine(
        "sqlite:///./job_tracker.db",
        connect_args={"check_same_thread": False}
    )
```

New dependencies: `psycopg2-binary`, `cloud-sql-python-connector[pg8000]`

### `backend/main.py`

1. **Merge MCP routes** — add `/api/fetch-job` endpoint from `mcp_server.py`. Remove `MCP_SERVER_URL` env var and `fetch_job_from_mcp()` function. The backend calls its own parser directly.

2. **Static file serving** — mount `index.html` from `static/` directory:
```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    return FileResponse("static/index.html")
```

3. **SPA catch-all** — any non-API route returns `index.html`

### `backend/agents.py`

Add API key header to Ollama calls:

```python
class OllamaAgent:
    def __init__(self):
        self.base_url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("MODEL_AGENTS", "llama3.2:latest")
        self.api_key = os.getenv("OLLAMA_API_KEY", "")
        self.timeout = 120.0

    async def generate(self, prompt, system=None, temperature=0.3):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # ... existing request logic with headers=headers
```

Same change in `job_parser.py` for parsing calls.

### `backend/requirements.txt`

Add:
```
psycopg2-binary
```

Note: `cloud-sql-python-connector[pg8000]` was originally planned but removed — Cloud Run connects to Cloud SQL via Unix socket (`host=/cloudsql/...` in the connection string) which psycopg2 handles directly. The connector is only needed for IAM auth, which can be added later if required.

### `mcp_server.py`

No changes — kept for local development, not included in Docker image.

## Docker

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY agents/ ./agents/
COPY index.html ./static/

ENV PYTHONPATH=/app/backend
EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### `.dockerignore`

```
.env
.git
__pycache__
*.pyc
backend/venv/
backend/job_tracker.db
backend/job_tracker.old*.db
backend/backend.log
mcp_server/venv/
mcp_server.py
start_*.sh
setup.sh
*.egg-info
.DS_Store
.claude/
```

## Deployment

### `cloudbuild.yaml`

```yaml
substitutions:
  _REGION: us-central1

steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/jobsync', '.']

  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/jobsync']

  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'jobsync'
      - '--image=gcr.io/$PROJECT_ID/jobsync'
      - '--region=${_REGION}'
      - '--platform=managed'
      - '--allow-unauthenticated'
      - '--add-cloudsql-instances'
      - '${PROJECT_ID}:${_REGION}:jobsync-db'
      - '--set-env-vars'
      - 'MODEL_ENDPOINT=https://ollama.com,MODEL_PARSING=minimax-m2.5:cloud,MODEL_AGENTS=glm-5:cloud,MODEL_COMMANDS=kimi-k2.5:cloud'
      - '--set-secrets'
      - 'DATABASE_URL=jobsync-database-url:latest,OLLAMA_API_KEY=ollama-api-key:latest'

images:
  - 'gcr.io/$PROJECT_ID/jobsync'
```

### Prerequisites (one-time setup)

1. **Enable APIs**: Cloud Run, Cloud SQL Admin, Cloud Build, Secret Manager, Artifact Registry
2. **Create Cloud SQL instance**:
   ```bash
   gcloud sql instances create jobsync-db \
     --database-version=POSTGRES_15 \
     --tier=db-f1-micro \
     --region=us-central1
   ```
3. **Create database and user**:
   ```bash
   gcloud sql databases create jobsync --instance=jobsync-db
   gcloud sql users create jobsync --instance=jobsync-db --password=<PASSWORD>
   ```
4. **Create Secret Manager secrets**:
   ```bash
   echo -n "postgresql+psycopg2://jobsync:PASSWORD@/jobsync?host=/cloudsql/PROJECT:us-central1:jobsync-db" | \
     gcloud secrets create jobsync-database-url --data-file=-
   echo -n "<OLLAMA_API_KEY>" | \
     gcloud secrets create ollama-api-key --data-file=-
   ```
5. **Grant Cloud Run access to secrets**:
   ```bash
   gcloud secrets add-iam-policy-binding jobsync-database-url \
     --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```
6. **Deploy**:
   ```bash
   gcloud builds submit --config=cloudbuild.yaml
   ```

## Environment Variables

| Variable | Source | Example |
|----------|--------|---------|
| `DATABASE_URL` | Secret Manager | `postgresql+psycopg2://jobsync:PASS@/jobsync?host=/cloudsql/PROJECT:REGION:jobsync-db` |
| `MODEL_ENDPOINT` | Direct env var | `https://ollama.com` |
| `MODEL_PARSING` | Direct env var | `minimax-m2.5:cloud` |
| `MODEL_AGENTS` | Direct env var | `glm-5:cloud` |
| `MODEL_COMMANDS` | Direct env var | `kimi-k2.5:cloud` |
| `OLLAMA_API_KEY` | Secret Manager | (Ollama Cloud API key) |

## Local Development

Local development continues to work as-is:
- No `DATABASE_URL` → falls back to SQLite
- No `OLLAMA_API_KEY` → assumes local Ollama (no auth needed)
- `mcp_server.py` and `start_*.sh` remain for local use
- `.env` file stays in `.gitignore`

## Files Changed Summary

| File | Change |
|------|--------|
| `backend/models.py` | Configurable `DATABASE_URL`, PostgreSQL + Cloud SQL support, connection pooling |
| `backend/main.py` | Merge MCP `/fetch-job` route, add static file serving, SPA catch-all |
| `backend/agents.py` | Add `OLLAMA_API_KEY` auth header to Ollama calls |
| `backend/job_parser.py` | Add `OLLAMA_API_KEY` auth header to Ollama calls |
| `backend/requirements.txt` | Add `psycopg2-binary`, `cloud-sql-python-connector[pg8000]` |
| `index.html` | Move to `static/index.html` (or serve from project root) |
| New: `Dockerfile` | Python 3.11 slim, deps install, uvicorn on 8080 |
| New: `.dockerignore` | Exclude venvs, .env, db files, scripts |
| New: `cloudbuild.yaml` | Cloud Build + Cloud Run deploy pipeline |