# Cloud Run Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy JobSync to Google Cloud Run with Cloud SQL PostgreSQL and Ollama Cloud LLM.

**Architecture:** Single Cloud Run service serves FastAPI backend (API routes + merged MCP route + static frontend), connects to Cloud SQL PostgreSQL for persistence and Ollama Cloud for LLM inference. Secrets managed via GCP Secret Manager.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, PostgreSQL (psycopg2), Cloud SQL Auth Proxy, Docker, Cloud Build, Cloud Run

---

### Task 1: Switch database layer to configurable PostgreSQL/SQLite

The `models.py` file currently hardcodes `sqlite:///./job_tracker.db`. We need it to use PostgreSQL when `DATABASE_URL` is set (production) and fall back to SQLite (local dev). Also add connection pooling for PostgreSQL.

**Files:**
- Modify: `backend/models.py:89-103`

- [ ] **Step 1: Update `backend/models.py` — replace hardcoded SQLite with configurable engine**

Replace lines 89-103 (the database setup section) with:

```python
import os

# Database setup - PostgreSQL for production, SQLite for local dev
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Production: PostgreSQL via Cloud SQL
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
else:
    # Local dev: SQLite fallback
    engine = create_engine(
        "sqlite:///./job_tracker.db",
        connect_args={"check_same_thread": False},
    )
```

Keep the existing `Base`, `SessionLocal`, `init_db`, and `get_db` exactly as they are — they don't change.

- [ ] **Step 2: Add PostgreSQL dependencies to `backend/requirements.txt`**

Append these two lines to the end of `backend/requirements.txt`:

```
psycopg2-binary
cloud-sql-python-connector[pg8000]
```

The full file should now be:

```
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy==2.0.25
pydantic==2.5.3
httpx==0.26.0
beautifulsoup4==4.12.3
python-multipart==0.0.6
python-dotenv==1.0.0
pypdf2==3.0.1
python-docx==0.8.11
pdfplumber==0.10.3
psycopg2-binary
cloud-sql-python-connector[pg8000]
```

- [ ] **Step 3: Verify local dev still works**

Run: `cd backend && source venv/bin/activate && pip install psycopg2-binary 'cloud-sql-python-connector[pg8000]' && python -c "from models import engine; print(f'Engine: {engine.url}')"`

Expected: `Engine: sqlite:///./job_tracker.db` (because no `DATABASE_URL` is set)

- [ ] **Step 4: Commit**

```bash
git add backend/models.py backend/requirements.txt
git commit -m "feat: add configurable DATABASE_URL with PostgreSQL support and SQLite fallback"
```

---

### Task 2: Add API key authentication to Ollama calls

Both `agents.py` and `job_parser.py` make HTTP calls to the Ollama API endpoint. For Ollama Cloud, we need to send a `Bearer` token in the `Authorization` header. Add `MODEL_API_KEY` env var support.

**Files:**
- Modify: `backend/agents.py:92-122` (OllamaAgent class)
- Modify: `backend/job_parser.py:10-62` (OllamaClient class)

- [ ] **Step 1: Update `backend/agents.py` — add API key to OllamaAgent**

In the `OllamaAgent.__init__` method (around line 95-99), add `self.api_key`:

```python
class OllamaAgent:
    """Base class for Ollama-powered agents"""

    def __init__(self):
        self.base_url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip(
            "/"
        )
        self.model = os.getenv("MODEL_AGENTS", "llama3.2:latest")
        self.api_key = os.getenv("MODEL_API_KEY", "")
        self.timeout = 120.0
```

In the `OllamaAgent.generate` method (around line 102-122), add headers with auth:

```python
    async def generate(
        self, prompt: str, system: Optional[str] = None, temperature: float = 0.3
    ) -> str:
        """Generate text using Ollama"""
        url = f"{self.base_url}/api/generate"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 32000},
        }

        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
```

- [ ] **Step 2: Update `backend/job_parser.py` — add API key to OllamaClient**

In the `OllamaClient.__init__` method (around line 13-18), add `self.api_key`:

```python
class OllamaClient:
    """Client for calling Ollama API"""

    def __init__(self):
        self.base_url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip('/')
        self.model = os.getenv("MODEL_PARSING") or os.getenv("OLLAMA_MODEL") or "llama3.2:latest"
        self.api_key = os.getenv("MODEL_API_KEY", "")
        print(f"[OllamaClient] Using model: {self.model} at {self.base_url}")
```

In the `OllamaClient.parse_job_description` method (around line 48-62), add headers to the HTTP call:

```python
    async def parse_job_description(self, text: str) -> Dict[str, Any]:
        """Use Ollama to parse job description into structured data"""

        prompt = f"""You are a Job Description Archiver Agent. Extract structured information from the following job posting.

Analyze the job description and return a JSON object with these exact fields:
- company: The company name (string, required)
- position: The job title/position (string, required)
- location: Job location including city, state, and remote status (string)
- salary: Salary range or compensation info (string)
- remote: One of "Remote", "Hybrid", "On-site", or "Not specified"
- description: Cleaned job description text (string)
- requirements: Object with "must_have" (list of strings) and "nice_to_have" (list of strings)
- responsibilities: List of key responsibilities (list of strings)
- keywords: Technical skills and keywords found (list of strings)
- credentials: Required degrees, certifications, years of experience (list of strings)

IMPORTANT: Return ONLY valid JSON. No markdown, no explanation, just the JSON object.

Job Description:
---
{text[:8000]}
---

JSON Output:"""

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response_text = ""
        try:
            print(f"[OllamaClient] Sending request to {self.base_url}/api/generate with model {self.model}")
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 2000
                        }
                    },
                    headers=headers
                )
```

Note: Only the `headers=headers` parameter is added to the `client.post()` call. Everything else in the method stays the same.

- [ ] **Step 3: Verify imports still work**

Run: `cd backend && source venv/bin/activate && python -c "from agents import agent_service; from job_parser import JobParser; print('Imports OK')"`

Expected: `Imports OK` (no errors)

- [ ] **Step 4: Commit**

```bash
git add backend/agents.py backend/job_parser.py
git commit -m "feat: add MODEL_API_KEY auth header for Ollama Cloud support"
```

---

### Task 3: Merge MCP server routes into backend and add static file serving

The MCP server (`mcp_server.py`) has two endpoints: `POST /fetch-job` and `GET /health`. We need to merge these into `main.py` and add static file serving for the frontend.

**Files:**
- Modify: `backend/main.py` (add routes + static serving)
- No changes to: `mcp_server.py` (kept for local dev)

- [ ] **Step 1: Add imports to `backend/main.py`**

After the existing imports (around line 1-7), add these imports:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
```

Add them alongside the existing FastAPI imports — put `StaticFiles` and `FileResponse` with the existing `from fastapi import ...` line, or add a new import line right after it.

- [ ] **Step 2: Remove MCP_SERVER_URL and fetch_job_from_mcp from `backend/main.py`**

Delete the following lines (around 131-171):

```python
# MCP Server configuration
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080")
```

And delete the entire `fetch_url_directly` and `fetch_job_from_mcp` functions (lines 152-171). These are no longer needed since the MCP routes are being merged directly into the backend.

- [ ] **Step 3: Add merged MCP route and static file serving to `backend/main.py`**

Before the `if __name__ == "__main__":` block at the bottom of the file, add these new routes:

```python
# Merged MCP routes (previously mcp_server.py)


@app.post("/api/fetch-job")
async def fetch_job(request: dict):
    """
    Fetch job details from a URL.
    Supports LinkedIn, Indeed, and generic job boards.
    """
    url = request.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            html_content = response.text

        parser = JobParser()
        job_data = await parser.parse_from_html(html_content, url)
        return job_data

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied (403) when fetching URL. The website may block automated requests: {url}",
            )
        elif e.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Job posting not found (404): {url}",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch URL (HTTP {e.response.status_code}): {str(e)}",
            )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Network error when fetching URL: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing job: {str(e)}")


# Static file serving and SPA catch-all
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_index():
    """Serve the main frontend page"""
    return FileResponse("static/index.html")
```

- [ ] **Step 4: Add SPA catch-all route**

Right after the `serve_index` route above, add a catch-all for SPA routing. This must be the LAST route defined (before `if __name__`):

```python
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Catch-all for SPA routing — return index.html for any non-API path"""
    # Only serve index.html for non-API routes
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse("static/index.html")
```

- [ ] **Step 5: Copy `index.html` to `static/` directory**

```bash
mkdir -p static
cp index.html static/index.html
```

This creates the `static/` directory that the Dockerfile and FastAPI will serve from. The original `index.html` at the project root is kept for local dev.

- [ ] **Step 6: Update `.gitignore` to exclude the static copy**

Add `/static/index.html` to `.gitignore` since it's a build artifact (copied from the root `index.html`). Or alternatively, add a note that `static/index.html` is generated. Actually — let's just commit it since it's identical to the source. Skip this step.

- [ ] **Step 7: Verify the app starts locally**

Run: `cd backend && source venv/bin/activate && python -c "from main import app; print('App loaded OK')"`

Expected: `App loaded OK` (no errors)

- [ ] **Step 8: Commit**

```bash
git add backend/main.py static/
git commit -m "feat: merge MCP routes into backend and add static file serving"
```

---

### Task 4: Create Dockerfile and .dockerignore

Create the container build configuration for Cloud Run.

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY agents/ ./agents/
COPY static/ ./static/

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Create `.dockerignore`**

```
.env
.git
.gitignore
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
docs/
resumes/
cover_letters/
job_description_*.md
app-requirements.md
README.md
resume-review-skill.md
```

- [ ] **Step 3: Test Docker build locally**

```bash
docker build -t jobsync-test .
```

Expected: Build completes successfully with no errors.

- [ ] **Step 4: Test the container runs**

```bash
docker run -p 8080:8080 -e MODEL_ENDPOINT=http://host.docker.internal:11434 jobsync-test
```

Then in another terminal: `curl http://localhost:8080/api/health`

Expected: `{"status":"healthy","service":"job-tracker-api"}`

Note: The health endpoint will work without DATABASE_URL (uses SQLite in the container) and without a running Ollama instance.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: add Dockerfile and .dockerignore for Cloud Run deployment"
```

---

### Task 5: Create Cloud Build deployment configuration

Create `cloudbuild.yaml` for automated deployment to Cloud Run.

**Files:**
- Create: `cloudbuild.yaml`

- [ ] **Step 1: Create `cloudbuild.yaml`**

```yaml
substitutions:
  _REGION: us-central1

steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/jobsync', '.']

  # Push the container image to Artifact Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/jobsync']

  # Deploy container image to Cloud Run
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
      - 'MODEL_ENDPOINT=https://api.olama.ai,MODEL_PARSING=minimax-m2.5:cloud,MODEL_AGENTS=glm-5:cloud,MODEL_COMMANDS=kimi-k2.5:cloud'
      - '--set-secrets'
      - 'DATABASE_URL=jobsync-database-url:latest,MODEL_API_KEY=jobsync-model-api-key:latest'

images:
  - 'gcr.io/$PROJECT_ID/jobsync'
```

- [ ] **Step 2: Create a deployment script for one-time GCP setup**

Create `deploy-setup.sh` with the prerequisite commands:

```bash
#!/bin/bash
# One-time setup script for JobSync Cloud Run deployment
# Run this once before deploying with Cloud Build

set -e

PROJECT_ID=$(gcloud config get-value project)
REGION=${1:-us-central1}

echo "Setting up JobSync infrastructure in project: $PROJECT_ID, region: $REGION"
echo "==========================================================================="

# Enable required APIs
echo "1. Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com

# Create Cloud SQL instance
echo "2. Creating Cloud SQL instance (this takes a few minutes)..."
gcloud sql instances create jobsync-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=$REGION || echo "Instance may already exist, continuing..."

# Create database
echo "3. Creating database..."
gcloud sql databases create jobsync --instance=jobsync-db || echo "Database may already exist, continuing..."

# Prompt for password
echo "4. Creating database user..."
read -s -p "Enter password for jobsync DB user: " DB_PASSWORD
echo ""
gcloud sql users create jobsync --instance=jobsync-db --password="$DB_PASSWORD" || echo "User may already exist, continuing..."

# Get the Cloud SQL connection name
CONNECTION_NAME=$(gcloud sql instances describe jobsync-db --format="value(connectionName)")

# Create Secret Manager secrets
echo "5. Creating secrets..."
echo -n "postgresql+psycopg2://jobsync:${DB_PASSWORD}@/jobsync?host=/cloudsql/${CONNECTION_NAME}" | \
  gcloud secrets create jobsync-database-url --data-file=- || echo "Secret may already exist, continuing..."

read -s -p "Enter Ollama Cloud API key: " OLLAMA_API_KEY
echo ""
echo -n "$OLLAMA_API_KEY" | \
  gcloud secrets create jobsync-model-api-key --data-file=- || echo "Secret may already exist, continuing..."

# Get project number for IAM
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Grant Cloud Run access to secrets
echo "6. Granting IAM access to secrets..."
gcloud secrets add-iam-policy-binding jobsync-database-url \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding jobsync-model-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

echo ""
echo "Setup complete! Now deploy with:"
echo "  gcloud builds submit --config=cloudbuild.yaml"
```

- [ ] **Step 3: Make the script executable**

```bash
chmod +x deploy-setup.sh
```

- [ ] **Step 4: Commit**

```bash
git add cloudbuild.yaml deploy-setup.sh
git commit -m "feat: add Cloud Build config and GCP setup script"
```

---

### Task 6: Update .gitignore for deployment artifacts

The `.gitignore` needs to cover the new `static/` build artifact and Docker-related files.

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Update `.gitignore`**

Add these lines to `.gitignore`:

```
# Deployment
static/index.html
*.db
*.log
```

Note: `static/index.html` is tracked because it's a copy of `index.html` — but we may want it tracked. Actually, let's track it since it's needed for Docker builds. Skip adding `static/index.html` to gitignore. Only add the Docker/deployment related ignores.

The final `.gitignore` should be:

```
/.DS_Store
/.env
/.ruff_cache
*.db
*.log
.DS_Store
__pycache__/
*.pyc
backend/venv/
mcp_server/venv/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: update .gitignore for deployment"
```

---

### Task 7: End-to-end verification

Test the complete deployment pipeline locally before pushing to GCP.

- [ ] **Step 1: Verify local development still works with SQLite**

```bash
cd backend && source venv/bin/activate
python -c "
from models import engine, init_db, SessionLocal
init_db()
db = SessionLocal()
print(f'Database engine: {engine.url}')
print('SQLite fallback works correctly')
db.close()
"
```

Expected: `Database engine: sqlite:///./job_tracker.db` and no errors.

- [ ] **Step 2: Verify DATABASE_URL switching works**

```bash
cd backend && source venv/bin/activate
DATABASE_URL="postgresql+psycopg2://test:test@/testdb?host=/cloudsql/test:test:test" python -c "
from models import engine
print(f'Engine URL: {engine.url}')
"
```

Expected: `Engine URL: postgresql+psycopg2://test:test@/testdb?host=/cloudsql/test:test:test`

- [ ] **Step 3: Verify Docker build succeeds**

```bash
docker build -t jobsync-test .
```

Expected: Build completes with `Successfully tagged jobsync-test:latest`.

- [ ] **Step 4: Verify container starts and health endpoint works**

```bash
docker run -d --name jobsync-verify -p 8080:8080 jobsync-test
sleep 3
curl http://localhost:8080/api/health
docker stop jobsync-verify && docker rm jobsync-verify
```

Expected: `{"status":"healthy","service":"job-tracker-api"}`

- [ ] **Step 5: Verify frontend serving works**

```bash
docker run -d --name jobsync-frontend -p 8080:8080 jobsync-test
sleep 3
curl -s http://localhost:8080/ | head -5
docker stop jobsync-frontend && docker rm jobsync-frontend
```

Expected: First 5 lines of `index.html` (HTML doctype and head tag).

- [ ] **Step 6: Commit any remaining fixes**

If any fixes were needed during verification, commit them:
```bash
git add -A
git commit -m "fix: adjustments from end-to-end verification"
```