# NDT Manager Quick Start Guide

## Your Setup
- **Instance**:  ()
- **Region**:  ()
- **Directory**: /home/ubuntu/distributedNDT_aws
- **Public IP**: 
- **Private IP**: 

## Instant Start
```bash
# Quick deploy and test everything
./quick_deploy.sh

# Or manual start
./start.sh
```

## Health & Status
```bash
./health_check.sh    # Comprehensive health check
./status.sh          # Detailed status information
./test_api.sh        # Test all API endpoints
```

## API Access
- **Main API**: http://:8000
- **Documentation**: http://:8000/docs
- **Health Check**: http://:8000/health

## Management Commands
```bash
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
```

## Example Topology Deployment
```bash
# Start NDT Manager
./start.sh

# In another terminal, deploy the example
python api_client.py deploy example_topology.json

# Monitor the deployment
python api_client.py monitor
```

## Troubleshooting
```bash
# Check logs
tail -f logs/ndt-manager.log
sudo journalctl -u ndt-manager -f

# Reset and restart
./stop.sh
./start.sh

# Full system check
./health_check.sh
```

## Configuration Files
- `.env` - Environment variables
- `configs/config.yaml` - Main configuration
- `logs/` - Application logs
- `venv/` - Python virtual environment

## Next Steps
1. Ensure your SSH key is available for worker instances
2. Update `AWS_KEY_PAIR_NAME` in .env if different from 'default-key'  
3. Test with the example topology
4. Create your own containerlab topologies
5. Scale to multiple worker instances

## Support
- Check health: `./health_check.sh`
- View status: `./status.sh`
- Test API: `./test_api.sh`
- Review logs in `logs/` directory
