#!/usr/bin/env python3
"""
EC2 Instance Provisioner for NDT Manager
Handles creation, configuration, and management of EC2 instances
"""

import asyncio
import base64
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import boto3
import paramiko
from botocore.exceptions import ClientError, WaiterError

logger = logging.getLogger(__name__)

@dataclass
class InstanceRequest:
    cpu_cores: int
    memory_gb: float
    storage_gb: float
    estimated_containers: int
    purpose: str = "containerlab"
    tags: Optional[Dict[str, str]] = None

@dataclass
class ProvisionedInstance:
    instance_id: str
    instance_type: str
    public_ip: str
    private_ip: str
    region: str
    availability_zone: str
    launch_time: datetime
    tags: Dict[str, str]
    initialization_status: str
    ssh_ready: bool
    services_ready: bool

class EC2InstanceProvisioner:
    """Handles EC2 instance provisioning and configuration"""
    
    def __init__(self, 
                 region: str = 'us-east-1',
                 key_pair_name: str = 'default-key',
                 iam_instance_profile: str = 'ec2-admin-root',
                 ssh_key_path: str = '~/.ssh/id_rsa'):
        
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.ec2_resource = boto3.resource('ec2', region_name=region)
        self.region = region
        self.key_pair_name = key_pair_name
        self.iam_instance_profile = iam_instance_profile
        self.ssh_key_path = os.path.expanduser(ssh_key_path)
        
        # Instance type mapping based on requirements
        self.instance_type_map = {
            'micro': {
                'type': 't3.micro',
                'cpu': 2, 'memory': 1, 'max_containers': 2,
                'cost_per_hour': 0.0104
            },
            'small': {
                'type': 't3.small',
                'cpu': 2, 'memory': 2, 'max_containers': 3,
                'cost_per_hour': 0.0208
            },
            'medium': {
                'type': 't3.medium',
                'cpu': 2, 'memory': 4, 'max_containers': 5,
                'cost_per_hour': 0.0416
            },
            'large': {
                'type': 't3.large',
                'cpu': 2, 'memory': 8, 'max_containers': 8,
                'cost_per_hour': 0.0832
            },
            'xlarge': {
                'type': 't3.xlarge',
                'cpu': 4, 'memory': 16, 'max_containers': 15,
                'cost_per_hour': 0.1664
            },
            '2xlarge': {
                'type': 't3.2xlarge',
                'cpu': 8, 'memory': 32, 'max_containers': 25,
                'cost_per_hour': 0.3328
            },
            # Compute optimized for CPU-intensive containerlab workloads
            'c5_large': {
                'type': 'c5.large',
                'cpu': 2, 'memory': 4, 'max_containers': 6,
                'cost_per_hour': 0.085
            },
            'c5_xlarge': {
                'type': 'c5.xlarge',
                'cpu': 4, 'memory': 8, 'max_containers': 12,
                'cost_per_hour': 0.17
            },
            # Memory optimized for memory-intensive network devices
            'r5_large': {
                'type': 'r5.large',
                'cpu': 2, 'memory': 16, 'max_containers': 10,
                'cost_per_hour': 0.126
            },
            'r5_xlarge': {
                'type': 'r5.xlarge',
                'cpu': 4, 'memory': 32, 'max_containers': 20,
                'cost_per_hour': 0.252
            }
        }
    
    def select_instance_type(self, request: InstanceRequest) -> str:
        """Select the most appropriate instance type based on requirements"""
        
        # Find instances that meet minimum requirements
        suitable_types = []
        
        for size_name, specs in self.instance_type_map.items():
            if (specs['cpu'] >= request.cpu_cores and
                specs['memory'] >= request.memory_gb and
                specs['max_containers'] >= request.estimated_containers):
                
                # Calculate efficiency score (lower is better)
                cpu_overhead = specs['cpu'] - request.cpu_cores
                memory_overhead = specs['memory'] - request.memory_gb
                container_overhead = specs['max_containers'] - request.estimated_containers
                
                efficiency_score = (
                    cpu_overhead * 0.4 +
                    memory_overhead * 0.4 +
                    container_overhead * 0.2 +
                    specs['cost_per_hour'] * 10  # Weight cost heavily
                )
                
                suitable_types.append((size_name, specs['type'], efficiency_score))
        
        if not suitable_types:
            # Fallback to largest instance if nothing fits
            logger.warning(f"No instance type perfectly fits requirements: {request}")
            return self.instance_type_map['2xlarge']['type']
        
        # Sort by efficiency score and return the best match
        suitable_types.sort(key=lambda x: x[2])
        selected_type = suitable_types[0][1]
        
        logger.info(f"Selected instance type {selected_type} for requirements: "
                   f"CPU={request.cpu_cores}, Memory={request.memory_gb}GB, "
                   f"Containers={request.estimated_containers}")
        
        return selected_type
    
    async def provision_instance(self, request: InstanceRequest) -> ProvisionedInstance:
        """Provision a new EC2 instance with the specified requirements"""
        
        try:
            # Select appropriate instance type
            instance_type = self.select_instance_type(request)
            
            # Get latest Ubuntu AMI
            ami_id = await self._get_latest_ubuntu_ami()
            
            # Get or create security group
            security_group_id = await self._ensure_security_group()
            
            # Prepare user data script
            user_data = self._generate_user_data_script(request)
            
            # Prepare tags
            tags = {
                'Name': f'ndt-worker-{datetime.now().strftime("%Y%m%d-%H%M%S")}',
                'NDT-Managed': 'true',
                'NDT-Role': 'worker',
                'NDT-Purpose': request.purpose,
                'CreatedBy': 'ndt-manager',
                'CreatedAt': datetime.now().isoformat(),
                'RequestedCPU': str(request.cpu_cores),
                'RequestedMemory': str(request.memory_gb),
                'RequestedStorage': str(request.storage_gb),
                'EstimatedContainers': str(request.estimated_containers)
            }
            
            if request.tags:
                tags.update(request.tags)
            
            # Create instance
            response = self.ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                KeyName=self.key_pair_name,
                SecurityGroupIds=[security_group_id],
                IamInstanceProfile={'Name': self.iam_instance_profile},
                BlockDeviceMappings=[
                    {
                        'DeviceName': '/dev/sda1',
                        'Ebs': {
                            'VolumeSize': max(20, int(request.storage_gb)),
                            'VolumeType': 'gp3',
                            'Iops': 3000,
                            'Throughput': 125,
                            'DeleteOnTermination': True,
                            'Encrypted': True
                        }
                    }
                ],
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': [{'Key': k, 'Value': v} for k, v in tags.items()]
                    },
                    {
                        'ResourceType': 'volume',
                        'Tags': [{'Key': k, 'Value': v} for k, v in tags.items()]
                    }
                ],
                UserData=user_data,
                MetadataOptions={
                    'HttpTokens': 'required',
                    'HttpPutResponseHopLimit': 2,
                    'HttpEndpoint': 'enabled'
                }
            )
            
            instance = response['Instances'][0]
            instance_id = instance['InstanceId']
            
            logger.info(f"Created EC2 instance {instance_id} ({instance_type})")
            
            # Wait for instance to be running
            logger.info(f"Waiting for instance {instance_id} to be running...")
            waiter = self.ec2_client.get_waiter('instance_running')
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={'Delay': 15, 'MaxAttempts': 40}
            )
            
            # Get updated instance information
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = response['Reservations'][0]['Instances'][0]
            
            provisioned = ProvisionedInstance(
                instance_id=instance_id,
                instance_type=instance_type,
                public_ip=instance.get('PublicIpAddress', ''),
                private_ip=instance.get('PrivateIpAddress', ''),
                region=self.region,
                availability_zone=instance['Placement']['AvailabilityZone'],
                launch_time=instance['LaunchTime'].replace(tzinfo=None),
                tags=tags,
                initialization_status='running',
                ssh_ready=False,
                services_ready=False
            )
            
            # Wait for SSH and complete initialization
            await self._wait_for_initialization(provisioned)
            
            logger.info(f"Successfully provisioned and configured instance {instance_id}")
            
            return provisioned
            
        except Exception as e:
            logger.error(f"Error provisioning instance: {e}")
            raise
    
    async def _get_latest_ubuntu_ami(self) -> str:
        """Get the latest Ubuntu 24.04 LTS AMI"""
        try:
            response = self.ec2_client.describe_images(
                Filters=[
                    {'Name': 'name', 'Values': ['ubuntu/images/hvm-ssd/ubuntu-noble-24.04-amd64-server-*']},
                    {'Name': 'owner-alias', 'Values': ['amazon']},
                    {'Name': 'state', 'Values': ['available']},
                    {'Name': 'architecture', 'Values': ['x86_64']}
                ],
                Owners=['099720109477']  # Canonical
            )
            
            if not response['Images']:
                raise Exception("No Ubuntu 24.04 LTS AMI found")
            
            # Sort by creation date and get the latest
            images = sorted(response['Images'], key=lambda x: x['CreationDate'], reverse=True)
            ami_id = images[0]['ImageId']
            
            logger.info(f"Selected Ubuntu AMI: {ami_id}")
            return ami_id
            
        except Exception as e:
            logger.error(f"Error getting Ubuntu AMI: {e}")
            # Fallback to a known good AMI (update this periodically)
            return 'ami-0c7217cdde317cfec'
    
    async def _ensure_security_group(self) -> str:
        """Ensure security group exists and return its ID"""
        sg_name = 'ndt-worker-security-group'
        
        try:
            # Check if security group exists
            response = self.ec2_client.describe_security_groups(
                Filters=[{'Name': 'group-name', 'Values': [sg_name]}]
            )
            
            if response['SecurityGroups']:
                return response['SecurityGroups'][0]['GroupId']
            
            # Get default VPC
            vpc_response = self.ec2_client.describe_vpcs(
                Filters=[{'Name': 'isDefault', 'Values': ['true']}]
            )
            
            if not vpc_response['Vpcs']:
                raise Exception("No default VPC found")
            
            vpc_id = vpc_response['Vpcs'][0]['VpcId']
            
            # Create security group
            sg_response = self.ec2_client.create_security_group(
                GroupName=sg_name,
                Description='Security group for NDT worker instances',
                VpcId=vpc_id
            )
            
            sg_id = sg_response['GroupId']
            
            # Add inbound rules
            self.ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 22,
                        'ToPort': 22,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'SSH access'}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 80,
                        'ToPort': 80,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'HTTP'}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 443,
                        'ToPort': 443,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'HTTPS'}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 8080,
                        'ToPort': 8090,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'Management interfaces'}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 50051,
                        'ToPort': 50100,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'gRPC/gNMI'}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 161,
                        'ToPort': 162,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'SNMP'}]
                    },
                    {
                        'IpProtocol': 'tcp',
                        'FromPort': 830,
                        'ToPort': 830,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'NETCONF'}]
                    },
                    {
                        'IpProtocol': 'icmp',
                        'FromPort': -1,
                        'ToPort': -1,
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'ICMP ping'}]
                    },
                    {
                        'IpProtocol': 'gre',
                        'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'GRE tunnels for inter-instance connectivity'}]
                    }
                ]
            )
            
            logger.info(f"Created security group {sg_id}")
            return sg_id
            
        except Exception as e:
            logger.error(f"Error with security group: {e}")
            raise
    
    def _generate_user_data_script(self, request: InstanceRequest) -> str:
        """Generate user data script for instance initialization"""
        
        script = f"""#!/bin/bash
set -e

# Log all output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting NDT worker initialization at $(date)"

# Update system
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y

# Install essential packages
apt-get install -y \\
    curl \\
    wget \\
    git \\
    vim \\
    htop \\
    iotop \\
    net-tools \\
    tcpdump \\
    bridge-utils \\
    iptables \\
    python3 \\
    python3-pip \\
    python3-venv \\
    jq \\
    unzip \\
    software-properties-common \\
    apt-transport-https \\
    ca-certificates \\
    gnupg \\
    lsb-release

# Install Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Configure Docker
systemctl enable docker
systemctl start docker

# Add ubuntu user to docker group
usermod -aG docker ubuntu

# Install containerlab
bash -c "$(curl -sL https://get.containerlab.dev)"

# Verify containerlab installation
containerlab version

# Install additional networking tools
apt-get install -y \\
    iproute2 \\
    iputils-ping \\
    traceroute \\
    nmap \\
    iperf3 \\
    mtr-tiny

# Create working directories
mkdir -p /opt/ndt
mkdir -p /opt/ndt/topologies
mkdir -p /opt/ndt/logs
mkdir -p /opt/ndt/configs

# Set proper ownership
chown -R ubuntu:ubuntu /opt/ndt

# Install Python packages for NDT worker
pip3 install \\
    paramiko \\
    pyyaml \\
    requests \\
    psutil \\
    docker

# Create NDT worker service script
cat > /opt/ndt/worker.py << 'EOF'
#!/usr/bin/env python3
import time
import logging
import subprocess
import os
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/ndt/logs/worker.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    logger.info("NDT Worker started")
    
    while True:
        try:
            # Health check and maintenance tasks
            logger.info("Worker health check")
            
            # Check Docker status
            result = subprocess.run(['systemctl', 'is-active', 'docker'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("Docker service is not running")
                subprocess.run(['systemctl', 'restart', 'docker'])
            
            # Check disk space
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
            logger.info(f"Disk usage: {{result.stdout}}")
            
            time.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error(f"Worker error: {{e}}")
            time.sleep(60)

if __name__ == "__main__":
    main()
EOF

chmod +x /opt/ndt/worker.py

# Create systemd service for NDT worker
cat > /etc/systemd/system/ndt-worker.service << 'EOF'
[Unit]
Description=NDT Worker Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/ndt
ExecStart=/usr/bin/python3 /opt/ndt/worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start NDT worker service
systemctl daemon-reload
systemctl enable ndt-worker
systemctl start ndt-worker

# Configure kernel parameters for containerlab
cat >> /etc/sysctl.conf << 'EOF'
# NDT/Containerlab optimizations
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
kernel.pid_max=65536
vm.max_map_count=262144
EOF

sysctl -p

# Load required kernel modules
cat > /etc/modules-load.d/ndt.conf << 'EOF'
br_netfilter
ip_gre
ip6_gre
vxlan
EOF

modprobe br_netfilter
modprobe ip_gre
modprobe ip6_gre
modprobe vxlan

# Configure log rotation
cat > /etc/logrotate.d/ndt << 'EOF'
/opt/ndt/logs/*.log {{
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    copytruncate
}}
EOF

# Install monitoring tools
pip3 install psutil requests

# Create resource monitoring script
cat > /opt/ndt/monitor.py << 'EOF'
#!/usr/bin/env python3
import psutil
import json
import time
from datetime import datetime

def get_system_metrics():
    return {{
        'timestamp': datetime.now().isoformat(),
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory': psutil.virtual_memory()._asdict(),
        'disk': psutil.disk_usage('/')._asdict(),
        'load_avg': psutil.getloadavg(),
        'processes': len(psutil.pids()),
        'network': psutil.net_io_counters()._asdict()
    }}

if __name__ == "__main__":
    metrics = get_system_metrics()
    print(json.dumps(metrics, indent=2))
EOF

chmod +x /opt/ndt/monitor.py

# Set up automatic security updates
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

# Configure automatic cleanup
cat > /opt/ndt/cleanup.sh << 'EOF'
#!/bin/bash
# Clean up old Docker images and containers
docker system prune -f
docker image prune -a -f
# Clean up old logs
find /opt/ndt/logs -name "*.log" -mtime +7 -delete
find /var/log -name "*.log" -mtime +30 -delete
EOF

chmod +x /opt/ndt/cleanup.sh

# Add cleanup to crontab
echo "0 2 * * 0 /opt/ndt/cleanup.sh" | crontab -u ubuntu -

# Create initialization complete marker
touch /tmp/ndt-initialization-complete
echo "NDT worker initialization completed at $(date)" | tee -a /var/log/user-data.log

# Final system info
echo "=== System Information ===" | tee -a /var/log/user-data.log
uname -a | tee -a /var/log/user-data.log
docker --version | tee -a /var/log/user-data.log
containerlab version | tee -a /var/log/user-data.log
python3 --version | tee -a /var/log/user-data.log

echo "NDT worker initialization script completed successfully" | tee -a /var/log/user-data.log
"""
        
        return base64.b64encode(script.encode('utf-8')).decode('utf-8')
    
    async def _wait_for_initialization(self, instance: ProvisionedInstance, timeout: int = 600):
        """Wait for instance initialization to complete"""
        
        logger.info(f"Waiting for initialization of instance {instance.instance_id}")
        
        start_time = time.time()
        ssh_ready = False
        services_ready = False
        
        while time.time() - start_time < timeout:
            try:
                # Test SSH connectivity
                if not ssh_ready:
                    ssh_ready = await self._test_ssh_connectivity(instance.public_ip)
                    if ssh_ready:
                        logger.info(f"SSH is ready for {instance.instance_id}")
                        instance.ssh_ready = True
                
                # Test services
                if ssh_ready and not services_ready:
                    services_ready = await self._test_services_ready(instance.public_ip)
                    if services_ready:
                        logger.info(f"Services are ready for {instance.instance_id}")
                        instance.services_ready = True
                        instance.initialization_status = 'ready'
                        return
                
                await asyncio.sleep(15)
                
            except Exception as e:
                logger.debug(f"Initialization check failed for {instance.instance_id}: {e}")
                await asyncio.sleep(15)
        
        # Timeout reached
        logger.warning(f"Initialization timeout for {instance.instance_id}")
        instance.initialization_status = 'timeout'
    
    async def _test_ssh_connectivity(self, ip_address: str) -> bool:
        """Test SSH connectivity to instance"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=ip_address,
                username='ubuntu',
                key_filename=self.ssh_key_path,
                timeout=10,
                banner_timeout=10
            )
            
            # Test basic command
            stdin, stdout, stderr = ssh.exec_command('echo "ssh_test"')
            result = stdout.read().decode().strip()
            
            ssh.close()
            return result == "ssh_test"
            
        except Exception:
            return False
    
    async def _test_services_ready(self, ip_address: str) -> bool:
        """Test if required services are ready"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=ip_address,
                username='ubuntu',
                key_filename=self.ssh_key_path,
                timeout=10
            )
            
            # Check initialization marker
            stdin, stdout, stderr = ssh.exec_command('test -f /tmp/ndt-initialization-complete && echo "ready"')
            result = stdout.read().decode().strip()
            
            if result != "ready":
                ssh.close()
                return False
            
            # Check Docker
            stdin, stdout, stderr = ssh.exec_command('sudo docker info >/dev/null 2>&1 && echo "docker_ok"')
            docker_result = stdout.read().decode().strip()
            
            # Check containerlab
            stdin, stdout, stderr = ssh.exec_command('which containerlab >/dev/null 2>&1 && echo "clab_ok"')
            clab_result = stdout.read().decode().strip()
            
            # Check NDT worker service
            stdin, stdout, stderr = ssh.exec_command('systemctl is-active ndt-worker 2>/dev/null')
            worker_result = stdout.read().decode().strip()
            
            ssh.close()
            
            return (docker_result == "docker_ok" and 
                   clab_result == "clab_ok" and 
                   worker_result == "active")
            
        except Exception:
            return False
    
    async def terminate_instance(self, instance_id: str) -> bool:
        """Terminate an EC2 instance"""
        try:
            logger.info(f"Terminating instance {instance_id}")
            
            # Add termination tag
            self.ec2_client.create_tags(
                Resources=[instance_id],
                Tags=[
                    {'Key': 'NDT-Terminated', 'Value': 'true'},
                    {'Key': 'NDT-TerminatedAt', 'Value': datetime.now().isoformat()}
                ]
            )
            
            # Terminate instance
            response = self.ec2_client.terminate_instances(InstanceIds=[instance_id])
            
            # Wait for termination
            waiter = self.ec2_client.get_waiter('instance_terminated')
            waiter.wait(InstanceIds=[instance_id])
            
            logger.info(f"Successfully terminated instance {instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error terminating instance {instance_id}: {e}")
            return False
    
    async def scale_down_unused_instances(self, min_instances: int = 1) -> List[str]:
        """Scale down unused instances, keeping minimum number"""
        try:
            # Get all managed instances
            response = self.ec2_client.describe_instances(
                Filters=[
                    {'Name': 'tag:NDT-Managed', 'Values': ['true']},
                    {'Name': 'instance-state-name', 'Values': ['running']}
                ]
            )
            
            instances = []
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    instances.append({
                        'id': instance['InstanceId'],
                        'launch_time': instance['LaunchTime'],
                        'type': instance['InstanceType']
                    })
            
            if len(instances) <= min_instances:
                logger.info(f"Already at minimum instance count ({min_instances})")
                return []
            
            # Sort by launch time (oldest first) and check utilization
            instances.sort(key=lambda x: x['launch_time'])
            
            candidates_for_termination = []
            
            for instance in instances:
                # Check if instance has low utilization
                # This is a placeholder - you'd want to implement actual utilization checking
                if len(candidates_for_termination) < len(instances) - min_instances:
                    candidates_for_termination.append(instance['id'])
            
            # Terminate candidate instances
            terminated = []
            for instance_id in candidates_for_termination:
                if await self.terminate_instance(instance_id):
                    terminated.append(instance_id)
            
            return terminated
            
        except Exception as e:
            logger.error(f"Error scaling down instances: {e}")
            return []
    
    async def get_instance_cost_estimate(self, instance_type: str, hours: float = 24) -> float:
        """Get estimated cost for running an instance"""
        
        # Find instance type in our mapping
        for size_name, specs in self.instance_type_map.items():
            if specs['type'] == instance_type:
                return specs['cost_per_hour'] * hours
        
        # Fallback cost estimation
        cost_map = {
            't3.micro': 0.0104,
            't3.small': 0.0208,
            't3.medium': 0.0416,
            't3.large': 0.0832,
            't3.xlarge': 0.1664,
            't3.2xlarge': 0.3328
        }
        
        return cost_map.get(instance_type, 0.1) * hours
    
    def get_provisioning_summary(self) -> Dict:
        """Get summary of provisioning capabilities"""
        return {
            'supported_instance_types': list(self.instance_type_map.keys()),
            'region': self.region,
            'key_pair': self.key_pair_name,
            'iam_profile': self.iam_instance_profile,
            'instance_specs': self.instance_type_map
        }