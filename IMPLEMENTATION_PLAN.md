# Performance-Aware GPU Workload Orchestrator - Implementation Plan

This document outlines the architecture and phased implementation plan for a distributed GPU orchestrator. It embraces the physical reality of a heterogeneous, thermally-constrained home lab to demonstrate deep distributed systems engineering.

## Key Architectural Philosophies

1.  **Strict Test-Driven Development (TDD)**: No code will be written without a failing test first. Every module requires strict unit tests, and every subsystem boundary (e.g., gRPC calls, REST endpoints, Scheduler loops) requires integration tests. We will use `pytest` with extensive parametrized testing (`@pytest.mark.parametrize`) to rigorously cover nominal paths, edge cases, and off-nominal failures (e.g., network partitions, missing hardware).
2.  **Distributed Systems > "Microservices Theater"**: We are building a "service-oriented control plane with distributed agents." We will deliberately avoid exploding operational complexity and focus on boundaries that map to real physical distribution.
3.  **Distributed Co-Scheduling (VRAM Pooling)**: To support massive workloads (like local LLM inference) that exceed a single node's VRAM, the orchestrator will implement **Gang Scheduling**. It will identify a cluster of healthy nodes, pool their VRAM, and simultaneously deploy RPC workers and a master inference process across them via `llama.cpp`.
4.  **Delay Artificial Complexity**: We will use in-memory async queues and standard HTTP polling first. Upgrading to a message broker (NATS) later creates a powerful "architectural evolution" narrative for interviews.
5.  **Adaptive, Hardware-Aware Scheduling**: The core value proposition. The scheduler will graduate from simple "least-loaded" logic to thermal-aware placement, and finally to adaptive routing based on historical throughput.

## High-Level Architecture

```text
                               ┌─────────────────┐
                               │  Web Dashboard  │
                               │  REST / GraphQL │ (Polling initially)
                               └────────┬────────┘
                                        │ 
                     ┌──────────────────▼──────────────────┐
                     │          API Gateway Service        │ (FastAPI)
                     └──────────────────┬──────────────────┘
                                        │ (Internal HTTP / async queues initially)
┌───────────────────────┐      ┌────────▼────────┐      ┌───────────────────────┐
│   Scheduler Service   │◄────►│   State Store   │◄────►│   Telemetry Service   │
│(Adaptive Algorithms)  │      │   (PostgreSQL)  │      │ (Hardware State Agg.) │
└───────────────────────┘      └────────┬────────┘      └───────────────────────┘
                                        │ (gRPC)
         ┌──────────────────────────────┼──────────────────────────────┐
 ┌───────▼───────┐              ┌───────▼───────┐              ┌───────▼───────┐
 │ Desktop (RTX) │              │ Laptop (RTX)  │              │ Steam Deck    │ ... (ROG Ally)
 │ Worker Agent  │              │ Worker Agent  │              │ Worker Agent  │
 └───────┬───────┘              └───────┬───────┘              └───────┬───────┘
         │                              │                              │
         └─────────────┬────────────────┴────────────────┬─────────────┘
                       │        (Prometheus Pull)        │
                 ┌─────▼─────────────────────────────────▼─────┐
                 │ Prometheus (Metrics) + Grafana (Dashboards) │ 
                 └─────────────────────────────────────────────┘
```

## Recommended Tech Stack & Constraints

*   **Control Plane**: Python, FastAPI, PostgreSQL (State).
*   **Worker-Scheduler Communication**: gRPC.
*   **Testing**: `pytest`, `pytest-asyncio`, `pytest-mock` (for hardware abstraction mocking).
*   **Worker Agents**: Standalone native Python packages.
*   **Telemetry**: Prometheus, Grafana, `pynvml` (NVIDIA), `amdsmi` / `RAPL` (Linux/Steam Deck), LibreHardwareMonitor/WMI (Windows/ROG Ally).

### Operational Constraints & Rabbit-Hole Avoidance
*   **Windows Host vs. WSL**: The Desktop and Laptop agents **must run on the native Windows Host OS**, not WSL, with **Administrator privileges** to read thermal sensors via LibreHardwareMonitor.
*   **Workload Distribution**: Workload binaries (FFmpeg, ONNX scripts, llama.cpp) will be **pre-installed** on the worker nodes. 
*   **CUDA Representation**: We will define a specific workload plugin tagged as `requires_cuda: true`. The Scheduler will use capability-matching to route this *only* to the RTX nodes.

---

## Phase-by-Phase Development Plan

### Phase 1: Local Single-Machine Orchestration
*   Set up a monorepo for the Control Plane (API Gateway, Scheduler, Telemetry logic).
*   Develop the standalone Python **Worker Agent**.
*   Implement basic job submission via FastAPI.
*   Implement a naive FIFO, in-memory queue in the Scheduler.
*   Run a local workload (e.g., FFmpeg transcode) to prove the end-to-end execution flow.

### Phase 2: Distributed Workers & Hardware Abstraction
*   Define the Protobuf schemas for gRPC communication (Registration, Heartbeat, Job Dispatch).
*   Deploy agents to the Desktop (Windows), Steam Deck (Linux/SteamOS), and ROG Ally X (Linux/SteamOS).
*   Build the Hardware Abstraction Layer (HAL) in the workers to normalize telemetry across NVML, AMD APIs, and Windows WMI.

### Phase 3: Telemetry Pipeline & Dashboards
*   Expose normalized hardware state (thermals, utilization, VRAM) from the workers.
*   Configure Prometheus to scrape the workers and the Control Plane.
*   Build Grafana dashboards to visualize cluster health and job execution timelines.

### Phase 4: Capability & Thermal-Aware Scheduling
*   Upgrade the Scheduler to route CUDA-required tasks *only* to NVIDIA nodes.
*   Implement **Thermal-Aware Routing**: The Scheduler reads thermal data and routes jobs away from nodes nearing their thermal limits.

### Phase 5: Distributed Co-Scheduling (VRAM Pooling for LLMs)
*   Implement **Gang Scheduling**: Deploy `llama-rpc-server` to a subset of worker nodes whose combined VRAM meets the requirement, and deploy the `llama-cli` master process to a head node.

### Phase 6: Adaptive Scheduling (Historical Throughput Weighting)
*   Implement a feedback loop where the scheduler records actual execution times for job types on specific nodes to calculate "effective throughput".

### Phase 7: Architectural Evolution (Optional / Later)
*   Migrate internal Control Plane communication to **NATS**.
*   Migrate the Dashboard to **GraphQL Subscriptions / WebSockets**.

### Phase 8: Go Worker Agent (Optional / Later)
*   Rewrite Worker Agent in **Go** for lower memory footprint and easier deployment.
*   (Super optional) Rewrite telemetry collection in **Go** for better network performance.

### Phase 9: Config enhancement (Optional / Later)
*   Make setting up configurations easier using **TOML/YAML**.
*   Store IP in .env (?)
*   Investigate one-time install script that can set up the entire orchestrator (including network routing of agent machines) on a new machine, from the host.