#!/bin/bash
# NDT Manager Startup Script

set -e

echo "Starting NDT Manager..."
cd "$(dirname "$0")"

# Source environment variables
source venv/bin/activate
export $(cat .env | grep -v '^#' | xargs) 2>/dev/null || true

echo "Checking prerequisites..."

# Check AWS access
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "ERROR: AWS access not available"
    echo "Please ensure IAM role is attached to the instance"
    exit 1
fi

# Check and start Redis if needed
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Starting Redis..."
    sudo systemctl start redis-server
    sleep 2
    
    if ! redis-cli ping > /dev/null 2>&1; then
        echo "ERROR: Redis failed to start"
        exit 1
    fi
fi

# Check and start Docker if needed
if ! systemctl is-active docker >/dev/null 2>&1; then
    echo "Starting Docker..."
    sudo systemctl start docker
fi

# Check if port is available
if netstat -tlnp 2>/dev/null | grep -q ":8000 "; then
    echo "WARNING: Port 8000 is already in use"
    echo "Stopping any existing NDT Manager processes..."
    pkill -f "uvicorn ndt_manager" 2>/dev/null || true
    sleep 3
fi

echo "Starting NDT Manager API server..."
echo "Instance:  in "
echo "Public URL: http://:8000"
echo "Documentation: http://:8000/docs"
echo ""

# Start the application
exec uvicorn ndt_manager:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --log-level info \
    --access-log \
    --use-colors \
    --reload-dir . \
    --app-dir .
