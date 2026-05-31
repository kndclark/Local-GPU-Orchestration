#!/bin/bash
# run.sh
# One-click quick install and run script for the GPU Orchestrator Worker (Linux)

set -e

# Change to the directory containing this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=================================================="
echo " Starting One-Click Install & Run (Linux)"
echo "=================================================="

# Make the inner scripts executable just in case
chmod +x scripts/linux/setup.sh
chmod +x scripts/linux/start_worker.sh

SETUP_ARGS=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --force-nvidia) SETUP_ARGS="$SETUP_ARGS --force-nvidia"; shift ;;
        --url) SETUP_ARGS="$SETUP_ARGS --url $2"; shift; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
done

echo ">> Running setup..."
if ! ./scripts/linux/setup.sh $SETUP_ARGS; then
    echo "❌ Setup failed. Aborting."
    exit 1
fi

# 2. Run Worker
echo ">> Setup successful. Starting worker daemon..."
if ! ./scripts/linux/start_worker.sh; then
    echo "❌ Worker daemon crashed or failed to start."
    exit 1
fi
