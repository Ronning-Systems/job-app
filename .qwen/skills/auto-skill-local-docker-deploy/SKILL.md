---
name: local-docker-deploy
description: Create repeatable local Docker deployment scripts to avoid remote build costs
source: auto-skill
extracted_at: '2026-06-20T16:35:13.116Z'
---

# Local Docker Deployment for Joblign

> **Branding note (2026-07-25):** The app was renamed JobSync → **Joblign**
> (tagline "Get aligned for success"). The legacy Cloud Run / GCP deployment
> path is retired; production now runs self-hosted on `patrick-mini` via
> `my-stack/deploy-patrick-mini.sh`. This skill covers local-Docker dev
> only. The `https://jobsync/api` Auth0 audience is an opaque identifier
> kept intentionally — do not rename it.

When running Joblign locally in Docker for development/testing, use the
`run_local_docker.sh` script (image `joblign-local`, container `joblign-local`).

## When to Use

- Developing features that require full container environment
- Testing deployment configuration without GCP costs
- Iterating quickly on Dockerfile changes
- Local integration testing with SQLite instead of Cloud SQL

## Script Structure

Create `run_local_docker.sh` with these components:

### 1. Prerequisites Check
```bash
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "Docker daemon is not running"
    exit 1
fi
```

### 2. Environment Configuration
```bash
# Create .env from example if needed
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Configure for local SQLite (comment out DATABASE_URL to force SQLite fallback)
if grep -q "^DATABASE_URL=" .env 2>/dev/null; then
    sed -i.bak 's/^DATABASE_URL=/#DATABASE_URL=/' .env && rm -f .env.bak
fi
```

### 3. Container Management
```bash
# Stop and remove existing container
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker stop ${CONTAINER_NAME} 2>/dev/null || true
    docker rm ${CONTAINER_NAME} 2>/dev/null || true
fi
```

### 4. Build and Run
```bash
# Build image locally
docker build -t ${IMAGE_NAME} .

# Run with environment variables
docker run -d \
  --name ${CONTAINER_NAME} \
  -p ${PORT}:8080 \
  -e PYTHONPATH=/app/backend \
  -e PORT=8080 \
  -e MODEL_ENDPOINT="${MODEL_ENDPOINT:-http://host.docker.internal:11434}" \
  -e AUTH0_DOMAIN="${AUTH0_DOMAIN:-your-auth0-domain}" \
  -e CORS_ORIGIN="${CORS_ORIGIN:-http://localhost:${PORT}}" \
  --rm \
  ${IMAGE_NAME}
```

## Key Configuration Patterns

### Connect to Local Services from Docker

**Local Ollama:**
```bash
-e MODEL_ENDPOINT=http://host.docker.internal:11434
```

**Auth0:**
```bash
-e AUTH0_DOMAIN=dev-xxxxx.us.auth0.com
-e AUTH0_AUDIENCE=https://jobsync/api
```

**CORS for localhost:**
```bash
-e CORS_ORIGIN=http://localhost:8765
```

### Port Mapping

Cloud Run containers typically listen on port 8080. Map to a different host port:
```bash
-p 8765:8080  # Host:Container
```

### Database Strategy

For local development:
- **Don't set DATABASE_URL** → App falls back to SQLite
- **Comment out existing DATABASE_URL** in .env to force SQLite mode
- This avoids needing Cloud SQL or local PostgreSQL setup

## Complete Script Example

```bash
#!/bin/bash
set -e

PORT="${PORT:-8765}"
IMAGE_NAME="joblign-local"
CONTAINER_NAME="joblign-local"

# Check Docker
if ! docker info &> /dev/null; then
    echo "Docker is not running"
    exit 1
fi

# Configure environment
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Force SQLite for local dev
if grep -q "^DATABASE_URL=" .env 2>/dev/null; then
    sed -i.bak 's/^DATABASE_URL=/#DATABASE_URL=/' .env && rm -f .env.bak
fi

# Cleanup existing container
docker stop ${CONTAINER_NAME} 2>/dev/null || true
docker rm ${CONTAINER_NAME} 2>/dev/null || true

# Build
docker build -t ${IMAGE_NAME} .

# Run
docker run -d \
  --name ${CONTAINER_NAME} \
  -p ${PORT}:8080 \
  -e PYTHONPATH=/app/backend \
  -e PORT=8080 \
  -e MODEL_ENDPOINT="http://host.docker.internal:11434" \
  -e AUTH0_DOMAIN="dev-xxxxx.us.auth0.com" \
  -e AUTH0_AUDIENCE="https://jobsync/api" \
  -e CORS_ORIGIN="http://localhost:${PORT}" \
  --rm \
  ${IMAGE_NAME}

echo "Running at http://localhost:${PORT}"
```

## Container Management Commands

```bash
# View logs
docker logs joblign-local

# Follow logs
docker logs -f joblign-local

# Stop container
docker stop joblign-local

# View running containers
docker ps

# Custom port
PORT=9000 ./run_local_docker.sh
```

## Benefits vs Cloud Build

| Aspect | Cloud Build | Local Docker |
|--------|-------------|--------------|
| Cost | ~$0.03/min + build minutes | $0 |
| Iteration speed | Minutes per build | Seconds |
| Network access | GCP services only | Local services via host.docker.internal |
| Database | Cloud SQL required | SQLite fallback |
| Best for | Production deploys | Development/testing |

## Important Notes

1. **`host.docker.internal`** works on Docker Desktop for Mac/Windows to access host services
2. **`--rm` flag** automatically removes container on stop, keeping system clean
3. **Environment variables** should match production where possible to catch config issues early
4. **SQLite mode** is triggered by absence of DATABASE_URL - verify this in your app's config logic
