#!/bin/bash
echo "Testing NDT Manager API..."
echo "========================"
echo ""

# Check if service is running
if ! pgrep -f "uvicorn ndt_manager" > /dev/null; then
    echo "❌ NDT Manager is not running"
    echo "Start it first with: ./start.sh"
    exit 1
fi

echo "🔍 Testing API endpoints..."
echo ""

# Test health endpoint
echo "1. Health endpoint..."
if HEALTH=$(curl -s --connect-timeout 10 "http://localhost:8000/health" 2>/dev/null); then
    if echo "$HEALTH" | jq . >/dev/null 2>&1; then
        echo "   ✓ Health endpoint responded with valid JSON"
        echo "$HEALTH" | jq .
    else
        echo "   ⚠ Health endpoint responded but not valid JSON"
        echo "   Response: $HEALTH"
    fi
else
    echo "   ✗ Health endpoint failed"
fi

echo ""

# Test resources endpoint
echo "2. Resources endpoint..."
if RESOURCES=$(curl -s --connect-timeout 10 "http://localhost:8000/resources" 2>/dev/null); then
    if echo "$RESOURCES" | jq . >/dev/null 2>&1; then
        echo "   ✓ Resources endpoint responded with valid JSON"
        INSTANCE_COUNT=$(echo "$RESOURCES" | jq '.instances | length' 2>/dev/null || echo 0)
        echo "   Managed instances: $INSTANCE_COUNT"
    else
        echo "   ⚠ Resources endpoint responded but not valid JSON"
    fi
else
    echo "   ✗ Resources endpoint failed"
fi

echo ""

# Test deployments endpoint
echo "3. Deployments endpoint..."
if DEPLOYMENTS=$(curl -s --connect-timeout 10 "http://localhost:8000/deployments" 2>/dev/null); then
    if echo "$DEPLOYMENTS" | jq . >/dev/null 2>&1; then
        echo "   ✓ Deployments endpoint responded with valid JSON"
        DEPLOYMENT_COUNT=$(echo "$DEPLOYMENTS" | jq 'length' 2>/dev/null || echo 0)
        echo "   Active deployments: $DEPLOYMENT_COUNT"
    else
        echo "   ⚠ Deployments endpoint responded but not valid JSON"
    fi
else
    echo "   ✗ Deployments endpoint failed"
fi

echo ""

# Test OpenAPI docs
echo "4. API Documentation..."
if curl -s --connect-timeout 10 "http://localhost:8000/docs" >/dev/null 2>&1; then
    echo "   ✓ API documentation is available"
    echo "   📚 Visit: http://:8000/docs"
else
    echo "   ✗ API documentation not accessible"
fi

echo ""
echo "========================"
echo "✅ API Testing Complete"
echo ""
echo "🌐 Access your NDT Manager at:"
echo "   • API: http://:8000"
echo "   • Docs: http://:8000/docs"
echo "   • Health: http://:8000/health"
echo ""
echo "🔧 Management commands:"
echo "   • ./status.sh - Check status"
echo "   • ./health_check.sh - Full health check"
echo "   • python api_client.py health - Test with CLI client"
