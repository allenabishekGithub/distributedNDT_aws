# NDT Manager

Objective: Automated containerlab topology deployment and management of a Network Topology across multiple AWS EC2 instances.

## Overview
NDT Manager automatically provisions, configures, and manages EC2 instances to run distributed containerlab topologies. It intelligently distributes network topologies across multiple instances based on resource requirements and connects them seamlessly.

## Architecture

### Manager Instance (This )
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
- `POST /deploy-topology` - Deploy a containerlab topology
- `GET /resources` - Get EC2 resource utilization
- `GET /deployments` - List active deployments
- `DELETE /topology/{name}` - Destroy a topology
- `GET /health` - Health check

## Instance Types Supported
- **t3.medium** (2 vCPU, 4GB) - Small topologies (≤5 nodes)
- **t3.large** (2 vCPU, 8GB) - Medium topologies (≤8 nodes)
- **t3.xlarge** (4 vCPU, 16GB) - Large topologies (≤15 nodes)
- **t3.2xlarge** (8 vCPU, 32GB) - Very large topologies (≤25 nodes)
- **c5.xlarge** (4 vCPU, 8GB) - CPU-intensive workloads

## Configuration
- **Main config**: `configs/config.yaml`
- **Environment**: `.env`
- **Logs**: `logs/` directory
- **Data**: `data/` directory

## Management
```bash
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
```

## Requirements
- Ubuntu 24.04 LTS
- IAM role with EC2 full access (ec2-admin-root)
- SSH key pair for worker instance access
- Internet connectivity

## Installation
Run the setup script in your project directory:
```bash
chmod +x setup.sh
./setup.sh
```

## Directory Structure
```
/home/ubuntu/distributedNDT_aws/
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
```

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
1. Run health check: `./health_check.sh`
2. Check status: `./status.sh`
3. Review logs: `tail -f logs/ndt-manager.log`
4. Test API: `./test_api.sh`
5. Verify AWS permissions and SSH keys

## Version
- NDT Manager v1.0
- Instance:  in 
- Setup Date: Wed Sep 17 14:09:12 UTC 2025
- Python: Python 3.12.3
- Docker: 28.4.0

---
🚀 **Your NDT Manager is ready at http://:8000**
