#!/bin/bash
# Local build and deploy script for JobSync Cloud Run deployment
# Replaces Cloud Build to avoid costs

set -e

# Configuration
REGION="${REGION:-us-west1}"
SERVICE_NAME="${SERVICE_NAME:-job-app}"
DB_INSTANCE="${DB_INSTANCE:-ronning-systems:us-west1:ronning-systems-jobapp}"
IMAGE_NAME="gcr.io/$(gcloud config get-value project)/${SERVICE_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}!${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo "=========================================================================="
echo "JobSync Cloud Run Deployment (Local Build)"
echo "=========================================================================="
echo "Project:     $(gcloud config get-value project)"
echo "Region:      ${REGION}"
echo "Service:     ${SERVICE_NAME}"
echo "DB Instance: ${DB_INSTANCE}"
echo "Image:       ${IMAGE_NAME}"
echo "=========================================================================="
echo ""

# Step 1: Verify prerequisites
log_info "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed or not in PATH"
    exit 1
fi

if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running"
    exit 1
fi

if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed"
    exit 1
fi

# Check authentication
if ! gcloud auth print-access-token &> /dev/null 2>&1; then
    log_error "Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi

log_info "Prerequisites verified"

# Capture current revision before deployment (for rollback instructions)
PREVIOUS_REVISION=$(gcloud run revisions list \
  --service "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(metadata.name)" \
  --sort-by="-metadata.creationTimestamp" \
  --limit=1 2>/dev/null || echo "none")

# Step 2: Ensure Docker is configured to authenticate to the registry.
# `gcr.io` is a legacy hostname that Google now maps to Artifact Registry.
# Without this, `docker push` will fail with an "Unauthenticated request"
# error even when the user has Owner-level IAM on the project.
log_info "Configuring Docker auth for ${IMAGE_NAME%/*}..."
gcloud auth configure-docker "${IMAGE_NAME%/*}" --quiet || {
    log_warn "gcloud auth configure-docker failed; push may still fail"
}

# Step 3: Build Docker image locally (amd64 for Cloud Run)
log_info "Building Docker image (linux/amd64)..."
docker build --platform linux/amd64 -t "${IMAGE_NAME}" .

if [ $? -ne 0 ]; then
    log_error "Docker build failed"
    exit 1
fi

log_info "Docker image built successfully"

# Step 4: Push to Container Registry
log_info "Pushing image to Container Registry..."
docker push "${IMAGE_NAME}"

if [ $? -ne 0 ]; then
    log_error "Failed to push image. Ensure you have permissions to push to gcr.io"
    exit 1
fi

log_info "Image pushed successfully"

# Step 5: Deploy to Cloud Run
log_info "Deploying to Cloud Run..."

gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_NAME}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances "${DB_INSTANCE}" \
  --set-env-vars "MODEL_ENDPOINT=https://ollama.com,MODEL_PARSING=minimax-m2.5:cloud,MODEL_AGENTS=glm-5:cloud,MODEL_GENERATION=qwen3.5:cloud,MODEL_GENERATION_FALLBACK=gemma3:12b-cloud,AUTH0_DOMAIN=dev-saxftot48835pavp.us.auth0.com,AUTH0_AUDIENCE=https://jobsync/api,CORS_ORIGIN=https://job-app-913142543866.us-west1.run.app" \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,OLLAMA_API_KEY=OLLAMA_API_KEY:latest" \
  --no-traffic

if [ $? -ne 0 ]; then
    log_error "Cloud Run deployment failed"
    exit 1
fi

log_info "New revision deployed (traffic not yet migrated)"

# Step 6: Get revision name
REVISION=$(gcloud run revisions list \
  --service "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(metadata.name)" \
  --sort-by="-metadata.creationTimestamp" \
  --limit=1)

log_info "New revision: ${REVISION}"

# Step 7: Migrate traffic to new revision
echo ""
log_info "Migrating traffic to new revision..."
gcloud run services update-traffic "${SERVICE_NAME}" \
  --region "${REGION}" \
  --to-latest

if [ $? -ne 0 ]; then
    log_error "Traffic migration failed"
    exit 1
fi

log_info "Traffic migrated successfully"

# Step 8: Get service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(status.url)")

# Step 9: Print summary
echo ""
echo "=========================================================================="
echo "Deployment complete!"
echo ""
echo "Service URL: ${SERVICE_URL}"
echo "New revision: ${REVISION} (100% traffic)"
echo ""
echo "To list all revisions:"
echo "  gcloud run revisions list --service ${SERVICE_NAME} --region ${REGION}"
echo ""
echo "To rollback to previous revision:"
echo "  gcloud run services update-traffic ${SERVICE_NAME} \\"
echo "    --region ${REGION} \\"
echo "    --to-revisions ${PREVIOUS_REVISION}=100"
echo "=========================================================================="
