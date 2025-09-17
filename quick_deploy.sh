#!/bin/bash
echo "🚀 NDT Manager Quick Deploy & Test"
echo "=================================="
echo ""

# Start the service in background
echo "1. Starting NDT Manager..."
if pgrep -f "uvicorn ndt_manager" > /dev/null; then
    echo "   ✓ Already running"
else
    ./start.sh &
    echo "   Started in background"
    
    # Wait for startup
    echo "   Waiting for startup..."
    for i in {1..30}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            break
        fi
        sleep 1
        echo -n "."
    done
    echo ""
fi

# Wait a moment for full initialization
sleep 3

echo ""
echo "2. Running health check..."
./health_check.sh

echo ""
echo "3. Testing API..."
./test_api.sh

echo ""
echo "=================================="
echo "🎉 Quick deploy completed!"
echo ""
echo "Next steps:"
echo "• Deploy example topology: python api_client.py deploy example_topology.json"
echo "• Monitor resources: python api_client.py monitor"
echo "• View all commands: python api_client.py --help"
