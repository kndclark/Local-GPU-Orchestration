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

### Step 1 — Start the Control Plane (on the host machine)

The control plane, Prometheus, and Grafana all run together in a single Docker Compose stack:

```bash
docker compose up -d --build
```

Or via the Makefile shortcut:

```bash
make up
```

This starts:
- **Control Plane** (REST API + gRPC) at ports `8080` / `50051`
- **Prometheus** at [http://localhost:9090](http://localhost:9090)
- **Grafana** at [http://localhost:3000](http://localhost:3000) — pre-provisioned dashboards (login: `admin`/`admin`)

> The control plane host can also run a worker agent alongside Docker — just run the worker startup script as described in Step 2.

---

### Step 2 — Start Worker Agents (on each worker machine)

Clone the repo on the worker machine and run the unified startup script. It auto-detects hardware, creates a virtual environment, installs the correct dependencies (including NVIDIA libraries if present), and immediately starts the agent.

**On Linux (Steam Deck, ROG Ally X):**
```bash
git clone https://github.com/kndclark/Local-GPU-Orchestration.git
cd Local-GPU-Orchestration
chmod +x run.sh
./run.sh
```

**On Windows (Desktop):**
```powershell
git clone https://github.com/kndclark/Local-GPU-Orchestration.git
cd Local-GPU-Orchestration
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

*(Pass `--force-nvidia` / `-ForceNvidia` if your NVIDIA GPU wasn't auto-detected.)*

**No manual configuration required.** The worker agent automatically:
1. Scans the local subnet to discover the control plane — no `ORCHESTRATOR_URL` needed
2. Registers itself via gRPC, which adds its Prometheus metrics endpoint to the scrape list automatically
3. Begins sending hardware telemetry heartbeats and polling for jobs

Prometheus picks up the new worker within one scrape interval (~15s). No editing of config files required.

---

### Manual Setup
If you prefer to run setup and start as separate steps:

**On Linux:**
```bash
chmod +x scripts/linux/setup.sh
./scripts/linux/setup.sh
./scripts/linux/start_worker.sh
```

**On Windows:**
```powershell
.\scripts\windows\setup.ps1
.\scripts\windows\start_worker.ps1
```

---

## Monitoring

The orchestrator exposes Prometheus metrics from both the **Control Plane** (port 8080) and **Worker Agents** (port 9101).

### Dashboards

| Dashboard | Description |
|-----------|-------------|
| **Cluster Overview** | Node count, total GPUs, VRAM, GPU vendor breakdown, jobs by status, per-node CPU/RAM, GPU temperature, VRAM, power, utilization |
| **Node Detail** | Drill-down by `node_id` — system stats, per-GPU temperature, utilization, VRAM, power, fan speed, clock speeds |

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