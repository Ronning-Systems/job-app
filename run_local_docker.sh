#!/bin/bash
# Local Docker Deployment Script
# Builds and runs JobSync locally using Docker (not Cloud Run)

set -e

# Configuration
PORT="${PORT:-8765}"
IMAGE_NAME="job-app-local"
CONTAINER_NAME="job-app-local"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}!${NC} $1"; }
log_step() { echo -e "${BLUE}→${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo "=========================================================================="
echo "JobSync - Local Docker Deployment"
echo "=========================================================================="
echo "Port:        ${PORT}"
echo "Image:       ${IMAGE_NAME}"
echo "Container:   ${CONTAINER_NAME}"
echo "=========================================================================="
echo ""

# Check prerequisites
log_step "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed or not in PATH"
    exit 1
fi

if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running"
    exit 1
fi

log_info "Docker is running"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    log_step "Creating .env file from .env.example..."
    cp .env.example .env
    log_info ".env file created"
else
    log_info ".env file already exists"
fi

# Ensure DATABASE_URL is not set (use SQLite)
log_step "Configuring for SQLite database..."
if grep -q "^DATABASE_URL=" .env 2>/dev/null; then
    log_warn "DATABASE_URL found in .env - commenting out for local SQLite"
    sed -i.bak 's/^DATABASE_URL=/#DATABASE_URL=/' .env && rm -f .env.bak
fi

# Stop and remove existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_step "Stopping existing container..."
    docker stop ${CONTAINER_NAME} 2>/dev/null || true
    docker rm ${CONTAINER_NAME} 2>/dev/null || true
    log_info "Existing container removed"
fi

# Build Docker image locally
log_step "Building Docker image..."
docker build -t ${IMAGE_NAME} .

if [ $? -ne 0 ]; then
    log_error "Docker build failed"
    exit 1
fi

log_info "Docker image built successfully: ${IMAGE_NAME}"

# Run container
log_step "Starting container..."
docker run -d \
  --name ${CONTAINER_NAME} \
  -p ${PORT}:8080 \
  -e PYTHONPATH=/app/backend \
  -e PORT=8080 \
  -e MODEL_ENDPOINT="${MODEL_ENDPOINT:-http://host.docker.internal:11434}" \
  -e MODEL_PARSING="${MODEL_PARSING:-llama3.2:latest}" \
  -e MODEL_AGENTS="${MODEL_AGENTS:-llama3.2:latest}" \
  -e MODEL_GENERATION="${MODEL_GENERATION:-llama3.2:latest}" \
  -e AUTH0_DOMAIN="${AUTH0_DOMAIN:-dev-saxftot48835pavp.us.auth0.com}" \
  -e AUTH0_AUDIENCE="${AUTH0_AUDIENCE:-https://jobsync/api}" \
  -e CORS_ORIGIN="${CORS_ORIGIN:-http://localhost:${PORT}}" \
  --rm \
  ${IMAGE_NAME}

if [ $? -ne 0 ]; then
    log_error "Failed to start container"
    exit 1
fi

log_info "Container started successfully"

# Wait for container to be ready
log_step "Waiting for service to be ready..."
sleep 3

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_error "Container failed to start. Check logs:"
    docker logs ${CONTAINER_NAME}
    exit 1
fi

echo ""
echo "=========================================================================="
echo "✓ Deployment Complete!"
echo "=========================================================================="
echo ""
echo "Application URL: http://localhost:${PORT}"
echo "API Docs:        http://localhost:${PORT}/docs"
echo "Health Check:    http://localhost:${PORT}/api/health"
echo ""
echo "Container:       ${CONTAINER_NAME}"
echo "Image:           ${IMAGE_NAME}"
echo ""
echo "Useful commands:"
echo "  docker logs ${CONTAINER_NAME}        # View logs"
echo "  docker logs -f ${CONTAINER_NAME}     # Follow logs"
echo "  docker stop ${CONTAINER_NAME}        # Stop container"
echo "  docker rm ${CONTAINER_NAME}          # Remove container"
echo ""
echo "To stop the server:"
echo "  docker stop ${CONTAINER_NAME}"
echo "=========================================================================="
