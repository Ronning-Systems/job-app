# JobSync - Job Application Tracker

A personal job application tracking system with AI-powered job description parsing, resume generation, and ATS analysis. Deployed on Google Cloud Run.

## Features

### Job Tracking
- Track jobs through 9 stages: Saved, Applied, Phone Screen, Interview, Executive Call, Offered, Rejected, Withdrawn, Closed
- Add jobs via URL (auto-fetches and parses job details) or plain text
- Store job descriptions, requirements, and extracted keywords
- History tracking with automatic stage change logging

### Resume Management
- Create and manage multiple resumes (example and template types)
- ATS optimization via ATS Expert Agent
- Technical fit analysis via Technical Hiring Manager Agent
- Resume generation tailored to specific jobs using example resumes and templates

### AI Agents
- **Job Description Parser**: Parses job postings from URLs or text via Ollama Cloud
- **ATS Expert Agent**: Analyzes resumes for ATS compatibility and keyword matching
- **Technical Hiring Manager Agent**: Evaluates technical fit against job requirements
- **Resume Generator Agent**: Creates tailored resumes using example resumes and templates

## Architecture

```
┌──────────────────────────────────────────────┐
│              Google Cloud Run                 │
│                                              │
│  ┌──────────────────────────────────┐        │
│  │     Cloud Run Service           │        │
│  │     (job-app)                   │        │
│  │                                 │        │
│  │  /api/*       → backend routes  │        │
│  │  /            → index.html      │        │
│  │  /api/fetch-job → URL fetching │        │
│  │                                 │        │
│  │  Env vars:                      │        │
│  │    DATABASE_URL  → Cloud SQL    │        │
│  │    MODEL_ENDPOINT → Ollama Cloud│       │
│  │    OLLAMA_API_KEY (secret)      │        │
│  └──────────┬──────────┬──────────┘        │
│             │          │                    │
│  ┌──────────▼──┐  ┌───▼──────────────┐   │
│  │ Cloud SQL   │  │ Secret Manager     │   │
│  │ PostgreSQL  │  │ (DB creds, API key) │   │
│  └─────────────┘  └────────────────────┘   │
└──────────────────────────────────────────────┘
         │
         │ HTTPS (MODEL_ENDPOINT)
         │
┌────────▼────────────────────────────────────┐
│  Ollama Cloud                                │
│  (models: minimax-m2.5, glm-5, kimi-k2.5)   │
└─────────────────────────────────────────────┘
```

### Tech Stack
- **Backend**: Python 3.11, FastAPI, SQLAlchemy
- **Database**: PostgreSQL (Cloud SQL) in production, SQLite for local dev
- **Frontend**: Single-page HTML/CSS/JS (no build step)
- **AI**: Ollama Cloud API (minimax-m2.5, glm-5, kimi-k2.5)
- **Deployment**: Docker, Google Cloud Run, Cloud Build

### API Endpoints

#### Jobs
- `POST /api/jobs` - Create a new job (from URL or text)
- `GET /api/jobs` - List all jobs (with optional stage/search filters)
- `GET /api/jobs/{id}` - Get job details
- `PUT /api/jobs/{id}` - Update job
- `DELETE /api/jobs/{id}` - Delete job
- `PATCH /api/jobs/{id}/stage` - Update application stage

#### Resumes
- `POST /api/resumes/base` - Upload a base resume (example or template)
- `GET /api/resumes/base` - List base resumes
- `DELETE /api/resumes/base/{id}` - Delete a base resume

#### Agents
- `POST /api/agents/ats-analysis` - ATS analysis
- `POST /api/agents/technical-fit` - Technical fit analysis
- `POST /api/jobs/{id}/generate-resume` - Generate a tailored resume

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

## Deployment (Cloud Run)

### One-time setup

```bash
# 1. Enable GCP APIs
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com

# 2. Create Cloud SQL instance
gcloud sql instances create jobsync-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-west1

# 3. Create database and user
gcloud sql databases create jobsync --instance=jobsync-db
gcloud sql users create jobsync --instance=jobsync-db --password=<PASSWORD>

# 4. Create secrets
echo -n "postgresql+psycopg2://jobsync:<PASSWORD>@/jobsync?host=/cloudsql/<CONNECTION_NAME>" | \
  gcloud secrets create DATABASE_URL --data-file=-
echo -n "<OLLAMA_API_KEY>" | \
  gcloud secrets create OLLAMA_API_KEY --data-file=-

# 5. Grant Cloud Run access to secrets
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format="value(projectNumber)")
gcloud secrets add-iam-policy-binding DATABASE_URL \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding OLLAMA_API_KEY \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Deploy

```bash
# Option 1: Cloud Build (automated)
gcloud builds submit --config=cloudbuild.yaml

# Option 2: One-shot deploy from source
gcloud run deploy job-app \
  --source . \
  --region us-west1 \
  --allow-unauthenticated \
  --add-cloudsql-instances ronning-systems:us-west1:ronning-systems-jobapp \
  --set-env-vars "MODEL_ENDPOINT=https://ollama.com,MODEL_PARSING=minimax-m2.5:cloud,MODEL_AGENTS=glm-5:cloud,MODEL_COMMANDS=kimi-k2.5:cloud" \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,OLLAMA_API_KEY=OLLAMA_API_KEY:latest"
```

## Project Structure

```
job-app/
├── index.html                 # Frontend SPA
├── Dockerfile                 # Container build config
├── cloudbuild.yaml            # Cloud Build CI/CD pipeline
├── deploy-setup.sh            # One-time GCP setup script
├── .dockerignore              # Docker build exclusions
│
├── backend/
│   ├── main.py                # FastAPI application (API + static serving)
│   ├── models.py             # SQLAlchemy models (PostgreSQL/SQLite)
│   ├── job_parser.py           # Job description parser (Ollama-powered)
│   ├── agents.py              # Agent service (ATS, tech fit, resume gen)
│   └── requirements.txt       # Python dependencies
│
├── agents/                    # Agent prompt definitions
│   ├── ats-expert.md
│   ├── resume-generator.md
│   ├── hr-professional.md
│   └── tech-hiring-manager.md
│
├── static/                   # Static frontend files (Docker build target)
│   └── index.html
│
└── mcp_server.py              # Standalone MCP server (local dev only)
```

## License

MIT License