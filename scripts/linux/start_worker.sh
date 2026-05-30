#!/bin/bash
# start_worker.sh
# Starts the GPU orchestrator worker agent on Linux (SteamOS / ROG Ally X)

echo "Starting GPU Orchestrator Worker Agent..."

# Ensure we're in the right directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../.."



# Run the agent module using the venv if it exists
if [ -f ".venv/bin/python3" ]; then
    .venv/bin/python3 -m worker_agent.main
else
    python3 -m worker_agent.main
fi
