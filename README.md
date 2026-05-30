# GPU Orchestrator

![CI/CD Pipeline](https://github.com/kndclark/Local-GPU-Orchestration/actions/workflows/ci.yml/badge.svg)

A distributed, performance-aware GPU workload orchestrator designed for heterogeneous clusters.

## Architecture

*   **Control Plane:** FastAPI web server and SQLite database managing nodes, hardware telemetry, and jobs.
*   **Worker Agents:** Lightweight daemon running on local endpoints (Desktop, Steam Deck, ROG Ally X) that auto-detects GPU hardware via a zero-dependency Hardware Abstraction Layer (HAL).
*   **gRPC Protocol:** Fast, typed bidirectional communication for node registration, rich telemetry heartbeats, and job dispatch.

## Supported Hardware

The worker agent's HAL automatically detects and normalizes telemetry for:
*   **NVIDIA GPUs:** via `pynvml` (Windows/Linux)
*   **AMD GPUs:** via Linux sysfs (zero dependencies, works out-of-the-box on SteamOS)
*   **Simulated Backend:** for CI/CD and development without hardware

## Deployment & Setup

### Quick Start (One-Click Install & Run)
The fastest way to deploy a worker agent to a new machine is to clone the repo and run the unified startup script. It will auto-detect your hardware, create a virtual environment, install the correct dependencies (e.g. NVIDIA libraries), prompt you for the Control Plane URL, and then immediately start the agent.

**On Linux (Steam Deck, ROG Ally X):**
```bash
git clone https://github.com/kndclark/Local-GPU-Orchestration.git
cd Local-GPU-Orchestration
chmod +x run.sh
./run.sh
```

**On Windows (Desktop):**
Open PowerShell and run:
```powershell
git clone https://github.com/kndclark/Local-GPU-Orchestration.git
cd Local-GPU-Orchestration
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

---

### Manual Setup
If you prefer to run the setup and start steps separately:

#### 1. Clone the repository
```bash
git clone https://github.com/kndclark/Local-GPU-Orchestration.git
cd Local-GPU-Orchestration
```

### 2. Run the Setup Script
The interactive setup script will auto-detect your operating system, configure a Python virtual environment, install the correct dependencies (including NVIDIA libraries if an NVIDIA GPU is detected), and configure your environment variables.

**On Linux (Steam Deck, ROG Ally X):**
```bash
chmod +x scripts/setup.sh
./scripts/linux/setup.sh
```

**On Windows (Desktop):**
Open PowerShell and run:
```powershell
.\scripts\windows\setup.ps1
```

### 3. Start the Worker Agent
Once setup is complete, run the start script to launch the daemon:

**On Linux:**
```bash
./scripts/linux/start_worker.sh
```

**On Windows:**
```powershell
.\scripts\windows\start_worker.ps1
```

The agent will automatically register with the control plane and begin sending hardware telemetry and polling for jobs.

## Development

```bash
# Install with all dev and test dependencies
pip install -e .[dev,test]
``` 

### Generate Protobuf Code

```bash
python scripts/compile_protos.py
```

### Running Tests

```bash
# Run all CI tests (uses simulated backend)
pytest -m "not hardware"

# Run tests against local physical hardware
pytest -m "hardware"
```