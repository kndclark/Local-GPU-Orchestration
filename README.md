# GPU Orchestrator

![CI/CD Pipeline](https://github.com/kndclark/Local-GPU-Orchestration/actions/workflows/ci.yml/badge.svg)

A distributed, performance-aware GPU workload orchestrator.

## Current State (Phase 1 Complete)
- **Control Plane**: Exposes a FastAPI REST endpoint (`/api/v1/jobs`) to submit workloads, utilizes SQLAlchemy for state management, and implements an asynchronous `FIFOScheduler`.
- **Worker Agent**: Registers nodes and sends heartbeats via gRPC, securely pulls jobs, and executes them using native OS subprocesses.


## Getting Started

```bash
pip install -e .[dev]
``` 

### Generate Protobuf Code

```bash
python scripts/compile_protos.py
```

## Running Tests

```bash
pytest
```         