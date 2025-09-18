#!/usr/bin/env python3
"""
NDT (Network Distribution Topology) Manager
Main application for managing distributed containerlab topologies across EC2 instances
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import boto3
import paramiko
import yaml
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn
from botocore.exceptions import ClientError
from deployment_manager import NetworkConnector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Data models
class NetworkTopology(BaseModel):
    name: str
    mgmt: Optional[Dict] = None
    topology: Dict

    @property
    def nodes(self) -> Dict:
        """Extract nodes from topology structure"""
        return self.topology.get("nodes", {})

    @property
    def links(self) -> List[Dict]:
        """Extract links from topology structure"""
        return self.topology.get("links", [])


@dataclass
class EC2Resources:
    instance_id: str
    instance_type: str
    cpu_cores: int
    memory_gb: float
    storage_gb: float
    available_cpu: float
    available_memory_gb: float
    available_storage_gb: float
    running_processes: int
    region: str
    availability_zone: str
    public_ip: Optional[str]
    private_ip: str
    status: str


@dataclass
class ContainerlabRequirements:
    cpu_cores: int
    memory_gb: float
    storage_gb: float
    estimated_processes: int


class NDTManager:
    """Main NDT Manager class"""

    def __init__(self):
        self.ec2_client = boto3.client("ec2")
        self.ec2_resource = boto3.resource("ec2")
        self.ssh_key_path = os.path.expanduser(os.getenv("SSH_KEY_PATH", "~/.ssh/id_rsa"))
        self.managed_instances: Dict[str, Dict] = {}
        self.topology_deployments: Dict[str, Dict] = {}

        # EC2 instance specifications for different containerlab sizes
        self.instance_specs = {
            "small": {"instance_type": "t3.medium", "cpu": 2, "memory": 4, "storage": 20},
            "medium": {"instance_type": "t3.large", "cpu": 2, "memory": 8, "storage": 50},
            "large": {"instance_type": "t3.xlarge", "cpu": 4, "memory": 16, "storage": 100},
            "xlarge": {"instance_type": "t3.2xlarge", "cpu": 8, "memory": 32, "storage": 200},
        }

    async def poll_ec2_resources(self, instance_ids: Optional[List[str]] = None) -> Dict[str, EC2Resources]:
        """Poll EC2 instances for their current resource utilization"""
        try:
            if instance_ids:
                response = self.ec2_client.describe_instances(InstanceIds=instance_ids)
            else:
                response = self.ec2_client.describe_instances(
                    Filters=[
                        {"Name": "tag:NDT-Managed", "Values": ["true"]},
                        {"Name": "instance-state-name", "Values": ["running", "pending"]},
                    ]
                )

            resources: Dict[str, EC2Resources] = {}

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    instance_id = instance["InstanceId"]

                    try:
                        instance_type = instance["InstanceType"]
                        public_ip = instance.get("PublicIpAddress")
                        private_ip = instance.get("PrivateIpAddress")

                        specs = await self._get_instance_type_specs(instance_type)
                        usage = await self._poll_instance_usage(public_ip or private_ip)

                        resources[instance_id] = EC2Resources(
                            instance_id=instance_id,
                            instance_type=instance_type,
                            cpu_cores=specs["cpu"],
                            memory_gb=specs["memory"],
                            storage_gb=specs["storage"],
                            available_cpu=specs["cpu"] - usage["cpu_used"],
                            available_memory_gb=specs["memory"] - usage["memory_used_gb"],
                            available_storage_gb=specs["storage"] - usage["storage_used_gb"],
                            running_processes=usage["processes"],
                            region=instance["Placement"]["AvailabilityZone"][:-1],
                            availability_zone=instance["Placement"]["AvailabilityZone"],
                            public_ip=public_ip,
                            private_ip=private_ip,
                            status=instance["State"]["Name"],
                        )

                    except Exception as e:
                        logger.error(f"Error polling instance {instance_id}: {e}")
                        continue

            return resources

        except ClientError as e:
            logger.error(f"Error describing instances: {e}")
            return {}

    async def _get_instance_type_specs(self, instance_type: str) -> Dict:
        """Get EC2 instance type specifications"""
        try:
            response = self.ec2_client.describe_instance_types(InstanceTypes=[instance_type])
            instance_info = response["InstanceTypes"][0]

            return {
                "cpu": instance_info["VCpuInfo"]["DefaultVCpus"],
                "memory": instance_info["MemoryInfo"]["SizeInMiB"] / 1024,  # GB
                "storage": 20,  # default gp3 volume we provision
            }
        except Exception as e:
            logger.error(f"Error getting instance specs for {instance_type}: {e}")
            fallback_specs = {
                "t3.micro": {"cpu": 2, "memory": 1, "storage": 8},
                "t3.small": {"cpu": 2, "memory": 2, "storage": 20},
                "t3.medium": {"cpu": 2, "memory": 4, "storage": 20},
                "t3.large": {"cpu": 2, "memory": 8, "storage": 20},
                "t3.xlarge": {"cpu": 4, "memory": 16, "storage": 20},
                "t3.2xlarge": {"cpu": 8, "memory": 32, "storage": 20},
            }
            return fallback_specs.get(instance_type, {"cpu": 2, "memory": 4, "storage": 20})

    async def _poll_instance_usage(self, ip_address: str) -> Dict:
        """Poll actual resource usage from an EC2 instance via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            key_path = os.path.expanduser(self.ssh_key_path)

            ssh.connect(hostname=ip_address, username="ubuntu", key_filename=key_path, timeout=30)

            # CPU (very rough)
            stdin, stdout, stderr = ssh.exec_command("top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | sed 's/%us,//'")
            cpu_used = float(stdout.read().decode().strip() or 0) / 100

            # Memory used (GB)
            stdin, stdout, stderr = ssh.exec_command("free -g | awk 'NR==2{printf \"%.2f\", $3}'")
            memory_used = float(stdout.read().decode().strip() or 0)

            # Root FS used (GB)
            stdin, stdout, stderr = ssh.exec_command("df -BG / | awk 'NR==2{print $3}' | sed 's/G//'")
            storage_used = float(stdout.read().decode().strip() or 0)

            # Process count
            stdin, stdout, stderr = ssh.exec_command("ps aux | wc -l")
            processes = int(stdout.read().decode().strip() or 0)

            ssh.close()

            return {
                "cpu_used": cpu_used,
                "memory_used_gb": memory_used,
                "storage_used_gb": storage_used,
                "processes": processes,
            }

        except Exception as e:
            logger.error(f"Error polling instance usage for {ip_address}: {e}")
            return {"cpu_used": 0, "memory_used_gb": 0, "storage_used_gb": 0, "processes": 0}

    def analyze_containerlab_requirements(self, topology: NetworkTopology) -> ContainerlabRequirements:
        """Analyze containerlab topology to estimate resource requirements"""
        nodes = topology.nodes
        node_count = len(nodes)

        # Base estimates per node (very rough; adjust per kind)
        cpu_per_node = 0.5
        memory_per_node = 0.5
        storage_per_node = 2.0

        total_cpu = 0.0
        total_memory = 0.0
        total_storage = 10.0  # base

        for _, node_config in nodes.items():
            node_kind = node_config.get("kind", "linux")

            if node_kind in ["srl", "srlinux"]:
                cpu_per_node, memory_per_node, storage_per_node = 1.0, 2.0, 5.0
            elif node_kind in ["ceos", "arista_ceos"]:
                cpu_per_node, memory_per_node, storage_per_node = 0.5, 1.0, 3.0
            elif node_kind == "linux":
                cpu_per_node, memory_per_node, storage_per_node = 0.2, 0.5, 1.0

            total_cpu += cpu_per_node
            total_memory += memory_per_node
            total_storage += storage_per_node

        # Overhead
        total_cpu += 1.0
        total_memory += 1.0
        total_storage += 5.0

        estimated_processes = node_count * 5 + 10

        return ContainerlabRequirements(
            cpu_cores=int(total_cpu) + 1,
            memory_gb=total_memory,
            storage_gb=total_storage,
            estimated_processes=estimated_processes,
        )

    async def find_suitable_ec2(self, requirements: ContainerlabRequirements) -> Optional[str]:
        """Find an existing EC2 instance that can handle the requirements"""
        resources = await self.poll_ec2_resources()

        for instance_id, resource in resources.items():
            if (
                resource.available_cpu >= requirements.cpu_cores
                and resource.available_memory_gb >= requirements.memory_gb
                and resource.available_storage_gb >= requirements.storage_gb
                and resource.status == "running"
            ):
                return instance_id

        return None

    def determine_instance_size(self, requirements: ContainerlabRequirements) -> str:
        """Determine the appropriate EC2 instance size based on requirements"""
        for size, specs in self.instance_specs.items():
            if (
                specs["cpu"] >= requirements.cpu_cores
                and specs["memory"] >= requirements.memory_gb
                and specs["storage"] >= requirements.storage_gb
            ):
                return size

        return "xlarge"  # Fallback to largest size

    async def create_ec2_instance(self, requirements: ContainerlabRequirements) -> str:
        """Create a new EC2 instance with the required specifications"""
        size = self.determine_instance_size(requirements)
        specs = self.instance_specs[size]

        try:
            # Get the latest Ubuntu 24.04 LTS AMI
            ami_id = await self._get_ubuntu_ami()

            # Create the instance
            user_data_b64 = base64.b64encode(self._get_user_data_script().encode()).decode()
            response = self.ec2_client.run_instances(
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=specs["instance_type"],
                KeyName=os.getenv("AWS_KEY_PAIR_NAME", "default-key"),
                SecurityGroupIds=[self._get_or_create_security_group()],
                IamInstanceProfile={"Name": "ec2-admin-root"},
                BlockDeviceMappings=[
                    {
                        "DeviceName": "/dev/sda1",
                        "Ebs": {
                            "VolumeSize": specs["storage"],
                            "VolumeType": "gp3",
                            "DeleteOnTermination": True,
                        },
                    }
                ],
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": f"ndt-worker-{datetime.now().strftime('%Y%m%d-%H%M%S')}"},
                            {"Key": "NDT-Managed", "Value": "true"},
                            {"Key": "NDT-Role", "Value": "worker"},
                            {"Key": "CreatedBy", "Value": "ndt-manager"},
                        ],
                    }
                ],
                UserData=user_data_b64,
            )

            instance_id = response["Instances"][0]["InstanceId"]
            logger.info(f"Created EC2 instance {instance_id}")

            # Wait for instance to be running and status checks OK
            waiter = self.ec2_client.get_waiter("instance_running")
            waiter.wait(InstanceIds=[instance_id])
            waiter_ok = self.ec2_client.get_waiter("instance_status_ok")
            waiter_ok.wait(InstanceIds=[instance_id])

            # Wait for SSH to be available and configure the instance
            await self._wait_for_ssh_and_configure(instance_id)

            return instance_id

        except ClientError as e:
            logger.error(f"Error creating EC2 instance: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create EC2 instance: {e}")

    async def _get_ubuntu_ami(self) -> str:
        """Get the latest Ubuntu 24.04 LTS AMI ID"""
        try:
            response = self.ec2_client.describe_images(
                Filters=[
                    {"Name": "name", "Values": ["ubuntu/images/hvm-ssd/ubuntu-noble-24.04-amd64-server-*"]},
                    {"Name": "state", "Values": ["available"]},
                    {"Name": "architecture", "Values": ["x86_64"]},
                ],
                Owners=["099720109477"],  # Canonical
            )

            if not response.get("Images"):
                logger.error("No Ubuntu 24.04 AMIs found")
                # Fallbacks by region
                region_amis = {
                    "us-east-1": "ami-0c7217cdde317cfec",
                    "us-west-2": "ami-017fecd1353bcc96e",
                    "eu-central-1": "ami-02003f9f0fde924ea",
                    "eu-west-1": "ami-0c1c30571d2dae5c9",
                    "ap-southeast-1": "ami-047126e50991d067b",
                }
                current_region = self.ec2_client.meta.region_name
                fallback_ami = region_amis.get(current_region, region_amis["us-east-1"])
                logger.warning(f"Using fallback AMI {fallback_ami} for region {current_region}")
                return fallback_ami

            images = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
            ami_id = images[0]["ImageId"]
            logger.info(f"Selected Ubuntu AMI: {ami_id}")
            return ami_id

        except Exception as e:
            logger.error(f"Error getting Ubuntu AMI: {e}")
            region_amis = {
                "us-east-1": "ami-0c7217cdde317cfec",
                "us-west-2": "ami-017fecd1353bcc96e",
                "eu-central-1": "ami-02003f9f0fde924ea",
                "eu-west-1": "ami-0c1c30571d2dae5c9",
                "ap-southeast-1": "ami-047126e50991d067b",
            }
            current_region = self.ec2_client.meta.region_name
            fallback_ami = region_amis.get(current_region, region_amis["us-east-1"])
            logger.warning(f"Using fallback AMI {fallback_ami} for region {current_region}")
            return fallback_ami

    def _get_or_create_security_group(self) -> str:
        """Get or create the security group used by NDT worker EC2 instances.

        Rules:
          - Egress: allow all
          - Ingress:
              * SSH 22/tcp from SSH_CIDR (default 0.0.0.0/0)
              * ICMP from SSH_CIDR
              * VXLAN 4789/udp from this SG (self-reference)
              * GRE (protocol 47) from this SG (self-reference)
              * (optional) gRPC/gNMI 50051–50100/tcp from SSH_CIDR
        """
        from botocore.exceptions import ClientError

        sg_name = "ndt-worker-sg"
        ssh_cidr = os.getenv("SSH_CIDR", "0.0.0.0/0")
        vpc_id = self._get_default_vpc_id()

        try:
            # Find existing SG by name within the same VPC
            resp = self.ec2_client.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [sg_name]}, {"Name": "vpc-id", "Values": [vpc_id]}]
            )
            if resp.get("SecurityGroups"):
                return resp["SecurityGroups"][0]["GroupId"]

            # Create SG
            create = self.ec2_client.create_security_group(
                GroupName=sg_name,
                Description="Security group for NDT worker nodes (containerlab)",
                VpcId=vpc_id,
                TagSpecifications=[
                    {
                        "ResourceType": "security-group",
                        "Tags": [{"Key": "Name", "Value": sg_name}, {"Key": "Project", "Value": "NDT"}],
                    }
                ],
            )
            sg_id = create["GroupId"]

            # Egress allow all
            try:
                self.ec2_client.authorize_security_group_egress(
                    GroupId=sg_id,
                    IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "all egress"}]}],
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                    raise

            # Ingress basic rules
            ingress_rules = [
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": ssh_cidr, "Description": "SSH"}],
                },
                {
                    "IpProtocol": "icmp",
                    "FromPort": -1,
                    "ToPort": -1,
                    "IpRanges": [{"CidrIp": ssh_cidr, "Description": "ICMP"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 50051,
                    "ToPort": 50100,
                    "IpRanges": [{"CidrIp": ssh_cidr, "Description": "gRPC/gNMI"}],
                },
            ]
            for perm in ingress_rules:
                try:
                    self.ec2_client.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[perm])
                except ClientError as e:
                    if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                        raise

            # Self-referencing rules for VXLAN & GRE
            self_ref = [{"GroupId": sg_id}]
            tunnel_perms = [
                {"IpProtocol": "udp", "FromPort": 4789, "ToPort": 4789, "UserIdGroupPairs": self_ref},
                {"IpProtocol": "47", "FromPort": -1, "ToPort": -1, "UserIdGroupPairs": self_ref},
            ]
            try:
                self.ec2_client.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=tunnel_perms)
            except ClientError as e:
                if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                    raise

            logger.info(f"Created security group {sg_name} ({sg_id}) in VPC {vpc_id}")
            return sg_id

        except Exception as e:
            logger.error(f"Error creating/locating security group: {e}")
            raise

    def _get_default_vpc_id(self) -> str:
        """Get the default VPC ID"""
        try:
            response = self.ec2_client.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
            return response["Vpcs"][0]["VpcId"]
        except Exception as e:
            logger.error(f"Error getting default VPC: {e}")
            raise

    def _get_user_data_script(self) -> str:
        return r"""#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/ndt-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive

# Base packages
apt-get update -y
apt-get upgrade -y
apt-get install -y curl jq git ca-certificates python3-pip

# Docker (official installer)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
usermod -aG docker ubuntu || true

# Wait for Docker to be ready
timeout 180 bash -c 'until docker info >/dev/null 2>&1; do sleep 3; done'

# Containerlab
bash -c "$(curl -sL https://get.containerlab.dev)"
ln -sf "$(command -v containerlab || command -v clab)" /usr/local/bin/clab

# Optional GHCR login (provide GHCR_USER/GHCR_TOKEN via env if needed)
if [ -n "${GHCR_USER:-}" ] && [ -n "${GHCR_TOKEN:-}" ]; then
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin || true
fi

# GRE/VXLAN support and IP forwarding
modprobe ip_gre || true
modprobe vxlan || true
sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv6.conf.all.forwarding=1
sed -i '/^net\.ipv4\.ip_forward=/d' /etc/sysctl.conf
sed -i '/^net\.ipv6\.conf\.all\.forwarding=/d' /etc/sysctl.conf
printf '%s\n' 'net.ipv4.ip_forward=1' 'net.ipv6.conf.all.forwarding=1' >> /etc/sysctl.conf

# Workspace
mkdir -p /opt/ndt/topos /opt/ndt/logs /opt/ndt/configs
chown -R ubuntu:ubuntu /opt/ndt

# Mark success for readiness checks
touch /var/local/ndt_bootstrap_success
"""

    async def _wait_for_ssh_and_configure(self, instance_id: str):
        """Wait for SSH to be available and perform additional configuration"""
        try:
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = response["Reservations"][0]["Instances"][0]
            public_ip = instance.get("PublicIpAddress")

            if not public_ip:
                logger.warning(f"No public IP for instance {instance_id}")
                return

            max_attempts = 30
            for attempt in range(max_attempts):
                try:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                    key_path = os.path.expanduser(self.ssh_key_path)
                    ssh.connect(hostname=public_ip, username="ubuntu", key_filename=key_path, timeout=10)

                    # Check readiness file created by user-data
                    stdin, stdout, stderr = ssh.exec_command(
                        'test -f /var/local/ndt_bootstrap_success && echo "ready"'
                    )
                    result = stdout.read().decode().strip()

                    if result == "ready":
                        logger.info(f"Instance {instance_id} is ready")
                        ssh.close()
                        break

                    ssh.close()

                except Exception as e:
                    logger.debug(f"SSH attempt {attempt + 1} failed for {instance_id}: {e}")

                await asyncio.sleep(10)
            else:
                logger.error(f"Instance {instance_id} did not become ready within timeout")

        except Exception as e:
            logger.error(f"Error configuring instance {instance_id}: {e}")

    async def distribute_topology(self, topology: NetworkTopology) -> Dict[str, List[str]]:
        """Distribute topology across multiple EC2 instances"""
        requirements = self.analyze_containerlab_requirements(topology)
        node_count = len(topology.nodes)

        if node_count <= 5:
            instance_id = await self.find_suitable_ec2(requirements)
            if not instance_id:
                instance_id = await self.create_ec2_instance(requirements)
            return {instance_id: list(topology.nodes.keys())}

        # Larger topology: simple chunking by node count
        nodes_per_instance = 5
        node_list = list(topology.nodes.keys())
        distribution: Dict[str, List[str]] = {}

        for i in range(0, len(node_list), nodes_per_instance):
            batch_nodes = node_list[i : i + nodes_per_instance]
            batch_requirements = ContainerlabRequirements(
                cpu_cores=max(2, len(batch_nodes)),
                memory_gb=max(4, len(batch_nodes) * 1.5),
                storage_gb=max(20, len(batch_nodes) * 3),
                estimated_processes=len(batch_nodes) * 5,
            )

            instance_id = await self.find_suitable_ec2(batch_requirements)
            if not instance_id:
                instance_id = await self.create_ec2_instance(batch_requirements)

            distribution[instance_id] = batch_nodes

        return distribution

    async def deploy_topology_to_instance(
        self, instance_id: str, topology: NetworkTopology, nodes: List[str]
    ) -> bool:
        """Deploy a partial topology to a specific EC2 instance"""
        try:
            # Get instance details
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = response["Reservations"][0]["Instances"][0]
            public_ip = instance.get("PublicIpAddress")

            if not public_ip:
                raise Exception(f"No public IP for instance {instance_id}")

            # Build partial topology (only nodes assigned to this host + intra-host links)
            all_nodes = topology.nodes
            all_links = topology.links

            partial_topology_config = {
                "name": f"{topology.name}-{instance_id[-8:]}",
                "mgmt": topology.mgmt,
                "topology": {
                    "nodes": {node: all_nodes[node] for node in nodes if node in all_nodes},
                    "links": [
                        link
                        for link in all_links
                        if (
                            len(link.get("endpoints", [])) >= 2
                            and all(ep.split(":")[0] in nodes for ep in link["endpoints"][:2])
                        )
                    ],
                },
            }

            # Connect via SSH and deploy
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            key_path = os.path.expanduser(self.ssh_key_path)
            ssh.connect(hostname=public_ip, username="ubuntu", key_filename=key_path, timeout=30)

            # Create topology file
            topology_yaml = yaml.dump(partial_topology_config, default_flow_style=False)

            # Upload topology file
            sftp = ssh.open_sftp()
            topology_file = f"/opt/ndt/topos/{topology.name}-{instance_id[-8:]}".replace(" ", "_") + ".clab.yml"
            with sftp.open(topology_file, "w") as f:
                f.write(topology_yaml)
            sftp.close()

            # Deploy containerlab topology
            stdin, stdout, stderr = ssh.exec_command(f"cd /opt/ndt/topos && sudo containerlab deploy -t {topology_file}")
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode()
            err = stderr.read().decode()

            # Persist remote logs for later debugging
            try:
                sftp = ssh.open_sftp()
                with sftp.open(f"/opt/ndt/logs/clab-{topology.name}-{instance_id[-8:]}.log", "w") as f:
                    f.write(out + "\n--- STDERR ---\n" + err)
                sftp.close()
            except Exception as e:
                logger.warning(f"Could not write remote clab log: {e}")

            ssh.close()

            if exit_code != 0:
                logger.error(
                    f"containerlab failed on {instance_id} (code={exit_code}). "
                    f"See /opt/ndt/logs/clab-{topology.name}-{instance_id[-8:]}.log"
                )
                return False

            logger.info(f"Successfully deployed topology to {instance_id}")
            return True

        except Exception as e:
            logger.error(f"Error deploying topology to {instance_id}: {e}")
            return False


# FastAPI application
app = FastAPI(title="NDT Manager", version="1.0.0")
ndt_manager = NDTManager()


@app.post("/deploy-topology")
async def deploy_topology(topology: NetworkTopology, background_tasks: BackgroundTasks):
    """Deploy a network topology across EC2 instances"""
    try:
        # Analyze requirements & distribute
        requirements = ndt_manager.analyze_containerlab_requirements(topology)
        distribution = await ndt_manager.distribute_topology(topology)

        # Deploy to each instance
        deployment_tasks = [
            ndt_manager.deploy_topology_to_instance(instance_id, topology, nodes)
            for instance_id, nodes in distribution.items()
        ]
        results = await asyncio.gather(*deployment_tasks, return_exceptions=True)
        successful_deployments = sum(1 for r in results if r is True)

        # Cross-host connectivity (GRE/VXLAN)
        connectivity = {"attempted": False, "ok": True}
        if len(distribution) > 1 and successful_deployments >= 2:
            connector = NetworkConnector()
            connectivity["attempted"] = True
            key_path = os.path.expanduser(ndt_manager.ssh_key_path)
            ok = await connector.setup_inter_instance_connectivity(
                distribution, ndt_manager.ec2_client, key_path
            )
            connectivity["ok"] = bool(ok)

        deployment_info = {
            "topology_name": topology.name,
            "total_instances": len(distribution),
            "successful_deployments": successful_deployments,
            "distribution": distribution,
            "requirements": asdict(requirements),
            "timestamp": datetime.now().isoformat(),
            "connectivity": connectivity,
        }

        ndt_manager.topology_deployments[topology.name] = deployment_info

        return {
            "status": "success" if successful_deployments == len(distribution) else "partial",
            "deployment_info": deployment_info,
        }

    except Exception as e:
        logger.error(f"Error deploying topology: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/resources")
async def get_resources():
    """Get current resource utilization of all managed EC2 instances"""
    try:
        resources = await ndt_manager.poll_ec2_resources()
        return {"timestamp": datetime.now().isoformat(), "instances": {k: asdict(v) for k, v in resources.items()}}
    except Exception as e:
        logger.error(f"Error getting resources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/deployments")
async def get_deployments():
    """Get information about current topology deployments"""
    return ndt_manager.topology_deployments


@app.delete("/topology/{topology_name}")
async def destroy_topology(topology_name: str):
    """Destroy a deployed topology"""
    if topology_name not in ndt_manager.topology_deployments:
        raise HTTPException(status_code=404, detail="Topology not found")

    try:
        deployment_info = ndt_manager.topology_deployments[topology_name]

        # Destroy topology on each instance
        for instance_id in deployment_info["distribution"].keys():
            response = ndt_manager.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = response["Reservations"][0]["Instances"][0]
            public_ip = instance.get("PublicIpAddress")

            if public_ip:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                key_path = os.path.expanduser(ndt_manager.ssh_key_path)
                ssh.connect(hostname=public_ip, username="ubuntu", key_filename=key_path, timeout=30)

                stdin, stdout, stderr = ssh.exec_command(
                    f"cd /opt/ndt/topos && sudo containerlab destroy -t {topology_name}-{instance_id[-8:]}.clab.yml"
                )
                _ = stdout.channel.recv_exit_status()
                ssh.close()

        # Remove from deployments
        del ndt_manager.topology_deployments[topology_name]

        return {"status": "success", "message": f"Topology {topology_name} destroyed"}

    except Exception as e:
        logger.error(f"Error destroying topology: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
