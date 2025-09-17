#!/usr/bin/env python3
"""
NDT Manager API Client
Simple client for interacting with the NDT Manager API
"""

import json
import requests
import argparse
import sys
from typing import Dict, Optional
import yaml

class NDTClient:
    """Client for NDT Manager API"""
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        
        if api_key:
            self.session.headers.update({'X-API-Key': api_key})
    
    def health_check(self) -> Dict:
        """Check API health"""
        response = self.session.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()
    
    def get_resources(self) -> Dict:
        """Get EC2 resource information"""
        response = self.session.get(f"{self.base_url}/resources")
        response.raise_for_status()
        return response.json()
    
    def get_deployments(self) -> Dict:
        """Get current deployments"""
        response = self.session.get(f"{self.base_url}/deployments")
        response.raise_for_status()
        return response.json()
    
    def deploy_topology(self, topology: Dict) -> Dict:
        """Deploy a containerlab topology"""
        response = self.session.post(
            f"{self.base_url}/deploy-topology",
            json=topology
        )
        response.raise_for_status()
        return response.json()
    
    def destroy_topology(self, topology_name: str) -> Dict:
        """Destroy a deployed topology"""
        response = self.session.delete(f"{self.base_url}/topology/{topology_name}")
        response.raise_for_status()
        return response.json()
    
    def deploy_from_file(self, file_path: str) -> Dict:
        """Deploy topology from a file"""
        try:
            with open(file_path, 'r') as f:
                if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                    topology = yaml.safe_load(f)
                else:
                    topology = json.load(f)
            
            return self.deploy_topology(topology)
            
        except Exception as e:
            raise Exception(f"Error loading topology file: {e}")

def print_json(data: Dict, indent: int = 2):
    """Pretty print JSON data"""
    print(json.dumps(data, indent=indent, default=str))

def print_resources_table(resources: Dict):
    """Print resources in table format"""
    instances = resources.get('instances', {})
    
    if not instances:
        print("No instances found")
        return
    
    # Header
    print(f"{'Instance ID':<20} {'Type':<12} {'State':<10} {'CPU%':<6} {'Memory%':<8} {'SSH':<5} {'Docker':<6}")
    print("-" * 75)
    
    # Instances
    for instance_id, info in instances.items():
        instance_type = info.get('instance_type', 'N/A')
        state = info.get('state', 'N/A')
        ssh_ok = '✓' if info.get('ssh_accessible', False) else '✗'
        docker_ok = '✓' if info.get('docker_running', False) else '✗'
        
        metrics = info.get('current_metrics')
        cpu_percent = f"{metrics.get('cpu_percent', 0):.1f}" if metrics else "N/A"
        memory_percent = f"{metrics.get('memory_percent', 0):.1f}" if metrics else "N/A"
        
        print(f"{instance_id:<20} {instance_type:<12} {state:<10} {cpu_percent:<6} {memory_percent:<8} {ssh_ok:<5} {docker_ok:<6}")

def print_deployments_table(deployments: Dict):
    """Print deployments in table format"""
    if not deployments:
        print("No deployments found")
        return
    
    # Header
    print(f"{'Topology Name':<25} {'Status':<10} {'Instances':<10} {'Deployed At':<20}")
    print("-" * 70)
    
    # Deployments
    for name, info in deployments.items():
        status = info.get('status', 'N/A')
        total_instances = info.get('total_instances', 0)
        deployed_at = info.get('timestamp', info.get('deployed_at', 'N/A'))
        
        if isinstance(deployed_at, str) and 'T' in deployed_at:
            deployed_at = deployed_at.split('T')[0] + ' ' + deployed_at.split('T')[1][:8]
        
        print(f"{name:<25} {status:<10} {total_instances:<10} {deployed_at:<20}")

def main():
    parser = argparse.ArgumentParser(description='NDT Manager API Client')
    parser.add_argument('--url', default='http://localhost:8000', help='NDT Manager API URL')
    parser.add_argument('--api-key', help='API key for authentication')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Health command
    subparsers.add_parser('health', help='Check API health')
    
    # Resources command
    resources_parser = subparsers.add_parser('resources', help='Get resource information')
    resources_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Deployments command
    deployments_parser = subparsers.add_parser('deployments', help='List deployments')
    deployments_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy topology')
    deploy_parser.add_argument('file', help='Topology file (JSON or YAML)')
    deploy_parser.add_argument('--wait', action='store_true', help='Wait for deployment to complete')
    
    # Destroy command
    destroy_parser = subparsers.add_parser('destroy', help='Destroy topology')
    destroy_parser.add_argument('name', help='Topology name')
    
    # Monitor command
    monitor_parser = subparsers.add_parser('monitor', help='Monitor resources continuously')
    monitor_parser.add_argument('--interval', type=int, default=30, help='Refresh interval in seconds')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        client = NDTClient(args.url, args.api_key)
        
        if args.command == 'health':
            result = client.health_check()
            print("✓ API is healthy")
            print_json(result)
        
        elif args.command == 'resources':
            result = client.get_resources()
            if args.json:
                print_json(result)
            else:
                print_resources_table(result)
        
        elif args.command == 'deployments':
            result = client.get_deployments()
            if args.json:
                print_json(result)
            else:
                print_deployments_table(result)
        
        elif args.command == 'deploy':
            print(f"Deploying topology from {args.file}...")
            result = client.deploy_from_file(args.file)
            
            if result.get('status') == 'success':
                print("✓ Topology deployed successfully")
            else:
                print("⚠ Topology deployment completed with issues")
            
            print_json(result)
            
            if args.wait:
                import time
                topology_name = result.get('deployment_info', {}).get('topology_name')
                if topology_name:
                    print(f"\nMonitoring deployment of {topology_name}...")
                    while True:
                        deployments = client.get_deployments()
                        if topology_name in deployments:
                            deployment = deployments[topology_name]
                            status = deployment.get('status', 'unknown')
                            print(f"Status: {status}")
                            
                            if status in ['success', 'failed']:
                                break
                        
                        time.sleep(10)
        
        elif args.command == 'destroy':
            print(f"Destroying topology {args.name}...")
            result = client.destroy_topology(args.name)
            print("✓ Topology destroyed")
            print_json(result)
        
        elif args.command == 'monitor':
            import time
            import os
            
            print(f"Monitoring resources (refresh every {args.interval}s, press Ctrl+C to stop)")
            
            try:
                while True:
                    # Clear screen
                    os.system('clear' if os.name == 'posix' else 'cls')
                    
                    print("NDT Manager Resource Monitor")
                    print("=" * 40)
                    
                    try:
                        resources = client.get_resources()
                        print_resources_table(resources)
                        
                        print(f"\nLast updated: {resources.get('timestamp', 'Unknown')}")
                        print(f"Next refresh in {args.interval} seconds...")
                        
                    except Exception as e:
                        print(f"Error fetching resources: {e}")
                    
                    time.sleep(args.interval)
                    
            except KeyboardInterrupt:
                print("\nMonitoring stopped")
    
    except requests.exceptions.ConnectionError:
        print(f"✗ Cannot connect to NDT Manager at {args.url}")
        print("Make sure the NDT Manager is running and accessible")
        sys.exit(1)
    
    except requests.exceptions.HTTPError as e:
        print(f"✗ API error: {e}")
        if e.response.status_code == 401:
            print("Check your API key")
        sys.exit(1)
    
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()