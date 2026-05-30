#!/bin/bash
# start_worker.sh
# Starts the GPU orchestrator worker agent on Linux (SteamOS / ROG Ally X)

echo "Starting GPU Orchestrator Worker Agent..."

# Ensure we're in the right directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../.."

# Set the Orchestrator Control Plane URL here
# Example: export ORCHESTRATOR_URL="192.168.1.100:50051"
if [ -z "$ORCHESTRATOR_URL" ]; then
    echo "Warning: ORCHESTRATOR_URL not set, defaulting to localhost:50051"
fi

# Run the agent module using the venv if it exists
if [ -f ".venv/bin/python3" ]; then
    .venv/bin/python3 -m worker_agent.main
else
    python3 -m worker_agent.main
fi
