#!/bin/bash
echo "NDT Manager Health Check"
echo "======================="
echo "Timestamp: $(date)"
echo "Instance:  ($HOSTNAME)"
echo ""

issues=0
warnings=0

# Check service status
echo "1. Checking service status..."
if systemctl is-active ndt-manager >/dev/null 2>&1; then
    echo "   ✓ Systemd service is running"
elif pgrep -f "uvicorn ndt_manager" > /dev/null; then
    echo "   ⚠ Process is running but not via systemd"
    ((warnings++))
else
    echo "   ✗ NDT Manager service is not running"
    ((issues++))
fi

# Check API health
echo "2. Checking API health..."
if curl -s -f --connect-timeout 10 http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✓ API is responding"
    
    # Get API response details
    API_RESPONSE=$(curl -s http://localhost:8000/health 2>/dev/null)
    if echo "$API_RESPONSE" | jq -r '.status' 2>/dev/null | grep -q "healthy"; then
        echo "   ✓ API reports healthy status"
    else
        echo "   ⚠ API responded but status unclear"
        ((warnings++))
    fi
else
    echo "   ✗ API is not responding"
    ((issues++))
fi

# Check AWS access
echo "3. Checking AWS access..."
if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "   ✓ AWS credentials are valid"
    CALLER_ARN=$(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null)
    echo "   Identity: $CALLER_ARN"
    
    # Check EC2 permissions
    if aws ec2 describe-instances --max-items 1 >/dev/null 2>&1; then
        echo "   ✓ EC2 permissions verified"
    else
        echo "   ✗ EC2 permissions insufficient"
        ((issues++))
    fi
else
    echo "   ✗ AWS credentials are not valid"
    ((issues++))
fi

# Check SSH key
echo "4. Checking SSH key..."
SSH_KEY=${SSH_KEY_PATH:-~/.ssh/id_rsa}
if [ -f "$SSH_KEY" ]; then
    echo "   ✓ SSH key exists at $SSH_KEY"
    
    # Check key permissions
    KEY_PERMS=$(stat -c %a "$SSH_KEY" 2>/dev/null || echo "000")
    if [ "$KEY_PERMS" = "600" ]; then
        echo "   ✓ SSH key permissions are correct"
    else
        echo "   ⚠ SSH key permissions should be 600"
        chmod 600 "$SSH_KEY" 2>/dev/null && echo "   ✓ Fixed SSH key permissions" || echo "   ✗ Could not fix SSH key permissions"
        ((warnings++))
    fi
else
    echo "   ✗ SSH key not found at $SSH_KEY"
    echo "     You'll need to add your SSH key for worker instance management"
    ((issues++))
fi

# Check Redis
echo "5. Checking Redis..."
if redis-cli ping >/dev/null 2>&1; then
    echo "   ✓ Redis is responding"
    
    # Check Redis memory usage
    REDIS_MEMORY=$(redis-cli info memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    echo "   Memory usage: $REDIS_MEMORY"
else
    echo "   ✗ Redis is not responding"
    echo "   Attempting to start Redis..."
    sudo systemctl start redis-server && echo "   ✓ Redis started" || echo "   ✗ Failed to start Redis"
    ((issues++))
fi

# Check Docker
echo "6. Checking Docker..."
if systemctl is-active docker >/dev/null 2>&1; then
    echo "   ✓ Docker service is running"
    
    # Check Docker daemon
    if docker info >/dev/null 2>&1; then
        echo "   ✓ Docker daemon is accessible"
        DOCKER_CONTAINERS=$(docker ps -q | wc -l)
        echo "   Running containers: $DOCKER_CONTAINERS"
    else
        echo "   ⚠ Docker daemon not accessible (user might need to re-login)"
        ((warnings++))
    fi
else
    echo "   ✗ Docker service is not running"
    ((issues++))
fi

# Check Python environment
echo "7. Checking Python environment..."
if [ -f "venv/bin/python" ]; then
    echo "   ✓ Virtual environment exists"
    
    if source venv/bin/activate && python -c "import fastapi, boto3, paramiko, uvicorn" 2>/dev/null; then
        echo "   ✓ Required Python packages are available"
        PYTHON_VERSION=$(python --version 2>&1)
        echo "   $PYTHON_VERSION"
    else
        echo "   ✗ Python environment has missing packages"
        ((issues++))
    fi
else
    echo "   ✗ Virtual environment not found"
    ((issues++))
fi

# Check system resources
echo "8. Checking system resources..."
CPU_USAGE=$(top -bn1 2>/dev/null | grep "Cpu(s)" | sed 's/.*: *\([0-9.]*\)%*us.*/\1/' | head -1)
MEMORY_USAGE=$(free | awk 'NR==2{printf "%.1f", $3*100/$2}')
DISK_USAGE=$(df /home/ubuntu/distributedNDT_aws | awk 'NR==2{print $5}' | sed 's/%//')

echo "   CPU Usage: ${CPU_USAGE}%"
echo "   Memory Usage: ${MEMORY_USAGE}%"
echo "   Disk Usage: ${DISK_USAGE}%"

# Check resource thresholds
if (( $(echo "$CPU_USAGE > 90" | bc -l 2>/dev/null || echo 0) )); then
    echo "   ⚠ High CPU usage"
    ((warnings++))
fi

if (( $(echo "$MEMORY_USAGE > 90" | bc -l 2>/dev/null || echo 0) )); then
    echo "   ⚠ High memory usage"
    ((warnings++))
fi

if [ "$DISK_USAGE" -gt 90 ]; then
    echo "   ⚠ High disk usage"
    ((warnings++))
fi

# Summary
echo ""
echo "======================="
echo "Health Check Summary:"
echo "======================="
if [ $issues -eq 0 ] && [ $warnings -eq 0 ]; then
    echo "✓ Perfect! All checks passed"
    echo ""
    echo "🚀 NDT Manager is ready to use!"
    echo "   Start: ./start.sh"
    echo "   API: http://:8000"
    echo "   Docs: http://:8000/docs"
    exit 0
elif [ $issues -eq 0 ]; then
    echo "⚠ Minor issues: $warnings warning(s)"
    echo ""
    echo "NDT Manager should work but may have reduced functionality"
    echo "Review warnings above and fix if needed"
    exit 0
else
    echo "✗ Critical issues: $issues error(s), $warnings warning(s)"
    echo ""
    echo "Please fix the errors above before starting NDT Manager"
    exit 1
fi
