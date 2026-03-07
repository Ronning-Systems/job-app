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
