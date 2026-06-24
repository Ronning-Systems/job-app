#!/bin/bash

# JobSync Setup Script
# Creates Python 3.9 virtual environments for all Python services

set -e

echo "========================================"
echo "JobSync Setup Script"
echo "========================================"

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
REQUIRED_VERSION="3.9"

if [[ "$PYTHON_VERSION" != "$REQUIRED_VERSION" ]]; then
    echo "Warning: Python $PYTHON_VERSION detected, but Python $REQUIRED_VERSION is recommended"
    echo "Attempting to use python3.9..."
    if ! command -v python3.9 &> /dev/null; then
        echo "Error: Python 3.9 is required but not installed"
        exit 1
    fi
    PYTHON_CMD="python3.9"
else
    PYTHON_CMD="python3"
fi

echo "Using Python: $PYTHON_CMD"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create backend virtual environment
echo ""
echo "Setting up Backend Virtual Environment..."
echo "========================================"

if [ -d "backend/venv" ]; then
    echo "Backend venv already exists. Removing old environment..."
    rm -rf backend/venv
fi

$PYTHON_CMD -m venv backend/venv
source backend/venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install backend dependencies
pip install -r backend/requirements.txt

echo ""
echo "Backend setup complete!"

# Create MCP Server virtual environment
echo ""
echo "Setting up MCP Server Virtual Environment..."
echo "========================================"

if [ -d "mcp_server/venv" ]; then
    echo "MCP Server venv already exists. Removing old environment..."
    rm -rf mcp_server/venv
fi

$PYTHON_CMD -m venv mcp_server/venv
source mcp_server/venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install MCP server dependencies
pip install -r mcp_server/requirements.txt

echo ""
echo "MCP Server setup complete!"

# Create startup scripts
echo ""
echo "Creating startup scripts..."
echo "========================================"

cat > start_backend.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source backend/venv/bin/activate
cd backend
python main.py
EOF

cat > start_mcp.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source mcp_server/venv/bin/activate
python mcp_server.py
EOF

cat > start_all.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting JobSync services..."
echo "=============================="

# Start MCP Server in background
echo "Starting MCP Server on port 8080..."
source mcp_server/venv/bin/activate
python mcp_server.py &
MCP_PID=$!
echo "MCP Server PID: $MCP_PID"

# Wait a moment for MCP to start
sleep 2

# Start Backend
echo "Starting Backend API on port 8000..."
source backend/venv/bin/activate
cd backend
python main.py &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

echo ""
echo "Services started!"
echo "Backend: http://localhost:8000"
echo "MCP Server: http://localhost:8080"
echo ""
echo "Press Ctrl+C to stop all services"

# Trap to kill processes on exit
trap "kill $MCP_PID $BACKEND_PID 2>/dev/null; exit" INT TERM

wait
EOF

chmod +x start_backend.sh start_mcp.sh start_all.sh

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "To start the app locally:"
echo "  ./run_local.sh"
echo ""
echo "The frontend will be available at:"
echo "  http://localhost:8765"
echo ""
