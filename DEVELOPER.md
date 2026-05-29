# Developer Guide

Welcome to the GPU Orchestrator project! This guide explains the high-level functionality of our major components and the development workflows used in the repository.

## Major Components

The system is split into two primary pieces that communicate over the network:

1. **Control Plane** (`control_plane/`)
   The central "brain" of the cluster. It provides a REST API (via FastAPI) for users to submit jobs, maintains the global state in a PostgreSQL database, and runs a Scheduler loop to dispatch workloads to the best available worker node (taking into account hardware capabilities and thermal limits).

2. **Worker Agent** (`worker_agent/`)
   A lightweight daemon running on the individual GPU machines (Windows desktops, Steam Decks, etc.). It gathers local hardware telemetry (temperature, VRAM usage), registers with the Control Plane, and executes the actual workloads (like `ffmpeg` or `llama.cpp`) when dispatched.

---

## The "Proto" Process (gRPC & Protobuf)

To make the Control Plane and Worker Agents communicate extremely quickly and reliably across the local network, we use **gRPC** and **Protocol Buffers (Protobuf)** instead of standard HTTP/REST.

### 1. What is Protobuf?
Protocol Buffers (the `proto/orchestrator.proto` file) provide a language-neutral way to define our network API contract. We define strict schemas for messages (like `HeartbeatRequest` or `RegisterNodeRequest`) and services (the RPC endpoints). 

*Why use it?* It is much faster and smaller than JSON, and it guarantees that both the sender and receiver expect the exact same data types.

### 2. The Compilation Step
Because Protobuf is just an interface definition language, we can't run it directly. We must "compile" the `.proto` file into native Python code using the `grpcio-tools` compiler. 

Our script `scripts/compile_protos.py` reads the `.proto` file and generates Python files:
- **`_pb2.py`**: Python classes representing our data structures.
- **`_pb2_grpc.py`**: The network client/server code.

We generate these files directly into the `control_plane/proto/` and `worker_agent/proto/` directories. This ensures both components have the exact same definitions and can safely communicate. Whenever you change the `orchestrator.proto` file, you must re-run the compilation script to update the Python code.

---

## Development & CI/CD Pipeline

We maintain high code quality through a rigorous CI/CD pipeline configured via GitHub Actions (`.github/workflows/ci.yml`). Every push and pull request runs formatting checks, linting, security analysis, and the full test suite.

### Local Development Setup
To set up your local environment and install all dependencies:
```bash
pip install -e .[dev,test]
```

### Running Tests
We use `pytest` for all unit and integration testing. We strongly adhere to Test-Driven Development (TDD).
```bash
pytest -v
```

### Linting & Formatting
We use `black` for code formatting and `flake8` for style guide enforcement.
```bash
black .
flake8 .
```

### Security Analysis (SAST)
We use `bandit` to scan our Python code for common security vulnerabilities. We specifically exclude the generated protobuf files.
```bash
bandit -r control_plane worker_agent -x control_plane/proto,worker_agent/proto
```
