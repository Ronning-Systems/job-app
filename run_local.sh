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

if ! command -v python3 &> /dev/null; then
    echo -e "\033[0;31m✗ Python 3 is not installed\033[0m"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
log_info "Python version: $PYTHON_VERSION"

# Create virtual environment if it doesn't exist
if [ ! -d "backend/venv" ]; then
    log_step "Creating virtual environment..."
    python3 -m venv backend/venv
    log_info "Virtual environment created"
else
    log_info "Virtual environment already exists"
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

# Run the server
cd backend
python3 -m uvicorn main:app --host $HOST --port $PORT --reload
