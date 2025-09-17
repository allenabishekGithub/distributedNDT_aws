#!/bin/bash

# Complete the NDT Manager setup after the main setup.sh run
# This script handles the final verification and creates missing components

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[COMPLETE]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[FINALIZE]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

cd /home/ubuntu/distributedNDT_aws

print_header "Completing NDT Manager setup..."

# Try to get instance metadata with timeout and fallbacks
print_status "Detecting instance information..."

get_metadata() {
    local endpoint=$1
    local fallback=$2
    
    # Try IMDSv2 first (with token)
    local token=$(curl -s --connect-timeout 5 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || echo "")
    
    if [ -n "$token" ]; then
        curl -s --connect-timeout 5 -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$endpoint" 2>/dev/null || echo "$fallback"
    else
        # Fallback to IMDSv1
        curl -s --connect-timeout 5 "http://169.254.169.254/latest/meta-data/$endpoint" 2>/dev/null || echo "$fallback"
    fi
}

INSTANCE_TYPE=$(get_metadata "instance-type" "unknown")
INSTANCE_ID=$(get_metadata "instance-id" "unknown")
PUBLIC_IP=$(get_metadata "public-ipv4" "unknown")
PRIVATE_IP=$(get_metadata "local-ipv4" "192.168.1.100")
REGION=$(get_metadata "placement/region" "eu-central-1")
AZ=$(get_metadata "placement/availability-zone" "eu-central-1a")

print_status "Instance Type: $INSTANCE_TYPE"
print_status "Instance ID: $INSTANCE_ID"
print_status "Region: $REGION"
print_status "Public IP: $PUBLIC_IP"
print_status "Private IP: $PRIVATE_IP"

# Update .env file with correct values
print_status "Updating environment configuration..."
cat > .env <<EOF
# NDT Manager Environment Configuration
# Instance: $INSTANCE_TYPE in $REGION

# Instance Information
NDT_INSTANCE_TYPE=$INSTANCE_TYPE
NDT_MANAGER_MODE=true
INSTANCE_ID=$INSTANCE_ID
PUBLIC_IP=$PUBLIC_IP
PRIVATE_IP=$PRIVATE_IP

# AWS Configuration
AWS_DEFAULT_REGION=$REGION
AWS_KEY_PAIR_NAME=default-key
SSH_KEY_PATH=~/.ssh/id_rsa

# Server Configuration
HOST=0.0.0.0
PORT=8000
UVICORN_WORKERS=2

# Performance Settings
MAX_CONCURRENT_OPERATIONS=10
BATCH_SIZE=50
CONNECTION_POOL_SIZE=20

# Resource Settings
CPU_CORES=4
MEMORY_GB=16
MAX_WORKER_INSTANCES=25

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/ndt-manager.log
LOG_ROTATION_SIZE=100MB
LOG_RETENTION_DAYS=30
ACCESS_LOG=true

# Resource Monitoring Thresholds
CPU_THRESHOLD=70
MEMORY_THRESHOLD=75
STORAGE_THRESHOLD=85

# Redis Configuration
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0

# Security Configuration
API_KEY_HEADER=X-API-Key

# Worker Instance Configuration
DEFAULT_WORKER_INSTANCE_TYPE=t3.medium
MIN_INSTANCES=0
DEPLOYMENT_TIMEOUT=600
HEALTH_CHECK_INTERVAL=30

# Feature Flags
ENABLE_METRICS=true
ENABLE_CACHING=true
ENABLE_MONITORING=true
CACHE_TTL=300
EOF

# Complete the remaining checks that were cut off
print_header "Completing system verification..."

CHECKS_PASSED=0
TOTAL_CHECKS=10

# Check 1: AWS access
echo -n "Checking AWS access... "
if aws sts get-caller-identity > /dev/null 2>&1; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 2: Python environment
echo -n "Checking Python environment... "
if [ -f "venv/bin/python" ] && source venv/bin/activate && python -c "import fastapi, boto3, paramiko" 2>/dev/null; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 3: Docker
echo -n "Checking Docker... "
if systemctl is-active docker >/dev/null 2>&1; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 4: Redis
echo -n "Checking Redis... "
if redis-cli ping >/dev/null 2>&1; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 5: SSH key
echo -n "Checking SSH key... "
if [ -f ~/.ssh/id_rsa ]; then
    chmod 600 ~/.ssh/id_rsa
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "⚠"
    print_warning "SSH key not found at ~/.ssh/id_rsa"
    print_warning "You'll need this for managing worker instances"
fi

# Check 6: Systemd service
echo -n "Checking systemd service... "
if systemctl is-enabled ndt-manager >/dev/null 2>&1; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 7: Configuration files
echo -n "Checking configuration... "
if [ -f ".env" ] && [ -d "configs" ]; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 8: Management scripts
echo -n "Checking management scripts... "
if [ -x "start.sh" ] && [ -x "stop.sh" ] && [ -x "status.sh" ] && [ -x "health_check.sh" ]; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Check 9: Disk space
echo -n "Checking disk space... "
AVAILABLE_SPACE=$(df . | awk 'NR==2{print $4}')
if [ "$AVAILABLE_SPACE" -gt 5242880 ]; then  # 5GB in KB
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "⚠"
fi

# Check 10: Network connectivity
echo -n "Checking network connectivity... "
if curl -s --connect-timeout 5 https://api.github.com > /dev/null; then
    echo "✓"
    ((CHECKS_PASSED++))
else
    echo "✗"
fi

# Update management scripts with correct values
print_status "Updating management scripts with instance information..."

# Update status.sh with correct values
cat > status.sh <<EOF
#!/bin/bash
echo "NDT Manager Status"
echo "================="
echo "Directory: $(pwd)"
echo "Instance: $INSTANCE_TYPE ($INSTANCE_ID)"
echo "Region: $REGION ($AZ)"
echo "Public IP: $PUBLIC_IP"
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
    echo "  PIDs: \$(pgrep -f 'uvicorn ndt_manager' | tr '\\n' ' ')"
    
    # Show process details
    ps -f -p \$(pgrep -f 'uvicorn ndt_manager' | head -1) 2>/dev/null || true
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
    echo "  Public: http://$PUBLIC_IP:8000"
    echo "  Docs: http://$PUBLIC_IP:8000/docs"
else
    echo "✗ API is not responding"
fi

# System resources
echo ""
echo "System Resources:"
echo "----------------"
echo "CPU Usage: \$(top -bn1 2>/dev/null | grep "Cpu(s)" | sed 's/.*: *\\([0-9.]*\\)%*us.*/\\1/' | head -1)%"
echo "Memory: \$(free -h | awk 'NR==2{printf "Used: %s/%s (%.1f%%)", \$3,\$2,\$3*100/\$2}')"
echo "Disk: \$(df -h $(pwd) | awk 'NR==2{printf "Used: %s/%s (%s)", \$3,\$2,\$5}')"
echo "Load Average: \$(uptime | awk -F'load average:' '{print \$2}' | sed 's/^[ \\t]*//')"

# Dependencies
echo ""
echo "Dependencies:"
echo "------------"
if systemctl is-active docker >/dev/null 2>&1; then
    echo "✓ Docker is running (\$(docker --version | cut -d' ' -f3 | tr -d ','))"
else
    echo "✗ Docker is not running"
fi

if redis-cli ping >/dev/null 2>&1; then
    echo "✓ Redis is responding (\$(redis-cli --version | cut -d' ' -f2))"
else
    echo "✗ Redis is not responding"
fi

if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "✓ AWS access available"
    echo "  Identity: \$(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null | head -1)"
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
WORKER_COUNT=\$(aws ec2 describe-instances --region $REGION --filters "Name=tag:NDT-Managed,Values=true" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId]' --output text 2>/dev/null | wc -l)
echo "Active workers: \$WORKER_COUNT"

if [ "\$WORKER_COUNT" -gt 0 ]; then
    echo "Worker instances:"
    aws ec2 describe-instances --region $REGION --filters "Name=tag:NDT-Managed,Values=true" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name,PublicIpAddress]' --output table 2>/dev/null || echo "Could not fetch worker details"
fi
EOF

chmod +x status.sh

# Create final setup completion file
echo "$(date): NDT Manager setup completed successfully" > .setup_complete
echo "Instance: $INSTANCE_TYPE ($INSTANCE_ID)" >> .setup_complete
echo "Region: $REGION ($AZ)" >> .setup_complete  
echo "Public IP: $PUBLIC_IP" >> .setup_complete
echo "Private IP: $PRIVATE_IP" >> .setup_complete
echo "Checks passed: $CHECKS_PASSED/$TOTAL_CHECKS" >> .setup_complete

# Create quick start instructions
cat > GETTING_STARTED.md <<EOF
# Getting Started with NDT Manager

## Your Configuration
- **Instance**: $INSTANCE_TYPE ($INSTANCE_ID)
- **Region**: $REGION ($AZ)  
- **Public IP**: $PUBLIC_IP
- **Setup Status**: $CHECKS_PASSED/$TOTAL_CHECKS checks passed

## Quick Start Commands

### 1. Check Health
\`\`\`bash
./health_check.sh
\`\`\`

### 2. Start NDT Manager
\`\`\`bash
# Option A: Start in foreground (recommended for first time)
./start.sh

# Option B: Start as system service
sudo systemctl start ndt-manager
\`\`\`

### 3. Verify It's Working
\`\`\`bash
# Check status
./status.sh

# Test API endpoints
./test_api.sh

# Or manual test
curl http://localhost:8000/health
curl http://$PUBLIC_IP:8000/health
\`\`\`

### 4. Deploy Example Topology
\`\`\`bash
# First start NDT Manager (if not already running)
./start.sh &

# Wait a moment for startup, then deploy
python api_client.py health
python api_client.py deploy example_topology.json
python api_client.py resources
\`\`\`

## Web Access
- **API**: http://$PUBLIC_IP:8000
- **Documentation**: http://$PUBLIC_IP:8000/docs
- **Health Check**: http://$PUBLIC_IP:8000/health

## Next Steps
1. Add your SSH key to ~/.ssh/id_rsa (for worker instances)
2. Update AWS_KEY_PAIR_NAME in .env if different from 'default-key'
3. Test with example topology
4. Create your own containerlab topologies

## Troubleshooting
- Logs: \`tail -f logs/ndt-manager.log\`
- Service logs: \`sudo journalctl -u ndt-manager -f\`
- Full health check: \`./health_check.sh\`
- Restart: \`./stop.sh && ./start.sh\`
EOF

print_status ""
print_status "======================================"
print_status "NDT Manager Setup Completed!"
print_status "======================================"
print_status ""
print_status "Final Status: $CHECKS_PASSED/$TOTAL_CHECKS checks passed"
print_status ""

if [ $CHECKS_PASSED -ge 8 ]; then
    print_status "🎉 Setup successful! NDT Manager is ready to use."
    print_status ""
    print_status "🚀 Next steps:"
    print_status "1. Run: ./health_check.sh"
    print_status "2. Start: ./start.sh"
    print_status "3. Test: curl http://localhost:8000/health"
    print_status ""
    print_status "🌐 Access your NDT Manager at: http://$PUBLIC_IP:8000"
elif [ $CHECKS_PASSED -ge 6 ]; then
    print_warning "⚠️  Most checks passed. NDT Manager should work."
    print_warning "Review any failed checks above."
    print_status ""
    print_status "You can proceed to start: ./start.sh"
else
    print_warning "❌ Several checks failed. Please review and fix issues."
    print_status ""
    print_status "Common fixes:"
    print_status "- Ensure SSH key exists: cp your-key.pem ~/.ssh/id_rsa"
    print_status "- Check AWS permissions: aws sts get-caller-identity"
    print_status "- Restart services: sudo systemctl restart docker redis-server"
fi

print_status ""
print_status "📚 Quick reference: cat GETTING_STARTED.md"

echo -e "${GREEN}✅ NDT Manager setup finalization complete!${NC}"