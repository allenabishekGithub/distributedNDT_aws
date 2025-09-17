#!/bin/bash

# NDT Manager Complete Setup Script
# Designed for /home/ubuntu/distributedNDT_aws directory structure
# Optimized for t3.xlarge EC2 instance with ec2-admin-root IAM role

set -e

echo "Starting NDT Manager complete setup from scratch..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[SETUP]${NC} $1"
}

# Ensure we're in the correct directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

print_header "Initializing NDT Manager setup in $(pwd)"

# Detect instance information
print_header "Detecting instance configuration..."
INSTANCE_TYPE=$(curl -s http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null || echo "unknown")
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "unknown")
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "unknown")
PRIVATE_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4 2>/dev/null || echo "unknown")
REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || echo "us-east-1")
AZ=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone 2>/dev/null || echo "unknown")

print_status "Instance Type: $INSTANCE_TYPE"
print_status "Instance ID: $INSTANCE_ID"
print_status "Region: $REGION"
print_status "Availability Zone: $AZ"
print_status "Public IP: $PUBLIC_IP"
print_status "Private IP: $PRIVATE_IP"

if [ "$INSTANCE_TYPE" = "t3.xlarge" ]; then
    print_status "✓ Perfect! Running on recommended t3.xlarge instance"
elif [[ "$INSTANCE_TYPE" == t3* ]]; then
    print_warning "Running on $INSTANCE_TYPE (recommended: t3.xlarge for optimal performance)"
else
    print_warning "Running on $INSTANCE_TYPE - performance may vary"
fi

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root. Please run as ubuntu user."
   print_error "Your IAM role provides the necessary AWS permissions."
   exit 1
fi

# Verify IAM role and AWS access
print_header "Verifying AWS access and IAM role..."
if aws sts get-caller-identity > /dev/null 2>&1; then
    ROLE_ARN=$(aws sts get-caller-identity --query Arn --output text 2>/dev/null || echo "unknown")
    print_status "✓ AWS access verified: $ROLE_ARN"
    
    if [[ $ROLE_ARN == *"ec2-admin-root"* ]]; then
        print_status "✓ Correct IAM role detected (ec2-admin-root)"
    else
        print_warning "IAM role name doesn't match expected 'ec2-admin-root'"
        print_warning "Continuing with current role, ensure it has EC2 full access"
    fi
else
    print_error "Cannot access AWS APIs. Please verify:"
    print_error "1. IAM role 'ec2-admin-root' is attached to this instance"
    print_error "2. The role has EC2 full access permissions"
    exit 1
fi

# Update system packages
print_header "Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# Install essential system dependencies
print_header "Installing essential system dependencies..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    git \
    curl \
    wget \
    vim \
    htop \
    iotop \
    ncdu \
    tree \
    jq \
    unzip \
    net-tools \
    tcpdump \
    nmap \
    iperf3 \
    bc \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release

# Install AWS CLI v2 (official method)
print_header "Installing AWS CLI v2..."
if ! command -v aws &> /dev/null; then
    print_status "Downloading and installing AWS CLI v2..."
    cd /tmp
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip -q awscliv2.zip
    sudo ./aws/install
    rm -rf aws awscliv2.zip
    cd "$SCRIPT_DIR"
    print_status "✓ AWS CLI v2 installed successfully"
else
    print_status "✓ AWS CLI is already installed"
fi

# Verify AWS CLI installation
AWS_VERSION=$(aws --version 2>&1 | head -1)
print_status "AWS CLI Version: $AWS_VERSION"

# Install and configure Docker
print_header "Installing and configuring Docker..."
if ! command -v docker &> /dev/null; then
    print_status "Installing Docker CE..."
    
    # Add Docker GPG key and repository
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # Add user to docker group
    sudo usermod -aG docker ubuntu
    
    # Configure Docker daemon for optimization
    sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3"
    },
    "default-ulimits": {
        "nofile": {
            "Name": "nofile",
            "Hard": 64000,
            "Soft": 64000
        }
    },
    "storage-driver": "overlay2",
    "max-concurrent-downloads": 10,
    "max-concurrent-uploads": 5,
    "live-restore": true
}
EOF
    
    sudo systemctl enable docker
    sudo systemctl start docker
    print_status "✓ Docker installed and configured"
else
    print_status "✓ Docker is already installed"
fi

# Install and configure Redis
print_header "Installing and configuring Redis..."
sudo apt-get install -y redis-server

# Configure Redis for NDT Manager
sudo tee /etc/redis/redis.conf > /dev/null <<EOF
# Redis configuration for NDT Manager
bind 127.0.0.1
port 6379
timeout 300
keepalive 60
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
dir /var/lib/redis
logfile /var/log/redis/redis-server.log
loglevel notice
EOF

sudo systemctl enable redis-server
sudo systemctl start redis-server
print_status "✓ Redis installed and configured"

# Install additional tools
print_header "Installing additional network and monitoring tools..."
sudo apt-get install -y \
    nginx \
    certbot \
    fail2ban \
    ufw \
    logrotate

# Create directory structure
print_header "Creating NDT Manager directory structure..."
mkdir -p {logs,configs,topologies,deployments,scripts,data,monitoring,backups,cache}
mkdir -p data/{instances,metrics,alerts,reports}
mkdir -p cache/{topologies,resources,deployments}
mkdir -p monitoring/{grafana,prometheus}

# Set up Python virtual environment
print_header "Setting up Python virtual environment..."
if [ -d "venv" ]; then
    print_status "Removing existing virtual environment..."
    rm -rf venv
fi

print_status "Creating new Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip and essential packages
print_status "Upgrading pip and installing build tools..."
pip install --upgrade pip wheel setuptools

# Install Python requirements
print_header "Installing Python requirements..."
if [ -f "requirements.txt" ]; then
    print_status "Installing from requirements.txt..."
    pip install -r requirements.txt
else
    print_status "Installing essential Python packages..."
    pip install \
        fastapi==0.104.1 \
        uvicorn[standard]==0.24.0 \
        boto3==1.34.0 \
        paramiko==3.3.1 \
        pyyaml==6.0.1 \
        pydantic==2.5.0 \
        python-multipart==0.0.6 \
        aiofiles==23.2.1 \
        redis==5.0.1 \
        psutil==5.9.6 \
        requests==2.31.0
fi

print_status "✓ Python environment configured"

# Set up configuration files
print_header "Setting up configuration files..."

# Copy main config if it exists
if [ -f "config.yaml" ]; then
    cp config.yaml configs/
    print_status "✓ Main configuration copied to configs/"
fi

# Create environment configuration
print_status "Creating environment configuration..."
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

# Performance Settings (optimized for $INSTANCE_TYPE)
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
REDIS_PASSWORD=

# Security Configuration
API_KEY_HEADER=X-API-Key
# API_KEY=your-secret-api-key-here

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

print_status "✓ Environment configuration created"

# Create systemd service
print_header "Creating systemd service..."
sudo tee /etc/systemd/system/ndt-manager.service > /dev/null <<EOF
[Unit]
Description=NDT Manager Service ($INSTANCE_TYPE optimized)
Documentation=https://github.com/your-repo/ndt-manager
After=network-online.target redis-server.service docker.service
Wants=network-online.target redis-server.service docker.service
Requires=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=$SCRIPT_DIR
Environment=PATH=$SCRIPT_DIR/venv/bin
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=NDT_INSTANCE_TYPE=$INSTANCE_TYPE
Environment=NDT_MANAGER_MODE=true

# Load environment variables
EnvironmentFile=$SCRIPT_DIR/.env

# Main service command
ExecStart=$SCRIPT_DIR/venv/bin/uvicorn ndt_manager:app --host 0.0.0.0 --port 8000 --workers 2
ExecReload=/bin/kill -HUP \$MAINPID

# Restart policy
Restart=always
RestartSec=10
StartLimitInterval=60
StartLimitBurst=3

# Resource limits (appropriate for $INSTANCE_TYPE)
LimitNOFILE=65536
LimitNPROC=32768
MemoryMax=12G
CPUQuota=300%

# Security settings
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$SCRIPT_DIR

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ndt-manager

[Install]
WantedBy=multi-user.target
EOF

print_status "✓ Systemd service created"

# Create management scripts
print_header "Creating management scripts..."

# Start script
cat > start.sh <<EOF
#!/bin/bash
# NDT Manager Startup Script

set -e

echo "Starting NDT Manager..."
cd "\$(dirname "\$0")"

# Source environment variables
source venv/bin/activate
export \$(cat .env | grep -v '^#' | xargs) 2>/dev/null || true

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
echo "Instance: $INSTANCE_TYPE in $REGION"
echo "Public URL: http://$PUBLIC_IP:8000"
echo "Documentation: http://$PUBLIC_IP:8000/docs"
echo ""

# Start the application
exec uvicorn ndt_manager:app \\
    --host 0.0.0.0 \\
    --port 8000 \\
    --workers 2 \\
    --log-level info \\
    --access-log \\
    --use-colors \\
    --reload-dir . \\
    --app-dir .
EOF

chmod +x start.sh

# Stop script
cat > stop.sh <<'EOF'
#!/bin/bash
echo "Stopping NDT Manager..."

# Stop via systemctl if running as service
if systemctl is-active ndt-manager >/dev/null 2>&1; then
    sudo systemctl stop ndt-manager
    echo "✓ Systemd service stopped"
fi

# Kill any remaining processes
if pgrep -f "uvicorn ndt_manager" >/dev/null; then
    pkill -f "uvicorn ndt_manager"
    sleep 2
    
    # Force kill if still running
    if pgrep -f "uvicorn ndt_manager" >/dev/null; then
        pkill -9 -f "uvicorn ndt_manager"
    fi
    echo "✓ Application processes stopped"
fi

echo "NDT Manager stopped"
EOF

chmod +x stop.sh

# Status script
cat > status.sh <<EOF
#!/bin/bash
echo "NDT Manager Status"
echo "================="
echo "Directory: $SCRIPT_DIR"
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
echo "Disk: \$(df -h $SCRIPT_DIR | awk 'NR==2{printf "Used: %s/%s (%s)", \$3,\$2,\$5}')"
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

# Health check script
cat > health_check.sh <<EOF
#!/bin/bash
echo "NDT Manager Health Check"
echo "======================="
echo "Timestamp: \$(date)"
echo "Instance: $INSTANCE_TYPE (\$HOSTNAME)"
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
    API_RESPONSE=\$(curl -s http://localhost:8000/health 2>/dev/null)
    if echo "\$API_RESPONSE" | jq -r '.status' 2>/dev/null | grep -q "healthy"; then
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
    CALLER_ARN=\$(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null)
    echo "   Identity: \$CALLER_ARN"
    
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
SSH_KEY=\${SSH_KEY_PATH:-~/.ssh/id_rsa}
if [ -f "\$SSH_KEY" ]; then
    echo "   ✓ SSH key exists at \$SSH_KEY"
    
    # Check key permissions
    KEY_PERMS=\$(stat -c %a "\$SSH_KEY" 2>/dev/null || echo "000")
    if [ "\$KEY_PERMS" = "600" ]; then
        echo "   ✓ SSH key permissions are correct"
    else
        echo "   ⚠ SSH key permissions should be 600"
        chmod 600 "\$SSH_KEY" 2>/dev/null && echo "   ✓ Fixed SSH key permissions" || echo "   ✗ Could not fix SSH key permissions"
        ((warnings++))
    fi
else
    echo "   ✗ SSH key not found at \$SSH_KEY"
    echo "     You'll need to add your SSH key for worker instance management"
    ((issues++))
fi

# Check Redis
echo "5. Checking Redis..."
if redis-cli ping >/dev/null 2>&1; then
    echo "   ✓ Redis is responding"
    
    # Check Redis memory usage
    REDIS_MEMORY=\$(redis-cli info memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\\r')
    echo "   Memory usage: \$REDIS_MEMORY"
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
        DOCKER_CONTAINERS=\$(docker ps -q | wc -l)
        echo "   Running containers: \$DOCKER_CONTAINERS"
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
        PYTHON_VERSION=\$(python --version 2>&1)
        echo "   \$PYTHON_VERSION"
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
CPU_USAGE=\$(top -bn1 2>/dev/null | grep "Cpu(s)" | sed 's/.*: *\\([0-9.]*\\)%*us.*/\\1/' | head -1)
MEMORY_USAGE=\$(free | awk 'NR==2{printf "%.1f", \$3*100/\$2}')
DISK_USAGE=\$(df $SCRIPT_DIR | awk 'NR==2{print \$5}' | sed 's/%//')

echo "   CPU Usage: \${CPU_USAGE}%"
echo "   Memory Usage: \${MEMORY_USAGE}%"
echo "   Disk Usage: \${DISK_USAGE}%"

# Check resource thresholds
if (( \$(echo "\$CPU_USAGE > 90" | bc -l 2>/dev/null || echo 0) )); then
    echo "   ⚠ High CPU usage"
    ((warnings++))
fi

if (( \$(echo "\$MEMORY_USAGE > 90" | bc -l 2>/dev/null || echo 0) )); then
    echo "   ⚠ High memory usage"
    ((warnings++))
fi

if [ "\$DISK_USAGE" -gt 90 ]; then
    echo "   ⚠ High disk usage"
    ((warnings++))
fi

# Summary
echo ""
echo "======================="
echo "Health Check Summary:"
echo "======================="
if [ \$issues -eq 0 ] && [ \$warnings -eq 0 ]; then
    echo "✓ Perfect! All checks passed"
    echo ""
    echo "🚀 NDT Manager is ready to use!"
    echo "   Start: ./start.sh"
    echo "   API: http://$PUBLIC_IP:8000"
    echo "   Docs: http://$PUBLIC_IP:8000/docs"
    exit 0
elif [ \$issues -eq 0 ]; then
    echo "⚠ Minor issues: \$warnings warning(s)"
    echo ""
    echo "NDT Manager should work but may have reduced functionality"
    echo "Review warnings above and fix if needed"
    exit 0
else
    echo "✗ Critical issues: \$issues error(s), \$warnings warning(s)"
    echo ""
    echo "Please fix the errors above before starting NDT Manager"
    exit 1
fi
EOF

chmod +x health_check.sh

# Test API script
cat > test_api.sh <<EOF
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
if HEALTH=\$(curl -s --connect-timeout 10 "http://localhost:8000/health" 2>/dev/null); then
    if echo "\$HEALTH" | jq . >/dev/null 2>&1; then
        echo "   ✓ Health endpoint responded with valid JSON"
        echo "\$HEALTH" | jq .
    else
        echo "   ⚠ Health endpoint responded but not valid JSON"
        echo "   Response: \$HEALTH"
    fi
else
    echo "   ✗ Health endpoint failed"
fi

echo ""

# Test resources endpoint
echo "2. Resources endpoint..."
if RESOURCES=\$(curl -s --connect-timeout 10 "http://localhost:8000/resources" 2>/dev/null); then
    if echo "\$RESOURCES" | jq . >/dev/null 2>&1; then
        echo "   ✓ Resources endpoint responded with valid JSON"
        INSTANCE_COUNT=\$(echo "\$RESOURCES" | jq '.instances | length' 2>/dev/null || echo 0)
        echo "   Managed instances: \$INSTANCE_COUNT"
    else
        echo "   ⚠ Resources endpoint responded but not valid JSON"
    fi
else
    echo "   ✗ Resources endpoint failed"
fi

echo ""

# Test deployments endpoint
echo "3. Deployments endpoint..."
if DEPLOYMENTS=\$(curl -s --connect-timeout 10 "http://localhost:8000/deployments" 2>/dev/null); then
    if echo "\$DEPLOYMENTS" | jq . >/dev/null 2>&1; then
        echo "   ✓ Deployments endpoint responded with valid JSON"
        DEPLOYMENT_COUNT=\$(echo "\$DEPLOYMENTS" | jq 'length' 2>/dev/null || echo 0)
        echo "   Active deployments: \$DEPLOYMENT_COUNT"
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
    echo "   📚 Visit: http://$PUBLIC_IP:8000/docs"
else
    echo "   ✗ API documentation not accessible"
fi

echo ""
echo "========================"
echo "✅ API Testing Complete"
echo ""
echo "🌐 Access your NDT Manager at:"
echo "   • API: http://$PUBLIC_IP:8000"
echo "   • Docs: http://$PUBLIC_IP:8000/docs"
echo "   • Health: http://$PUBLIC_IP:8000/health"
echo ""
echo "🔧 Management commands:"
echo "   • ./status.sh - Check status"
echo "   • ./health_check.sh - Full health check"
echo "   • python api_client.py health - Test with CLI client"
EOF

chmod +x test_api.sh

# Create quick deploy script for testing
cat > quick_deploy.sh <<'EOF'
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
EOF

chmod +x quick_deploy.sh

# System optimizations
print_header "Applying system optimizations..."

# File descriptor limits
if ! grep -q "NDT Manager optimizations" /etc/security/limits.conf; then
    sudo tee -a /etc/security/limits.conf > /dev/null <<EOF
# NDT Manager optimizations
ubuntu soft nofile 65536
ubuntu hard nofile 65536
ubuntu soft nproc 32768
ubuntu hard nproc 32768
EOF
    print_status "✓ File descriptor limits increased"
fi

# Network optimizations
if ! grep -q "NDT Manager network optimizations" /etc/sysctl.conf; then
    sudo tee -a /etc/sysctl.conf > /dev/null <<EOF
# NDT Manager network optimizations
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 65536 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_congestion_control = bbr
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
    sudo sysctl -p > /dev/null 2>&1
    print_status "✓ Network optimizations applied"
fi

# Set up log rotation
print_header "Configuring log rotation..."
sudo tee /etc/logrotate.d/ndt-manager > /dev/null <<EOF
$SCRIPT_DIR/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    copytruncate
    su ubuntu ubuntu
    maxsize 100M
    postrotate
        systemctl reload ndt-manager 2>/dev/null || true
    endscript
}
EOF

print_status "✓ Log rotation configured"

# Configure firewall (basic setup)
print_header "Configuring basic firewall..."
sudo ufw --force reset >/dev/null 2>&1
sudo ufw default deny incoming >/dev/null 2>&1
sudo ufw default allow outgoing >/dev/null 2>&1
sudo ufw allow ssh >/dev/null 2>&1
sudo ufw allow 8000/tcp comment 'NDT Manager API' >/dev/null 2>&1
sudo ufw --force enable >/dev/null 2>&1
print_status "✓ Firewall configured (SSH and API ports open)"

# Enable and configure systemd service
print_header "Enabling systemd service..."
sudo systemctl daemon-reload
sudo systemctl enable ndt-manager
print_status "✓ NDT Manager service enabled for auto-start"

# Create comprehensive documentation
print_header "Creating documentation..."

cat > QUICKSTART.md <<EOF
# NDT Manager Quick Start Guide

## Your Setup
- **Instance**: $INSTANCE_TYPE ($INSTANCE_ID)
- **Region**: $REGION ($AZ)
- **Directory**: $SCRIPT_DIR
- **Public IP**: $PUBLIC_IP
- **Private IP**: $PRIVATE_IP

## Instant Start
\`\`\`bash
# Quick deploy and test everything
./quick_deploy.sh

# Or manual start
./start.sh
\`\`\`

## Health & Status
\`\`\`bash
./health_check.sh    # Comprehensive health check
./status.sh          # Detailed status information
./test_api.sh        # Test all API endpoints
\`\`\`

## API Access
- **Main API**: http://$PUBLIC_IP:8000
- **Documentation**: http://$PUBLIC_IP:8000/docs
- **Health Check**: http://$PUBLIC_IP:8000/health

## Management Commands
\`\`\`bash
# Service control
./start.sh           # Start in foreground
./stop.sh            # Stop all processes
sudo systemctl start ndt-manager     # Start as system service
sudo systemctl status ndt-manager    # Check service status

# Using the CLI client
python api_client.py health                    # API health check
python api_client.py resources                 # View EC2 resources
python api_client.py deployments              # List deployments
python api_client.py deploy example_topology.json  # Deploy topology
python api_client.py monitor --interval 30    # Live monitoring
\`\`\`

## Example Topology Deployment
\`\`\`bash
# Start NDT Manager
./start.sh

# In another terminal, deploy the example
python api_client.py deploy example_topology.json

# Monitor the deployment
python api_client.py monitor
\`\`\`

## Troubleshooting
\`\`\`bash
# Check logs
tail -f logs/ndt-manager.log
sudo journalctl -u ndt-manager -f

# Reset and restart
./stop.sh
./start.sh

# Full system check
./health_check.sh
\`\`\`

## Configuration Files
- \`.env\` - Environment variables
- \`configs/config.yaml\` - Main configuration
- \`logs/\` - Application logs
- \`venv/\` - Python virtual environment

## Next Steps
1. Ensure your SSH key is available for worker instances
2. Update \`AWS_KEY_PAIR_NAME\` in .env if different from 'default-key'  
3. Test with the example topology
4. Create your own containerlab topologies
5. Scale to multiple worker instances

## Support
- Check health: \`./health_check.sh\`
- View status: \`./status.sh\`
- Test API: \`./test_api.sh\`
- Review logs in \`logs/\` directory
EOF

# Create a comprehensive README
cat > README.md <<EOF
# NDT Manager - Network Distribution Topology Manager

Automated containerlab topology deployment and management across AWS EC2 instances.

## Overview
NDT Manager automatically provisions, configures, and manages EC2 instances to run distributed containerlab topologies. It intelligently distributes network topologies across multiple instances based on resource requirements and connects them seamlessly.

## Architecture

### Manager Instance (This $INSTANCE_TYPE)
- Runs the main NDT Manager API server
- Orchestrates topology deployments
- Monitors all worker instances  
- Handles resource allocation and auto-scaling
- Provides web API and documentation

### Worker Instances (Auto-provisioned)
- Run containerlab topologies
- Automatically configured with Docker and containerlab
- Connected via secure tunnels for multi-instance topologies
- Auto-scaled based on topology requirements

## Features
- 🚀 **Auto-scaling**: Provisions EC2 instances based on topology requirements
- 🔗 **Network Integration**: Seamless connectivity between distributed topology components
- 📊 **Resource Monitoring**: Real-time CPU, memory, storage monitoring
- 🎯 **Cost Optimization**: Right-sizing instances and automatic cleanup
- 🛡️ **Security**: IAM roles, security groups, encrypted storage
- 📚 **API Documentation**: OpenAPI/Swagger docs at /docs endpoint
- 🔧 **Management Tools**: CLI client and web interface

## Quick Start
See [QUICKSTART.md](QUICKSTART.md) for immediate setup and usage.

## API Endpoints
- \`POST /deploy-topology\` - Deploy a containerlab topology
- \`GET /resources\` - Get EC2 resource utilization
- \`GET /deployments\` - List active deployments
- \`DELETE /topology/{name}\` - Destroy a topology
- \`GET /health\` - Health check

## Instance Types Supported
- **t3.medium** (2 vCPU, 4GB) - Small topologies (≤5 nodes)
- **t3.large** (2 vCPU, 8GB) - Medium topologies (≤8 nodes)
- **t3.xlarge** (4 vCPU, 16GB) - Large topologies (≤15 nodes)
- **t3.2xlarge** (8 vCPU, 32GB) - Very large topologies (≤25 nodes)
- **c5.xlarge** (4 vCPU, 8GB) - CPU-intensive workloads

## Configuration
- **Main config**: \`configs/config.yaml\`
- **Environment**: \`.env\`
- **Logs**: \`logs/\` directory
- **Data**: \`data/\` directory

## Management
\`\`\`bash
# Service management
sudo systemctl {start|stop|restart|status} ndt-manager

# Direct management  
./start.sh          # Start in foreground
./stop.sh           # Stop service
./status.sh         # Check status
./health_check.sh   # Health verification
./test_api.sh       # API testing

# Using CLI client
python api_client.py [command]
\`\`\`

## Requirements
- Ubuntu 24.04 LTS
- IAM role with EC2 full access (ec2-admin-root)
- SSH key pair for worker instance access
- Internet connectivity

## Installation
Run the setup script in your project directory:
\`\`\`bash
chmod +x setup.sh
./setup.sh
\`\`\`

## Directory Structure
\`\`\`
$SCRIPT_DIR/
├── ndt_manager.py           # Main application
├── resource_monitor.py      # EC2 monitoring
├── deployment_manager.py    # Topology deployment
├── instance_provisioner.py  # EC2 provisioning
├── api_client.py           # CLI client
├── config.yaml             # Main configuration
├── requirements.txt        # Python dependencies
├── example_topology.json   # Example topology
├── start.sh               # Start script
├── stop.sh                # Stop script  
├── status.sh              # Status check
├── health_check.sh        # Health verification
├── test_api.sh            # API testing
├── quick_deploy.sh        # Quick deployment
├── venv/                  # Python environment
├── logs/                  # Application logs
├── configs/               # Configuration files
└── data/                  # Runtime data
\`\`\`

## Security Considerations
- Uses IAM roles for AWS access (no hardcoded credentials)
- SSH key-based authentication to worker instances
- Security groups with minimal required access
- Encrypted EBS volumes
- Firewall configured for SSH and API access only

## Cost Management
- Automatic instance right-sizing
- Unused worker termination
- Resource usage monitoring
- Cost estimation for deployments

## Support & Troubleshooting
1. Run health check: \`./health_check.sh\`
2. Check status: \`./status.sh\`
3. Review logs: \`tail -f logs/ndt-manager.log\`
4. Test API: \`./test_api.sh\`
5. Verify AWS permissions and SSH keys

## Version
- NDT Manager v1.0
- Instance: $INSTANCE_TYPE in $REGION
- Setup Date: $(date)
- Python: $(python3 --version)
- Docker: $(docker --version 2>/dev/null | cut -d' ' -f3 | tr -d ',' || echo 'Not installed')

---
🚀 **Your NDT Manager is ready at http://$PUBLIC_IP:8000**
EOF

print_status "✓ Documentation created"

# Final system verification
print_header "Running final system verification..."

# Count successful checks
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
if [ -f ".env" ] && [ -f "configs/config.yaml" ]; then
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

# Final summary
print_status ""
print_status "======================================"
print_status "NDT Manager Setup Complete!"
print_status "======================================"
print_status ""
print_status "Setup Summary:"
print_status "✓ Directory: $SCRIPT_DIR"
print_status "✓ Instance: $INSTANCE_TYPE ($INSTANCE_ID)"  
print_status "✓ Region: $REGION ($AZ)"
print_status "✓ Public IP: $PUBLIC_IP"
print_status "✓ System checks: $CHECKS_PASSED/$TOTAL_CHECKS passed"
print_status ""

if [ $CHECKS_PASSED -eq $TOTAL_CHECKS ]; then
    print_status "🎉 Perfect! All checks passed."
    print_status ""
    print_status "🚀 Ready to start NDT Manager!"
elif [ $CHECKS_PASSED -ge 8 ]; then
    print_warning "⚠️  Most checks passed ($CHECKS_PASSED/$TOTAL_CHECKS)."
    print_warning "NDT Manager should work. Review any failures above."
    print_status ""
    print_status "🚀 You can proceed to start NDT Manager."
else
    print_error "❌ Several issues detected ($CHECKS_PASSED/$TOTAL_CHECKS passed)."
    print_error "Please resolve the failed checks before starting."
    print_status ""
fi

print_status "Next Steps:"
print_status "1. Run health check: ./health_check.sh"
print_status "2. Start NDT Manager: ./start.sh"
print_status "3. Test the API: ./test_api.sh"
print_status "4. Deploy example: python api_client.py deploy example_topology.json"
print_status ""
print_status "📚 Quick Start Guide: cat QUICKSTART.md"
print_status "📖 Full Documentation: cat README.md"
print_status ""
print_status "🌐 Your NDT Manager will be available at:"
print_status "   • API: http://$PUBLIC_IP:8000"
print_status "   • Documentation: http://$PUBLIC_IP:8000/docs"
print_status "   • Health: http://$PUBLIC_IP:8000/health"
print_status ""

# Create a final setup completion marker
echo "$(date): NDT Manager setup completed successfully" > .setup_complete
echo "Instance: $INSTANCE_TYPE ($INSTANCE_ID)" >> .setup_complete
echo "Region: $REGION ($AZ)" >> .setup_complete  
echo "Public IP: $PUBLIC_IP" >> .setup_complete
echo "Checks passed: $CHECKS_PASSED/$TOTAL_CHECKS" >> .setup_complete

echo -e "\n${GREEN}🎯 NDT Manager setup completed successfully!${NC}"
echo -e "${BLUE}💡 Run './quick_deploy.sh' to start and test everything at once${NC}"
echo -e "${BLUE}📋 Or follow the steps in QUICKSTART.md for manual control${NC}"