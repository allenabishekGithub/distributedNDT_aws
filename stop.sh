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
