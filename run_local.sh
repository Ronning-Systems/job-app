#!/bin/bash
# Local Development Server Script
# Runs the JobSync backend on localhost with SQLite database

set -e

echo "=========================================================================="
echo "JobSync - Local Development Server"
echo "=========================================================================="

# Configuration
PORT="${PORT:-8765}"
HOST="${HOST:-0.0.0.0}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}!${NC} $1"; }
log_step() { echo -e "${BLUE}→${NC} $1"; }

# Check prerequisites
log_step "Checking prerequisites..."

if ! command -v brew &> /dev/null; then
    echo -e "\033[0;31m✗ Homebrew is required to install Python 3.12 on first run\033[0m"
    echo -e "\033[0;31m  Install: https://brew.sh\033[0m"
    exit 1
fi

# Ensure python3.12 is installed (pydantic-core 2.14.6 cannot build on 3.13+)
if ! command -v python3.12 &> /dev/null; then
    log_step "Installing Python 3.12 via Homebrew (one-time, ~3 min)..."
    brew install python@3.12
    log_info "Python 3.12 installed"
else
    log_info "Python 3.12 available"
fi

# Decide whether the existing venv needs to be recreated.
# It needs recreating if: it doesn't exist, its Python binary is missing
# (dangling symlink from a moved project), or its Python is 3.13+.
RECREATE_VENV=0

if [ ! -d "backend/venv" ]; then
    RECREATE_VENV=1
elif ! backend/venv/bin/python -c "import sys" &> /dev/null; then
    log_warn "Existing venv is broken (Python binary missing) — will recreate"
    RECREATE_VENV=1
else
    VENV_PY_MAJOR=$(backend/venv/bin/python -c "import sys; print(sys.version_info.major)")
    VENV_PY_MINOR=$(backend/venv/bin/python -c "import sys; print(sys.version_info.minor)")
    if [ "$VENV_PY_MAJOR" -gt 3 ] || { [ "$VENV_PY_MAJOR" -eq 3 ] && [ "$VENV_PY_MINOR" -gt 12 ]; }; then
        log_warn "Existing venv uses Python $VENV_PY_MAJOR.$VENV_PY_MINOR (3.13+ not supported by pydantic-core 2.14.6) — will recreate with 3.12"
        RECREATE_VENV=1
    fi
fi

if [ "$RECREATE_VENV" -eq 1 ]; then
    log_step "Creating virtual environment with Python 3.12..."
    rm -rf backend/venv
    python3.12 -m venv backend/venv
    log_info "Virtual environment created"
else
    log_info "Virtual environment already exists and is compatible"
fi

# Activate virtual environment
log_step "Activating virtual environment..."
source backend/venv/bin/activate

# Install dependencies
log_step "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt
log_info "Dependencies installed"

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
# Remove DATABASE_URL from .env if present to force SQLite fallback
if grep -q "^DATABASE_URL=" .env 2>/dev/null; then
    log_warn "DATABASE_URL found in .env - commenting out for local SQLite"
    sed -i.bak 's/^DATABASE_URL=/#DATABASE_URL=/' .env && rm -f .env.bak
fi

# Create necessary directories
mkdir -p backend/logs

echo ""
echo "=========================================================================="
echo "Starting JobSync Backend Server"
echo "=========================================================================="
echo ""
echo "Server will be available at: http://localhost:${PORT}"
echo "API docs at: http://localhost:${PORT}/docs"
echo ""
echo "Using SQLite database (local development mode)"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=========================================================================="
echo ""

# Set environment variables for local development
export PYTHONPATH=/app/backend:$PYTHONPATH
export PORT=$PORT
# Skip Auth0 for local dev. Frontend reads /api/health to know to bypass.
export AUTH_DISABLED=true

# Run the server
cd backend
python3 -m uvicorn main:app --host $HOST --port $PORT --reload
