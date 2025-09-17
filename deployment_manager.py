#!/usr/bin/env python3
"""
Deployment Manager for NDT
Handles the deployment and management of containerlab topologies across EC2 instances
"""

import asyncio
import json
import logging
import yaml
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import paramiko
import time
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class DeploymentTask:
    instance_id: str
    topology_name: str
    nodes: List[str]
    topology_config: Dict
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

class TopologyDistributor:
    """Handles the distribution logic for network topologies"""
    
    def __init__(self, max_nodes_per_instance: int = 10):
        self.max_nodes_per_instance = max_nodes_per_instance
    
    def distribute_nodes(self, topology: Dict, available_instances: List[str]) -> Dict[str, List[str]]:
        """
        Distribute topology nodes across available instances
        Uses a simple round-robin distribution for now
        """
        nodes = list(topology.get('topology', {}).get('nodes', {}).keys())
        
        if not nodes:
            return {}
        
        # Simple round-robin distribution
        distribution = {}
        instance_index = 0
        
        for i, node in enumerate(nodes):
            if i % self.max_nodes_per_instance == 0 and instance_index < len(available_instances):
                current_instance = available_instances[instance_index]
                if current_instance not in distribution:
                    distribution[current_instance] = []
                instance_index += 1
            else:
                current_instance = available_instances[(instance_index - 1) % len(available_instances)]
            
            distribution[current_instance].append(node)
        
        return distribution
    
    def create_partial_topology(self, original_topology: Dict, assigned_nodes: List[str], instance_id: str) -> Dict:
        """Create a partial topology configuration for a specific instance"""
        
        # Get original topology structure
        original_topo = original_topology.get('topology', {})
        original_nodes = original_topo.get('nodes', {})
        original_links = original_topo.get('links', [])
        
        # Filter nodes
        partial_nodes = {
            node: original_nodes[node] 
            for node in assigned_nodes 
            if node in original_nodes
        }
        
        # Filter links - only include links where both endpoints are in assigned nodes
        partial_links = []
        for link in original_links:
            endpoints = link.get('endpoints', [])
            if len(endpoints) >= 2:
                # Extract node names from endpoints (format: "node:interface")
                endpoint_nodes = [ep.split(':')[0] for ep in endpoints[:2]]
                if all(node in assigned_nodes for node in endpoint_nodes):
                    partial_links.append(link)
        
        # Create partial topology
        partial_topology = {
            'name': f"{original_topology.get('name', 'topology')}-{instance_id[-8:]}",
            'mgmt': original_topology.get('mgmt', {}),
            'topology': {
                'nodes': partial_nodes,
                'links': partial_links
            }
        }
        
        return partial_topology

class ContainerlabDeployer:
    """Handles containerlab deployment operations on EC2 instances"""
    
    def __init__(self, ssh_key_path: str, ssh_username: str = "ubuntu"):
        self.ssh_key_path = ssh_key_path
        self.ssh_username = ssh_username
    
    async def deploy_topology(self, instance_ip: str, topology_config: Dict, topology_name: str) -> bool:
        """Deploy a topology configuration to a specific instance"""
        try:
            # Connect via SSH
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=instance_ip,
                username=self.ssh_username,
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Create topology file
            topology_yaml = yaml.dump(topology_config, default_flow_style=False)
            topology_file = f"/opt/ndt/{topology_name}.clab.yml"
            
            # Upload topology file
            sftp = ssh.open_sftp()
            try:
                with sftp.open(topology_file, 'w') as f:
                    f.write(topology_yaml)
            finally:
                sftp.close()
            
            # Deploy with containerlab
            deploy_command = f"cd /opt/ndt && sudo containerlab deploy -t {topology_file} --reconfigure"
            
            stdin, stdout, stderr = ssh.exec_command(deploy_command)
            
            # Wait for command completion
            exit_status = stdout.channel.recv_exit_status()
            deploy_output = stdout.read().decode()
            deploy_errors = stderr.read().decode()
            
            ssh.close()
            
            if exit_status != 0:
                logger.error(f"Deployment failed on {instance_ip}: {deploy_errors}")
                return False
            
            logger.info(f"Successfully deployed {topology_name} to {instance_ip}")
            return True
            
        except Exception as e:
            logger.error(f"Error deploying to {instance_ip}: {e}")
            return False
    
    async def destroy_topology(self, instance_ip: str, topology_name: str) -> bool:
        """Destroy a topology on a specific instance"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=instance_ip,
                username=self.ssh_username,
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            destroy_command = f"cd /opt/ndt && sudo containerlab destroy -t {topology_name}.clab.yml --cleanup"
            
            stdin, stdout, stderr = ssh.exec_command(destroy_command)
            exit_status = stdout.channel.recv_exit_status()
            
            ssh.close()
            
            if exit_status != 0:
                logger.warning(f"Destroy command had non-zero exit status on {instance_ip}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error destroying topology on {instance_ip}: {e}")
            return False
    
    async def get_topology_status(self, instance_ip: str, topology_name: str) -> Dict:
        """Get the status of a deployed topology"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=instance_ip,
                username=self.ssh_username,
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Check if topology file exists
            stdin, stdout, stderr = ssh.exec_command(f"test -f /opt/ndt/{topology_name}.clab.yml && echo 'exists'")
            file_exists = stdout.read().decode().strip() == 'exists'
            
            if not file_exists:
                ssh.close()
                return {'status': 'not_deployed', 'containers': []}
            
            # Get containerlab status
            stdin, stdout, stderr = ssh.exec_command(f"cd /opt/ndt && sudo containerlab inspect -t {topology_name}.clab.yml --format json")
            inspect_output = stdout.read().decode()
            
            ssh.close()
            
            if inspect_output:
                try:
                    status_data = json.loads(inspect_output)
                    return {
                        'status': 'deployed',
                        'containers': status_data.get('containers', []),
                        'links': status_data.get('links', [])
                    }
                except json.JSONDecodeError:
                    return {'status': 'unknown', 'containers': []}
            
            return {'status': 'unknown', 'containers': []}
            
        except Exception as e:
            logger.error(f"Error getting topology status from {instance_ip}: {e}")
            return {'status': 'error', 'error': str(e)}

class NetworkConnector:
    """Handles network connectivity between distributed topology components"""
    
    def __init__(self):
        self.bridge_networks = {}
    
    async def setup_inter_instance_connectivity(self, deployment_info: Dict[str, List[str]], 
                                              ec2_client, ssh_key_path: str) -> bool:
        """Setup network connectivity between topology parts on different instances"""
        try:
            # Get instance IPs
            instance_ips = {}
            instance_ids = list(deployment_info.keys())
            
            if len(instance_ids) <= 1:
                # Single instance deployment, no inter-instance connectivity needed
                return True
            
            response = ec2_client.describe_instances(InstanceIds=instance_ids)
            
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    instance_id = instance['InstanceId']
                    instance_ips[instance_id] = {
                        'public_ip': instance.get('PublicIpAddress'),
                        'private_ip': instance.get('PrivateIpAddress')
                    }
            
            # Create GRE tunnels between instances for inter-connectivity
            tunnel_commands = []
            
            # Create mesh connectivity between all instances
            for i, instance_id_1 in enumerate(instance_ids):
                for j, instance_id_2 in enumerate(instance_ids[i+1:], i+1):
                    
                    ip1 = instance_ips[instance_id_1]['private_ip']
                    ip2 = instance_ips[instance_id_2]['private_ip']
                    
                    if not ip1 or not ip2:
                        continue
                    
                    # Create tunnel from instance 1 to instance 2
                    tunnel_name_1_2 = f"gre-{instance_id_2[-8:]}"
                    tunnel_name_2_1 = f"gre-{instance_id_1[-8:]}"
                    
                    # Commands for instance 1
                    cmd1 = f"""
sudo ip tunnel add {tunnel_name_1_2} mode gre remote {ip2} local {ip1}
sudo ip link set {tunnel_name_1_2} up
sudo ip addr add 192.168.{i+1}.1/24 dev {tunnel_name_1_2}
"""
                    
                    # Commands for instance 2
                    cmd2 = f"""
sudo ip tunnel add {tunnel_name_2_1} mode gre remote {ip1} local {ip2}
sudo ip link set {tunnel_name_2_1} up
sudo ip addr add 192.168.{i+1}.2/24 dev {tunnel_name_2_1}
"""
                    
                    tunnel_commands.append((instance_ips[instance_id_1]['public_ip'], cmd1))
                    tunnel_commands.append((instance_ips[instance_id_2]['public_ip'], cmd2))
            
            # Execute tunnel setup commands
            deployer = ContainerlabDeployer(ssh_key_path)
            
            for public_ip, command in tunnel_commands:
                if public_ip:
                    try:
                        ssh = paramiko.SSHClient()
                        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        
                        ssh.connect(
                            hostname=public_ip,
                            username='ubuntu',
                            key_filename=ssh_key_path,
                            timeout=30
                        )
                        
                        stdin, stdout, stderr = ssh.exec_command(command)
                        stdout.channel.recv_exit_status()
                        
                        ssh.close()
                        
                    except Exception as e:
                        logger.error(f"Error setting up tunnel on {public_ip}: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting up inter-instance connectivity: {e}")
            return False

class DeploymentOrchestrator:
    """Main orchestrator for topology deployments"""
    
    def __init__(self, ec2_client, ssh_key_path: str):
        self.ec2_client = ec2_client
        self.ssh_key_path = ssh_key_path
        self.distributor = TopologyDistributor()
        self.deployer = ContainerlabDeployer(ssh_key_path)
        self.connector = NetworkConnector()
        self.active_deployments = {}
    
    async def deploy_distributed_topology(self, topology: Dict, available_instances: List[str]) -> Dict:
        """Deploy a topology across multiple instances"""
        
        topology_name = topology.get('name', f'topology-{int(time.time())}')
        
        try:
            # Distribute nodes across instances
            distribution = self.distributor.distribute_nodes(topology, available_instances)
            
            if not distribution:
                raise Exception("No nodes to distribute or no available instances")
            
            # Get instance IPs
            instance_ips = await self._get_instance_ips(list(distribution.keys()))
            
            # Create deployment tasks
            deployment_tasks = []
            
            for instance_id, nodes in distribution.items():
                if instance_id not in instance_ips:
                    logger.error(f"No IP found for instance {instance_id}")
                    continue
                
                # Create partial topology for this instance
                partial_topology = self.distributor.create_partial_topology(
                    topology, nodes, instance_id
                )
                
                task = DeploymentTask(
                    instance_id=instance_id,
                    topology_name=partial_topology['name'],
                    nodes=nodes,
                    topology_config=partial_topology,
                    started_at=datetime.now()
                )
                
                deployment_tasks.append(task)
            
            # Deploy to all instances concurrently
            deployment_results = await asyncio.gather(
                *[self._deploy_to_instance(task, instance_ips[task.instance_id]) 
                  for task in deployment_tasks],
                return_exceptions=True
            )
            
            # Process results
            successful_deployments = 0
            failed_deployments = 0
            
            for i, result in enumerate(deployment_results):
                task = deployment_tasks[i]
                task.completed_at = datetime.now()
                
                if isinstance(result, Exception):
                    task.status = "failed"
                    task.error_message = str(result)
                    failed_deployments += 1
                elif result:
                    task.status = "completed"
                    successful_deployments += 1
                else:
                    task.status = "failed"
                    failed_deployments += 1
            
            # Setup inter-instance connectivity if multiple instances
            connectivity_setup = True
            if len(distribution) > 1:
                connectivity_setup = await self.connector.setup_inter_instance_connectivity(
                    distribution, self.ec2_client, self.ssh_key_path
                )
            
            # Store deployment info
            deployment_info = {
                'topology_name': topology_name,
                'status': 'success' if failed_deployments == 0 else 'partial',
                'total_instances': len(distribution),
                'successful_deployments': successful_deployments,
                'failed_deployments': failed_deployments,
                'distribution': distribution,
                'tasks': deployment_tasks,
                'connectivity_setup': connectivity_setup,
                'deployed_at': datetime.now()
            }
            
            self.active_deployments[topology_name] = deployment_info
            
            return deployment_info
            
        except Exception as e:
            logger.error(f"Error deploying distributed topology: {e}")
            raise
    
    async def _deploy_to_instance(self, task: DeploymentTask, instance_ip: str) -> bool:
        """Deploy a single task to an instance"""
        return await self.deployer.deploy_topology(
            instance_ip, task.topology_config, task.topology_name
        )
    
    async def _get_instance_ips(self, instance_ids: List[str]) -> Dict[str, str]:
        """Get IP addresses for instances"""
        try:
            response = self.ec2_client.describe_instances(InstanceIds=instance_ids)
            
            instance_ips = {}
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    instance_id = instance['InstanceId']
                    public_ip = instance.get('PublicIpAddress')
                    private_ip = instance.get('PrivateIpAddress')
                    
                    # Prefer public IP for SSH access
                    instance_ips[instance_id] = public_ip or private_ip
            
            return instance_ips
            
        except Exception as e:
            logger.error(f"Error getting instance IPs: {e}")
            return {}
    
    async def destroy_deployment(self, topology_name: str) -> bool:
        """Destroy a distributed topology deployment"""
        if topology_name not in self.active_deployments:
            logger.error(f"Deployment {topology_name} not found")
            return False
        
        deployment_info = self.active_deployments[topology_name]
        
        try:
            # Get instance IPs
            instance_ids = list(deployment_info['distribution'].keys())
            instance_ips = await self._get_instance_ips(instance_ids)
            
            # Destroy topology on each instance
            destroy_tasks = []
            for task in deployment_info['tasks']:
                if task.instance_id in instance_ips:
                    destroy_tasks.append(
                        self.deployer.destroy_topology(
                            instance_ips[task.instance_id], 
                            task.topology_name
                        )
                    )
            
            # Execute destruction concurrently
            await asyncio.gather(*destroy_tasks, return_exceptions=True)
            
            # Remove from active deployments
            del self.active_deployments[topology_name]
            
            return True
            
        except Exception as e:
            logger.error(f"Error destroying deployment {topology_name}: {e}")
            return False
    
    async def get_deployment_status(self, topology_name: str) -> Optional[Dict]:
        """Get the status of a deployment"""
        if topology_name not in self.active_deployments:
            return None
        
        deployment_info = self.active_deployments[topology_name]
        
        # Get current status from instances
        instance_ids = list(deployment_info['distribution'].keys())
        instance_ips = await self._get_instance_ips(instance_ids)
        
        status_tasks = []
        for task in deployment_info['tasks']:
            if task.instance_id in instance_ips:
                status_tasks.append(
                    self.deployer.get_topology_status(
                        instance_ips[task.instance_id],
                        task.topology_name
                    )
                )
        
        statuses = await asyncio.gather(*status_tasks, return_exceptions=True)
        
        # Update deployment info with current status
        for i, status in enumerate(statuses):
            if not isinstance(status, Exception):
                deployment_info['tasks'][i].status = status.get('status', 'unknown')
        
        return deployment_info