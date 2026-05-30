#!/bin/bash
# setup.sh
# Automates the setup of the GPU Orchestrator Worker Agent on Linux

set -e

echo "=================================================="
echo " GPU Orchestrator Worker Agent Setup (Linux)      "
echo "=================================================="

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3 and try again."
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

# 2. Check for GPU hardware to determine dependencies
HAS_NVIDIA=false
HAS_AMD=false

if command -v nvidia-smi &> /dev/null; then
    HAS_NVIDIA=true
    echo "✓ NVIDIA GPU detected."
elif lspci | grep -i nvidia &> /dev/null; then
    HAS_NVIDIA=true
    echo "✓ NVIDIA GPU detected via lspci."
fi

if lspci | grep -i -E "vga|3d|display" | grep -i amd &> /dev/null; then
    HAS_AMD=true
    echo "✓ AMD GPU detected."
fi

if [ "$HAS_NVIDIA" = false ] && [ "$HAS_AMD" = false ]; then
    echo "ℹ No discrete GPU detected, or detection failed. Will install base dependencies."
fi

# 3. Create Virtual Environment
echo ""
echo "Creating virtual environment (.venv)..."
python3 -m venv .venv
source .venv/bin/activate

# 4. Install Dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip

if [ "$HAS_NVIDIA" = true ]; then
    echo "Installing base dependencies + NVIDIA (pynvml) support..."
    pip install -e .[nvidia]
else
    echo "Installing base dependencies (AMD sysfs support is built-in)..."
    pip install -e .
fi

# 5. Configure Environment Variables
echo ""
echo "=================================================="
echo " Configuration"
echo "=================================================="
echo "The worker needs the address of the Control Plane (e.g., 192.168.1.100:50051)."
echo "Press Enter to accept the default [localhost:50051]."
read -p "Orchestrator URL: " ORCH_URL

if [ -z "$ORCH_URL" ]; then
    ORCH_URL="localhost:50051"
fi

echo "ORCHESTRATOR_URL=\"$ORCH_URL\"" > .env
echo "✓ Configuration saved to .env"

echo ""
echo "=================================================="
echo " Setup Complete! ✨"
echo "=================================================="
echo "To start the worker agent, run:"
echo "  ./scripts/linux/start_worker.sh"
echo ""
