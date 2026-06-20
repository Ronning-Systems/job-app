# Deployment Guide

This guide covers both local development (localhost) and Cloud Run deployment.

---

## Local Development (localhost)

For development and testing without Google Cloud costs.

### Quick Start

```bash
# Build Docker image and run locally
./run_local_docker.sh
```

**Access the application:**
- Frontend: http://localhost:8765
- API docs: http://localhost:8765/docs
- Health check: http://localhost:8765/api/health

### What the script does

1. Creates `.env` from `.env.example` (if needed)
2. Configures SQLite database (no PostgreSQL needed)
3. Builds Docker image locally (`job-app-local`)
4. Runs container on port 8765
5. Automatically removes container on stop (`--rm` flag)

### Environment

- **Database**: SQLite (file-based, no setup required)
- **LLM**: Local Ollama via `host.docker.internal` or Ollama Cloud
- **Auth**: Requires Auth0 configuration for login

### Configuration

Set environment variables before running:

```bash
# Use local Ollama (running on your Mac)
export MODEL_ENDPOINT=http://host.docker.internal:11434
export MODEL_PARSING=llama3.2:latest
export MODEL_AGENTS=llama3.2:latest
export MODEL_GENERATION=llama3.2:latest

# Or use Ollama Cloud
export MODEL_ENDPOINT=https://ollama.com
export MODEL_PARSING=minimax-m2.5:cloud
export MODEL_AGENTS=glm-5:cloud
export MODEL_GENERATION=kimi-k2.5:cloud
export OLLAMA_API_KEY=your-api-key

# Auth0 (required for authentication)
export AUTH0_DOMAIN=your-tenant.us.auth0.com
export AUTH0_AUDIENCE=https://jobsync/api

# Run the script
./run_local_docker.sh
```

### Container Management

```bash
# View logs
docker logs job-app-local

# Follow logs in real-time
docker logs -f job-app-local

# Stop the container
docker stop job-app-local

# View running containers
docker ps
```

### Custom Port

```bash
PORT=9000 ./run_local_docker.sh
```

---

## Cloud Run Deployment

```bash
# Build and deploy (no traffic migration)
./deploy.sh

# Review the deployment, then migrate traffic
./migrate-traffic.sh

# Check status anytime
./status.sh

# Rollback if needed
./rollback.sh
```

## Scripts Overview

### `deploy.sh` - Build and Deploy
Builds the Docker image locally, pushes to Container Registry, and deploys to Cloud Run.

**Key features:**
- ✅ Builds Docker image on your machine (not Cloud Build)
- ✅ Deploys with `--no-traffic` flag (safe deployment)
- ✅ Does NOT automatically migrate traffic (manual approval required)
- ✅ Shows rollback instructions on completion

**Environment variables:**
```bash
export REGION=us-west1           # Default: us-west1
export SERVICE_NAME=job-app      # Default: job-app
export DB_INSTANCE=...           # Default: ronning-systems:us-west1:ronning-systems-jobapp
./deploy.sh
```

### `migrate-traffic.sh` - Migrate Traffic
Shifts 100% of traffic to the latest revision. Run this after verifying the deployment works.

```bash
./migrate-traffic.sh
```

### `rollback.sh` - Rollback
Reverts traffic to the previous revision.

```bash
./rollback.sh
```

### `status.sh` - View Status
Shows current service status, traffic distribution, and revision history.

```bash
./status.sh
```

## Deployment Workflow

### Standard Deployment

1. **Deploy new revision** (no traffic impact):
   ```bash
   ./deploy.sh
   ```

2. **Test the new revision** before migrating traffic:
   ```bash
   # Get the service URL
   SERVICE_URL=$(gcloud run services describe job-app --region us-west1 --format="value(status.url)")
   
   # Test the health endpoint
   curl "${SERVICE_URL}/api/health"
   ```

3. **Migrate traffic** once verified:
   ```bash
   ./migrate-traffic.sh
   ```

### Emergency Rollback

If something goes wrong after traffic migration:

```bash
./rollback.sh
```

This reverts 100% of traffic to the previous revision.

## Manual gcloud Commands

The scripts wrap these underlying commands:

### Build and push image locally
```bash
IMAGE_NAME="gcr.io/$(gcloud config get-value project)/job-app"
docker build -t "${IMAGE_NAME}" .
docker push "${IMAGE_NAME}"
```

### Deploy without traffic
```bash
gcloud run deploy job-app \
  --image "${IMAGE_NAME}" \
  --region us-west1 \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances ronning-systems:us-west1:ronning-systems-jobapp \
  --set-env-vars "MODEL_ENDPOINT=https://ollama.com,..." \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,OLLAMA_API_KEY=OLLAMA_API_KEY:latest" \
  --no-traffic
```

### Migrate traffic
```bash
gcloud run services update-traffic job-app \
  --region us-west1 \
  --to-latest
```

### Rollback to specific revision
```bash
gcloud run services update-traffic job-app \
  --region us-west1 \
  --to-revisions <revision-name>=100
```

## Prerequisites

- Docker installed and running
- gcloud CLI installed and authenticated
- Project configured: `gcloud config set project <PROJECT_ID>`
- Cloud SQL instance and secrets already set up (run `deploy-setup.sh` once if needed)

## Cost Comparison

| Method | Cost |
|--------|------|
| Cloud Build (previous) | ~$0.03/min + build minutes |
| Local build + deploy | $0 (only Cloud Run usage charges) |

## Troubleshooting

### Docker build fails
Ensure Docker daemon is running:
```bash
docker info
```

### Authentication errors
Re-authenticate with gcloud:
```bash
gcloud auth login
gcloud auth configure-docker
```

### Permission denied pushing image
Ensure you have Artifact Registry Writer role:
```bash
gcloud projects add-iam-policy-binding $(gcloud config get-value project) \
  --member="user:$(gcloud config get-value account)" \
  --role="roles/artifactregistry.writer"
```

### Can't access secrets
Verify Secret Manager access:
```bash
gcloud secrets list
gcloud secrets get-iam-policy DATABASE_URL
```
