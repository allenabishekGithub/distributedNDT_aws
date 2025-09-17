#!/usr/bin/env python3
"""
Resource Monitor for NDT Manager
Monitors EC2 instances and their resource utilization
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import boto3
import paramiko
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

@dataclass
class SystemMetrics:
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    load_average: Tuple[float, float, float]
    process_count: int
    network_connections: int
    docker_containers: int
    docker_running: int

@dataclass
class InstanceResourceInfo:
    instance_id: str
    instance_type: str
    public_ip: Optional[str]
    private_ip: str
    region: str
    availability_zone: str
    state: str
    launch_time: datetime
    uptime_hours: float
    tags: Dict[str, str]
    
    # Resource specifications
    cpu_cores: int
    memory_total_gb: float
    storage_total_gb: float
    
    # Current utilization
    current_metrics: Optional[SystemMetrics]
    
    # Resource availability
    available_cpu_percent: float
    available_memory_gb: float
    available_storage_gb: float
    
    # Health status
    ssh_accessible: bool
    docker_running: bool
    containerlab_installed: bool
    last_checked: datetime

class SSHResourceCollector:
    """Collects resource information via SSH"""
    
    def __init__(self, ssh_key_path: str, username: str = "ubuntu", timeout: int = 30):
        self.ssh_key_path = os.path.expanduser(ssh_key_path)
        self.username = username
        self.timeout = timeout
    
    async def collect_metrics(self, ip_address: str) -> Optional[SystemMetrics]:
        """Collect system metrics from a remote instance via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=ip_address,
                username=self.username,
                key_filename=self.ssh_key_path,
                timeout=self.timeout
            )
            
            metrics = SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=await self._get_cpu_usage(ssh),
                memory_percent=0,
                memory_used_gb=0,
                memory_total_gb=0,
                disk_percent=0,
                disk_used_gb=0,
                disk_total_gb=0,
                load_average=(0, 0, 0),
                process_count=0,
                network_connections=0,
                docker_containers=0,
                docker_running=0
            )
            
            # Collect all metrics
            metrics.memory_percent, metrics.memory_used_gb, metrics.memory_total_gb = await self._get_memory_usage(ssh)
            metrics.disk_percent, metrics.disk_used_gb, metrics.disk_total_gb = await self._get_disk_usage(ssh)
            metrics.load_average = await self._get_load_average(ssh)
            metrics.process_count = await self._get_process_count(ssh)
            metrics.network_connections = await self._get_network_connections(ssh)
            metrics.docker_containers, metrics.docker_running = await self._get_docker_info(ssh)
            
            ssh.close()
            return metrics
            
        except Exception as e:
            logger.debug(f"Error collecting metrics from {ip_address}: {e}")
            return None
    
    async def _get_cpu_usage(self, ssh) -> float:
        """Get CPU usage percentage"""
        try:
            # Use top to get CPU usage
            stdin, stdout, stderr = ssh.exec_command(
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | sed 's/%us,//'"
            )
            result = stdout.read().decode().strip()
            return float(result) if result else 0.0
        except:
            return 0.0
    
    async def _get_memory_usage(self, ssh) -> Tuple[float, float, float]:
        """Get memory usage (percent, used GB, total GB)"""
        try:
            # Get memory info in GB
            stdin, stdout, stderr = ssh.exec_command(
                "free -g | awk 'NR==2{printf \"%.2f %.2f %.2f\", $3/$2*100, $3, $2}'"
            )
            result = stdout.read().decode().strip()
            if result:
                parts = result.split()
                return float(parts[0]), float(parts[1]), float(parts[2])
            return 0.0, 0.0, 0.0
        except:
            return 0.0, 0.0, 0.0
    
    async def _get_disk_usage(self, ssh) -> Tuple[float, float, float]:
        """Get disk usage (percent, used GB, total GB)"""
        try:
            stdin, stdout, stderr = ssh.exec_command(
                "df -BG / | awk 'NR==2{printf \"%.2f %.2f %.2f\", $3/$2*100, $3, $2}' | sed 's/G//g'"
            )
            result = stdout.read().decode().strip()
            if result:
                parts = result.split()
                return float(parts[0]), float(parts[1]), float(parts[2])
            return 0.0, 0.0, 0.0
        except:
            return 0.0, 0.0, 0.0
    
    async def _get_load_average(self, ssh) -> Tuple[float, float, float]:
        """Get system load average"""
        try:
            stdin, stdout, stderr = ssh.exec_command("uptime | awk -F'load average:' '{print $2}'")
            result = stdout.read().decode().strip()
            if result:
                loads = [float(x.strip().rstrip(',')) for x in result.split()]
                return tuple(loads[:3])
            return 0.0, 0.0, 0.0
        except:
            return 0.0, 0.0, 0.0
    
    async def _get_process_count(self, ssh) -> int:
        """Get total process count"""
        try:
            stdin, stdout, stderr = ssh.exec_command("ps aux | wc -l")
            result = stdout.read().decode().strip()
            return int(result) if result else 0
        except:
            return 0
    
    async def _get_network_connections(self, ssh) -> int:
        """Get active network connections count"""
        try:
            stdin, stdout, stderr = ssh.exec_command("netstat -an | grep ESTABLISHED | wc -l")
            result = stdout.read().decode().strip()
            return int(result) if result else 0
        except:
            return 0
    
    async def _get_docker_info(self, ssh) -> Tuple[int, int]:
        """Get Docker container information (total, running)"""
        try:
            # Total containers
            stdin, stdout, stderr = ssh.exec_command("sudo docker ps -a --format '{{.ID}}' | wc -l")
            total = int(stdout.read().decode().strip() or 0)
            
            # Running containers
            stdin, stdout, stderr = ssh.exec_command("sudo docker ps --format '{{.ID}}' | wc -l")
            running = int(stdout.read().decode().strip() or 0)
            
            return total, running
        except:
            return 0, 0
    
    async def check_service_status(self, ip_address: str) -> Dict[str, bool]:
        """Check status of required services"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                hostname=ip_address,
                username=self.username,
                key_filename=self.ssh_key_path,
                timeout=self.timeout
            )
            
            status = {
                'ssh_accessible': True,
                'docker_running': False,
                'containerlab_installed': False
            }
            
            # Check Docker service
            stdin, stdout, stderr = ssh.exec_command("sudo systemctl is-active docker")
            docker_status = stdout.read().decode().strip()
            status['docker_running'] = docker_status == "active"
            
            # Check containerlab installation
            stdin, stdout, stderr = ssh.exec_command("which containerlab")
            clab_path = stdout.read().decode().strip()
            status['containerlab_installed'] = bool(clab_path)
            
            ssh.close()
            return status
            
        except Exception as e:
            logger.debug(f"Error checking service status for {ip_address}: {e}")
            return {
                'ssh_accessible': False,
                'docker_running': False,
                'containerlab_installed': False
            }

class EC2ResourceMonitor:
    """Main EC2 resource monitoring class"""
    
    def __init__(self, region: str = 'us-east-1', ssh_key_path: str = '~/.ssh/id_rsa'):
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.ec2_resource = boto3.resource('ec2', region_name=region)
        self.ssh_collector = SSHResourceCollector(ssh_key_path)
        self.region = region
        self.instance_cache = {}
        self.last_update = None
        self.cache_ttl = 300  # 5 minutes
    
    async def get_all_managed_instances(self, force_refresh: bool = False) -> Dict[str, InstanceResourceInfo]:
        """Get information about all NDT-managed instances"""
        
        # Check cache validity
        if (not force_refresh and 
            self.last_update and 
            (datetime.now() - self.last_update).seconds < self.cache_ttl and
            self.instance_cache):
            return self.instance_cache
        
        try:
            # Query EC2 for managed instances
            response = self.ec2_client.describe_instances(
                Filters=[
                    {'Name': 'tag:NDT-Managed', 'Values': ['true']},
                    {'Name': 'instance-state-name', 'Values': ['running', 'stopped', 'stopping', 'pending']}
                ]
            )
            
            instances = {}
            
            for reservation in response['Reservations']:
                for instance_data in reservation['Instances']:
                    instance_id = instance_data['InstanceId']
                    
                    # Get instance specifications
                    specs = await self._get_instance_specifications(instance_data['InstanceType'])
                    
                    # Parse tags
                    tags = {tag['Key']: tag['Value'] for tag in instance_data.get('Tags', [])}
                    
                    # Calculate uptime
                    launch_time = instance_data['LaunchTime'].replace(tzinfo=None)
                    uptime_hours = (datetime.now() - launch_time).total_seconds() / 3600
                    
                    # Create instance info
                    instance_info = InstanceResourceInfo(
                        instance_id=instance_id,
                        instance_type=instance_data['InstanceType'],
                        public_ip=instance_data.get('PublicIpAddress'),
                        private_ip=instance_data.get('PrivateIpAddress'),
                        region=self.region,
                        availability_zone=instance_data['Placement']['AvailabilityZone'],
                        state=instance_data['State']['Name'],
                        launch_time=launch_time,
                        uptime_hours=uptime_hours,
                        tags=tags,
                        cpu_cores=specs['cpu'],
                        memory_total_gb=specs['memory'],
                        storage_total_gb=specs['storage'],
                        current_metrics=None,
                        available_cpu_percent=0,
                        available_memory_gb=0,
                        available_storage_gb=0,
                        ssh_accessible=False,
                        docker_running=False,
                        containerlab_installed=False,
                        last_checked=datetime.now()
                    )
                    
                    instances[instance_id] = instance_info
            
            # Collect metrics for running instances
            await self._collect_instance_metrics(instances)
            
            self.instance_cache = instances
            self.last_update = datetime.now()
            
            return instances
            
        except ClientError as e:
            logger.error(f"Error querying EC2 instances: {e}")
            return {}
    
    async def _collect_instance_metrics(self, instances: Dict[str, InstanceResourceInfo]):
        """Collect metrics for all running instances"""
        
        running_instances = [
            info for info in instances.values() 
            if info.state == 'running' and (info.public_ip or info.private_ip)
        ]
        
        if not running_instances:
            return
        
        # Collect metrics concurrently
        tasks = []
        for instance_info in running_instances:
            ip = instance_info.public_ip or instance_info.private_ip
            tasks.append(self._collect_single_instance_metrics(instance_info, ip))
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _collect_single_instance_metrics(self, instance_info: InstanceResourceInfo, ip: str):
        """Collect metrics for a single instance"""
        try:
            # Collect system metrics
            metrics = await self.ssh_collector.collect_metrics(ip)
            instance_info.current_metrics = metrics
            
            # Check service status
            service_status = await self.ssh_collector.check_service_status(ip)
            instance_info.ssh_accessible = service_status['ssh_accessible']
            instance_info.docker_running = service_status['docker_running']
            instance_info.containerlab_installed = service_status['containerlab_installed']
            
            # Calculate available resources
            if metrics:
                instance_info.available_cpu_percent = 100 - metrics.cpu_percent
                instance_info.available_memory_gb = instance_info.memory_total_gb - metrics.memory_used_gb
                instance_info.available_storage_gb = instance_info.storage_total_gb - metrics.disk_used_gb
            
            instance_info.last_checked = datetime.now()
            
        except Exception as e:
            logger.debug(f"Error collecting metrics for {instance_info.instance_id}: {e}")
            instance_info.ssh_accessible = False
    
    async def _get_instance_specifications(self, instance_type: str) -> Dict:
        """Get EC2 instance type specifications"""
        try:
            response = self.ec2_client.describe_instance_types(InstanceTypes=[instance_type])
            instance_info = response['InstanceTypes'][0]
            
            return {
                'cpu': instance_info['VCpuInfo']['DefaultVCpus'],
                'memory': instance_info['MemoryInfo']['SizeInMiB'] / 1024,  # Convert to GB
                'storage': 20  # Default EBS storage, will be overridden by actual disk size
            }
        except Exception as e:
            logger.debug(f"Error getting specs for {instance_type}: {e}")
            # Fallback specifications
            fallback_specs = {
                't3.micro': {'cpu': 2, 'memory': 1, 'storage': 8},
                't3.small': {'cpu': 2, 'memory': 2, 'storage': 20},
                't3.medium': {'cpu': 2, 'memory': 4, 'storage': 20},
                't3.large': {'cpu': 2, 'memory': 8, 'storage': 20},
                't3.xlarge': {'cpu': 4, 'memory': 16, 'storage': 20},
                't3.2xlarge': {'cpu': 8, 'memory': 32, 'storage': 20},
                'c5.large': {'cpu': 2, 'memory': 4, 'storage': 20},
                'c5.xlarge': {'cpu': 4, 'memory': 8, 'storage': 20},
                'm5.large': {'cpu': 2, 'memory': 8, 'storage': 20},
                'm5.xlarge': {'cpu': 4, 'memory': 16, 'storage': 20},
            }
            return fallback_specs.get(instance_type, {'cpu': 2, 'memory': 4, 'storage': 20})
    
    async def find_suitable_instances(self, 
                                    cpu_required: float, 
                                    memory_required: float, 
                                    storage_required: float,
                                    min_instances: int = 1) -> List[str]:
        """Find instances that can accommodate the resource requirements"""
        
        instances = await self.get_all_managed_instances()
        
        suitable_instances = []
        
        for instance_id, info in instances.items():
            if (info.state == 'running' and
                info.ssh_accessible and
                info.docker_running and
                info.containerlab_installed and
                info.available_cpu_percent >= (cpu_required / info.cpu_cores * 100) and
                info.available_memory_gb >= memory_required and
                info.available_storage_gb >= storage_required):
                
                suitable_instances.append(instance_id)
        
        return suitable_instances[:min_instances] if len(suitable_instances) >= min_instances else []
    
    async def get_instance_health_summary(self) -> Dict:
        """Get a summary of instance health across the fleet"""
        instances = await self.get_all_managed_instances()
        
        summary = {
            'total_instances': len(instances),
            'running_instances': 0,
            'healthy_instances': 0,
            'unhealthy_instances': 0,
            'stopped_instances': 0,
            'total_cpu_cores': 0,
            'total_memory_gb': 0,
            'available_cpu_cores': 0,
            'available_memory_gb': 0,
            'average_cpu_utilization': 0,
            'average_memory_utilization': 0,
            'instances_by_type': {},
            'instances_by_az': {},
            'health_issues': []
        }
        
        cpu_utilizations = []
        memory_utilizations = []
        
        for info in instances.values():
            # Count by state
            if info.state == 'running':
                summary['running_instances'] += 1
            elif info.state in ['stopped', 'stopping']:
                summary['stopped_instances'] += 1
            
            # Count by health
            if (info.state == 'running' and 
                info.ssh_accessible and 
                info.docker_running and 
                info.containerlab_installed):
                summary['healthy_instances'] += 1
            elif info.state == 'running':
                summary['unhealthy_instances'] += 1
            
            # Resource totals
            summary['total_cpu_cores'] += info.cpu_cores
            summary['total_memory_gb'] += info.memory_total_gb
            
            if info.state == 'running' and info.current_metrics:
                summary['available_cpu_cores'] += (info.available_cpu_percent / 100) * info.cpu_cores
                summary['available_memory_gb'] += info.available_memory_gb
                
                cpu_utilizations.append(info.current_metrics.cpu_percent)
                memory_utilizations.append(info.current_metrics.memory_percent)
            
            # Count by type and AZ
            instance_type = info.instance_type
            summary['instances_by_type'][instance_type] = summary['instances_by_type'].get(instance_type, 0) + 1
            
            az = info.availability_zone
            summary['instances_by_az'][az] = summary['instances_by_az'].get(az, 0) + 1
            
            # Check for health issues
            if info.state == 'running':
                if not info.ssh_accessible:
                    summary['health_issues'].append(f"{info.instance_id}: SSH not accessible")
                if not info.docker_running:
                    summary['health_issues'].append(f"{info.instance_id}: Docker not running")
                if not info.containerlab_installed:
                    summary['health_issues'].append(f"{info.instance_id}: Containerlab not installed")
        
        # Calculate averages
        if cpu_utilizations:
            summary['average_cpu_utilization'] = sum(cpu_utilizations) / len(cpu_utilizations)
        if memory_utilizations:
            summary['average_memory_utilization'] = sum(memory_utilizations) / len(memory_utilizations)
        
        return summary
    
    async def get_instance_metrics_history(self, instance_id: str, hours: int = 24) -> List[SystemMetrics]:
        """Get historical metrics for an instance (placeholder for future implementation)"""
        # This would typically involve storing metrics in a database
        # For now, return current metrics only
        instances = await self.get_all_managed_instances()
        
        if instance_id in instances and instances[instance_id].current_metrics:
            return [instances[instance_id].current_metrics]
        
        return []
    
    def serialize_instances(self, instances: Dict[str, InstanceResourceInfo]) -> Dict:
        """Serialize instance information for JSON response"""
        serialized = {}
        
        for instance_id, info in instances.items():
            serialized[instance_id] = {
                'instance_id': info.instance_id,
                'instance_type': info.instance_type,
                'public_ip': info.public_ip,
                'private_ip': info.private_ip,
                'region': info.region,
                'availability_zone': info.availability_zone,
                'state': info.state,
                'launch_time': info.launch_time.isoformat(),
                'uptime_hours': round(info.uptime_hours, 2),
                'tags': info.tags,
                'cpu_cores': info.cpu_cores,
                'memory_total_gb': round(info.memory_total_gb, 2),
                'storage_total_gb': round(info.storage_total_gb, 2),
                'available_cpu_percent': round(info.available_cpu_percent, 2),
                'available_memory_gb': round(info.available_memory_gb, 2),
                'available_storage_gb': round(info.available_storage_gb, 2),
                'ssh_accessible': info.ssh_accessible,
                'docker_running': info.docker_running,
                'containerlab_installed': info.containerlab_installed,
                'last_checked': info.last_checked.isoformat(),
                'current_metrics': asdict(info.current_metrics) if info.current_metrics else None
            }
        
        return serialized

class ResourceAlertManager:
    """Manages resource-based alerts and notifications"""
    
    def __init__(self, 
                 cpu_threshold: float = 80.0,
                 memory_threshold: float = 80.0,
                 disk_threshold: float = 90.0):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.disk_threshold = disk_threshold
        self.alert_history = []
    
    def check_alerts(self, instances: Dict[str, InstanceResourceInfo]) -> List[Dict]:
        """Check for resource alerts across instances"""
        alerts = []
        current_time = datetime.now()
        
        for instance_id, info in instances.items():
            if not info.current_metrics or info.state != 'running':
                continue
            
            metrics = info.current_metrics
            
            # CPU alerts
            if metrics.cpu_percent > self.cpu_threshold:
                alerts.append({
                    'type': 'high_cpu',
                    'instance_id': instance_id,
                    'instance_type': info.instance_type,
                    'severity': 'warning' if metrics.cpu_percent < 95 else 'critical',
                    'value': metrics.cpu_percent,
                    'threshold': self.cpu_threshold,
                    'message': f"High CPU usage: {metrics.cpu_percent:.1f}%",
                    'timestamp': current_time
                })
            
            # Memory alerts
            if metrics.memory_percent > self.memory_threshold:
                alerts.append({
                    'type': 'high_memory',
                    'instance_id': instance_id,
                    'instance_type': info.instance_type,
                    'severity': 'warning' if metrics.memory_percent < 95 else 'critical',
                    'value': metrics.memory_percent,
                    'threshold': self.memory_threshold,
                    'message': f"High memory usage: {metrics.memory_percent:.1f}%",
                    'timestamp': current_time
                })
            
            # Disk alerts
            if metrics.disk_percent > self.disk_threshold:
                alerts.append({
                    'type': 'high_disk',
                    'instance_id': instance_id,
                    'instance_type': info.instance_type,
                    'severity': 'warning' if metrics.disk_percent < 98 else 'critical',
                    'value': metrics.disk_percent,
                    'threshold': self.disk_threshold,
                    'message': f"High disk usage: {metrics.disk_percent:.1f}%",
                    'timestamp': current_time
                })
            
            # Service health alerts
            if not info.ssh_accessible:
                alerts.append({
                    'type': 'ssh_unreachable',
                    'instance_id': instance_id,
                    'instance_type': info.instance_type,
                    'severity': 'critical',
                    'message': "SSH not accessible",
                    'timestamp': current_time
                })
            
            if not info.docker_running:
                alerts.append({
                    'type': 'docker_down',
                    'instance_id': instance_id,
                    'instance_type': info.instance_type,
                    'severity': 'critical',
                    'message': "Docker service not running",
                    'timestamp': current_time
                })
        
        # Store alerts in history
        self.alert_history.extend(alerts)
        
        # Keep only recent alerts (last 24 hours)
        cutoff_time = current_time - timedelta(hours=24)
        self.alert_history = [
            alert for alert in self.alert_history 
            if alert['timestamp'] > cutoff_time
        ]
        
        return alerts