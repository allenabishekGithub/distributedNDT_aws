#!/bin/bash
echo "NDT Manager Status"
echo "================="
echo "Directory: /home/ubuntu/distributedNDT_aws"
echo "Instance:  ()"
echo "Region:  ()"
echo "Public IP: "
echo ""

# Check service status
echo "Service Status:"
echo "--------------"
if systemctl is-active ndt-manager >/dev/null 2>&1; then
    echo "✓ Systemd service is running"
    systemctl status ndt-manager --no-pager -l | head -10
else
    echo "○ Systemd service is not running"
fi

# Check process status
if pgrep -f "uvicorn ndt_manager" > /dev/null; then
    echo "✓ NDT Manager process is running"
    echo "  PIDs: $(pgrep -f 'uvicorn ndt_manager' | tr '\n' ' ')"
    
    # Show process details
    ps -f -p $(pgrep -f 'uvicorn ndt_manager' | head -1) 2>/dev/null || true
else
    echo "✗ NDT Manager process is not running"
fi

# Check API status
echo ""
echo "API Status:"
echo "----------"
if curl -s -f --connect-timeout 5 http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ API is responding on port 8000"
    echo "  Local: http://localhost:8000"
    echo "  Public: http://:8000"
    echo "  Docs: http://:8000/docs"
else
    echo "✗ API is not responding"
fi

# System resources
echo ""
echo "System Resources:"
echo "----------------"
echo "CPU Usage: $(top -bn1 2>/dev/null | grep "Cpu(s)" | sed 's/.*: *\([0-9.]*\)%*us.*/\1/' | head -1)%"
echo "Memory: $(free -h | awk 'NR==2{printf "Used: %s/%s (%.1f%%)", $3,$2,$3*100/$2}')"
echo "Disk: $(df -h /home/ubuntu/distributedNDT_aws | awk 'NR==2{printf "Used: %s/%s (%s)", $3,$2,$5}')"
echo "Load Average: $(uptime | awk -F'load average:' '{print $2}' | sed 's/^[ \t]*//')"

# Dependencies
echo ""
echo "Dependencies:"
echo "------------"
if systemctl is-active docker >/dev/null 2>&1; then
    echo "✓ Docker is running ($(docker --version | cut -d' ' -f3 | tr -d ','))"
else
    echo "✗ Docker is not running"
fi

if redis-cli ping >/dev/null 2>&1; then
    echo "✓ Redis is responding ($(redis-cli --version | cut -d' ' -f2))"
else
    echo "✗ Redis is not responding"
fi

if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "✓ AWS access available"
    echo "  Identity: $(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null | head -1)"
else
    echo "✗ AWS access not available"
fi

if [ -f ~/.ssh/id_rsa ]; then
    echo "✓ SSH key found"
else
    echo "⚠ SSH key not found (needed for worker instances)"
fi

# Worker instances
echo ""
echo "Worker Instances:"
echo "----------------"
WORKER_COUNT=$(aws ec2 describe-instances --region  --filters "Name=tag:NDT-Managed,Values=true" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId]' --output text 2>/dev/null | wc -l)
echo "Active workers: $WORKER_COUNT"

if [ "$WORKER_COUNT" -gt 0 ]; then
    echo "Worker instances:"
    aws ec2 describe-instances --region  --filters "Name=tag:NDT-Managed,Values=true" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,PublicIpAddress]' --output table 2>/dev/null || echo "Could not fetch worker details"
fi
