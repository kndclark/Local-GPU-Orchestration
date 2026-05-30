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

*(Note: If the auto-detection fails to find your NVIDIA GPU, you can pass a flag to force the installation of NVIDIA telemetry tools: `./run.sh --force-nvidia` or `.\run.ps1 -ForceNvidia`)*

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

*(Note: You can pass `--force-nvidia` or `-ForceNvidia` to these scripts if your NVIDIA GPU wasn't automatically detected, or manually install via `pip install -e .[nvidia]` in the `.venv`).*

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

## Monitoring (Prometheus + Grafana)

The orchestrator exposes Prometheus metrics from both the **Control Plane** (port 8080) and **Worker Agents** (port 9101). A pre-configured Docker Compose stack is provided for visualization.

### Start the Monitoring Stack

```bash
docker-compose -f docker-compose.monitoring.yml up -d
```

This starts:
- **Prometheus** at [http://localhost:9090](http://localhost:9090) — scrapes the control plane and worker agents every 15s
- **Grafana** at [http://localhost:3000](http://localhost:3000) — pre-provisioned with two dashboards (login: `admin`/`admin`)

### Dashboards

| Dashboard | Description |
|-----------|-------------|
| **Cluster Overview** | Node count, total GPUs, VRAM, GPU vendor breakdown, jobs by status, per-node CPU/RAM, GPU temperature, VRAM, power, utilization |
| **Node Detail** | Drill-down by `node_id` — system stats, per-GPU temperature, utilization, VRAM, power, fan speed, clock speeds |

### Adding Worker Targets

Edit `monitoring/prometheus.yml` to add additional worker agent targets:

```yaml
- targets: ["<worker-ip>:9101"]
  labels:
    component: "worker_agent"
    machine: "<machine-name>"
```

### Metrics Ports

| Service | Port | Path |
|---------|------|------|
| Control Plane | 8080 | `/metrics/` |
| Worker Agent | 9101 (configurable) | `/metrics` |

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
# Run all tests (uses simulated backend for GPU tests)
pytest -v

# Run only CI-safe tests (no physical hardware required)
pytest -m "not hardware" -v

# Run tests against local physical hardware
pytest -m "hardware" -v
```