# NDT Manager Deployment Guide for t3.xlarge

## Overview
This guide walks you through deploying the NDT (Network Distribution Topology) Manager on your t3.xlarge EC2 instance with ec2-admin-root IAM role.

## Prerequisites Checklist

### ✅ EC2 Instance Requirements
- [x] t3.xlarge instance (4 vCPU, 16GB RAM)
- [x] Ubuntu 24.04 LTS
- [x] IAM role: ec2-admin-root (with full EC2 permissions)
- [x] Security group allowing SSH (port 22) and API (port 8000)
- [x] SSH key pair configured

### ✅ Network Requirements
- [x] Public IP address assigned
- [x] Internet gateway access
- [x] Default VPC with subnet

## Step-by-Step Deployment

### 1. Initial Setup

Connect to your t3.xlarge instance:
```bash
ssh -i your-key.pem ubuntu@your-instance-ip
```

Upload all the project files to your instance:
```bash
# Option A: Using SCP
scp -i your-key.pem -r ndt-manager/ ubuntu@your-instance-ip:~/

# Option B: Using git (if files are in a repository)
git clone your-repository-url ndt-manager

# Option C: Copy files individually
# Upload: ndt_manager.py, resource_monitor.py, deployment_manager.py, 
#         instance_provisioner.py, requirements.txt, config.yaml, setup.sh
```

### 2. Run the Setup Script

```bash
cd ~/ndt-manager
chmod +x setup.sh
./setup.sh
```

The setup script will:
- ✅ Verify your t3.xlarge instance type
- ✅ Check IAM role permissions
- ✅ Install all dependencies
- ✅ Configure Python environment
- ✅ Set up system optimizations
- ✅ Create systemd service
- ✅ Configure monitoring and logging

### 3. Configuration

After setup, review and update configuration files:

#### Update SSH Key Reference
```bash
# Edit the config file to match your SSH key
vim configs/config.yaml

# Update this line to match your key pair name:
# aws:
#   key_pair_name: "your-actual-key-pair-name"
```

#### Verify Environment
```bash
# Check environment configuration
cat .env

# Update any settings as needed
vim .env
```

### 4. Start the Service

#### Option A: Using systemd (Recommended)
```bash
sudo systemctl start ndt-manager
sudo systemctl enable ndt-manager
```

#### Option B: Direct startup
```bash
./start.sh
```

#### Option C: Quick test deployment
```bash
./quick_deploy.sh
```

### 5. Verify Installation

Run the comprehensive health check:
```bash
./health_check.sh
```

Expected output:
```
NDT Manager Health Check
=======================
✓ NDT Manager service is running
✓ API is responding
✓ AWS credentials are valid
✓ SSH key exists
=======================
✓ All checks passed
```

Check detailed status:
```bash
./status.sh
```

### 6. Test API Endpoints

#### Using curl:
```bash
# Health check
curl http://localhost:8000/health

# Get resources
curl http://localhost:8000/resources

# List deployments
curl http://localhost:8000/deployments
```

#### Using the CLI client:
```bash
# Health check
python api_client.py health

# View resources
python api_client.py resources

# Monitor continuously
python api_client.py monitor --interval 30
```

### 7. Deploy Your First Topology

#### Deploy the example topology:
```bash
python api_client.py deploy example_topology.json
```

#### Create a custom topology:
```bash
# Create a simple 2-router topology
cat > my_topology.json << EOF
{
  "name": "my-first-lab",
  "mgmt": {
    "network": "mgmt",
    "ipv4-subnet": "172.20.20.0/24"
  },
  "topology": {
    "nodes": {
      "router1": {
        "kind": "srl",
        "image": "ghcr.io/nokia/srlinux:latest",
        "mgmt-ipv4": "172.20.20.11"
      },
      "router2": {
        "kind": "srl",
        "image": "ghcr.io/nokia/srlinux:latest",
        "mgmt-ipv4": "172.20.20.12"
      }
    },
    "links": [
      {
        "endpoints": ["router1:e1-1", "router2:e1-1"]
      }
    ]
  }
}
EOF

# Deploy it
python api_client.py deploy my_topology.json
```

## Access Your NDT Manager

### Web Interface
- **API Documentation**: http://your-instance-ip:8000/docs
- **API Health**: http://your-instance-ip:8000/health
- **Resources**: http://your-instance-ip:8000/resources

### Command Line
```bash
# From your instance
python api_client.py [command]

# From remote machine (if API port is open)
python api_client.py --url http://your-instance-ip:8000 [command]
```

## Performance Expectations

### Your t3.xlarge Manager Can Handle:
- **Concurrent Deployments**: Up to 10 simultaneous
- **Worker Instances**: Manage up to 25 workers
- **Topology Size**: Unlimited (auto-distributed)
- **API Requests**: 100+ requests/minute
- **Resource Monitoring**: 50+ instances

### Typical Resource Usage:
- **CPU**: 20-40% during normal operations
- **Memory**: 4-8GB for manager + cache
- **Storage**: 2-5GB for logs and data
- **Network**: Moderate (monitoring + deployment)

## Troubleshooting

### Common Issues and Solutions

#### 1. Service Won't Start
```bash
# Check logs
sudo journalctl -u ndt-manager -f

# Check configuration
./health_check.sh

# Restart service
sudo systemctl restart ndt-manager
```

#### 2. AWS Permissions Issues
```bash
# Verify IAM role
aws sts get-caller-identity

# Check EC2 permissions
aws ec2 describe-instances --max-items 1
```

#### 3. Worker Instance Problems
```bash
# List managed instances
aws ec2 describe-instances --filters "Name=tag:NDT-Managed,Values=true"

# Check worker connectivity
python api_client.py resources
```

#### 4. High Resource Usage
```bash
# Monitor resources
./monitor.sh

# Check worker distribution
python api_client.py resources --json | jq '.instances | length'
```

#### 5. API Not Responding
```bash
# Check if service is running
systemctl status ndt-manager

# Check port binding
netstat -tlnp | grep 8000

# Test locally
curl -v http://localhost:8000/health
```

### Log Locations
- **Main application**: `logs/ndt-manager.log`
- **System service**: `sudo journalctl -u ndt-manager`
- **Health checks**: `logs/health.log`
- **Monitoring**: `logs/monitor.log`

## Maintenance

### Daily Operations
```bash
# Check system health
./health_check.sh

# Monitor resources
./status.sh

# View recent deployments
python api_client.py deployments
```

### Weekly Maintenance
```bash
# Create backup
./backup.sh

# Clean up old logs
find logs -name "*.log" -mtime +30 -delete

# Update system packages
sudo apt update && sudo apt upgrade -y
```

### Monthly Tasks
```bash
# Review resource usage patterns
grep "High.*usage" logs/monitor.log

# Optimize instance types based on usage
python api_client.py resources > monthly_usage_report.json

# Check for security updates
sudo unattended-upgrades --dry-run
```

## Security Best Practices

### 1. Network Security
- Keep API port (8000) restricted to trusted networks
- Use VPN or bastion host for remote access
- Monitor security group rules regularly

### 2. SSH Security  
- Use strong SSH keys (RSA 2048+ or Ed25519)
- Disable password authentication
- Rotate SSH keys periodically

### 3. AWS Security
- Use IAM roles instead of access keys when possible
- Monitor CloudTrail for unusual API activity
- Set up billing alerts for unexpected costs

### 4. Application Security
- Enable API key authentication in production
- Monitor application logs for suspicious activity
- Keep dependencies updated

## Cost Optimization

### Monitor Costs
```bash
# Check running instances
aws ec2 describe-instances --filters "Name=tag:NDT-Managed,Values=true" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,LaunchTime]' --output table

# Estimate daily costs
python -c "
costs = {'t3.medium': 0.0416, 't3.large': 0.0832, 't3.xlarge': 0.1664, 't3.2xlarge': 0.3328}
# Add your instance types and calculate
print('Daily cost estimate based on running instances')
"
```

### Optimization Tips
- Use smallest instance types that meet requirements
- Terminate unused worker instances promptly
- Schedule topology deployments during off-peak hours
- Consider spot instances for non-critical workloads

## Advanced Configuration

### Custom Instance Types
Edit `configs/config.yaml` to add custom instance configurations:
```yaml
instance_types:
  custom_compute:
    instance_type: "c5.4xlarge"
    cpu: 16
    memory: 32
    storage: 100
    max_nodes: 40
    cost_per_hour: 0.68
```

### Resource Thresholds
Adjust monitoring thresholds:
```yaml
resource_thresholds:
  cpu_threshold: 70    # Alert at 70% CPU
  memory_threshold: 75 # Alert at 75% memory
  storage_threshold: 85 # Alert at 85% storage
```

### Scaling Limits
Control auto-scaling behavior:
```yaml
deployment:
  max_nodes_per_instance: 15  # Nodes per worker
  max_concurrent_deployments: 8  # Parallel deployments
  worker_instance_default: "large"  # Default worker size
```

## Next Steps

### 1. Production Hardening
- Set up HTTPS with SSL certificates
- Configure API authentication
- Implement rate limiting
- Set up monitoring dashboards

### 2. Integration
- Connect to CI/CD pipelines
- Integrate with network automation tools
- Set up Slack/email notifications

### 3. Scaling
- Configure multi-region deployments
- Implement database backend for state
- Add load balancing for high availability

## Support

If you encounter issues:

1. **Check this guide** for common solutions
2. **Review logs** in the `logs/` directory  
3. **Run diagnostics** with `./health_check.sh`
4. **Verify AWS permissions** and connectivity
5. **Check instance resources** with `./status.sh`

Your t3.xlarge instance is now ready to orchestrate containerlab topologies across multiple EC2 instances! 🚀