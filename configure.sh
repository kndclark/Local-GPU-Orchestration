#!/bin/bash
# configure.sh
# Wrapper script to run the GPU Orchestrator configuration tool (Linux)

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python is not installed or not in PATH."
    exit 1
fi

echo ">> Launching configuration tool..."
python3 scripts/configure.py
