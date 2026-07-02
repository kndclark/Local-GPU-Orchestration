import asyncio

import grpc
import pytest
from fastapi.testclient import TestClient

from control_plane.main import app, SessionLocal, scheduler
from control_plane.grpc_server import OrchestratorService
from control_plane.gang_scheduler import run_gang_dispatch_cycle
from control_plane.proto import orchestrator_pb2_grpc

from worker_agent.client import WorkerClient
from worker_agent.hal.base import SystemTelemetry
from worker_agent.hal.simulated import SimulatedBackend, SimulatedConfig

NODES = ["gang-a", "gang-b"]


def _reset_scheduler():
    scheduler.pending_jobs.clear()
    scheduler._initialized = False


def _purge():
    from control_plane.database.models import Job, Node, GangJob, GangJobParticipant

    with SessionLocal() as db:
        db.query(GangJobParticipant).delete()
        db.query(GangJob).delete()
        db.query(Job).delete()
        for nid in NODES:
            node = db.query(Node).filter(Node.node_id == nid).first()
            if node:
                db.delete(node)
        db.commit()


async def _register_and_heartbeat(worker: WorkerClient, sim: SimulatedBackend):
    await worker.register_node(
        hostname=worker.node_id,
        gpus=sim.discover_gpus(),
        supported_workloads=["llama_rpc_server", "llama_cli"],
        os_name="linux",
    )
    telem = SystemTelemetry(
        gpus=[sim.read_telemetry(0)],
        cpu_utilization_percent=10.0,
        ram_utilization_percent=10.0,
        ram_available_mb=10000,
    )
    await worker.send_heartbeat(telemetry=telem, active_jobs=[])


async def _poll(worker: WorkerClient, attempts: int = 40):
    for _ in range(attempts):
        job = await worker.request_job()
        if job:
            return job
        await asyncio.sleep(0.02)
    return None


@pytest.mark.asyncio
async def test_gang_end_to_end():
    """Full two-phase gang lifecycle over the real gRPC + REST + dispatch path.

    Uses simulated hardware and stand-in workload types (no real llama.cpp): the
    point is to prove the distributed coordination — VRAM pooling, node pinning,
    WORKER_READY endpoint reporting, controller dispatch with injected endpoints,
    and completion propagation.
    """
    server = grpc.aio.server()
    service = OrchestratorService(db_session_factory=SessionLocal, scheduler=scheduler)
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    _reset_scheduler()
    _purge()

    wa = WorkerClient(node_id="gang-a", server_address=f"localhost:{port}")
    wb = WorkerClient(node_id="gang-b", server_address=f"localhost:{port}")
    clients = {"gang-a": wa, "gang-b": wb}
    sim = SimulatedBackend(
        config=SimulatedConfig(
            num_gpus=1, vendor="NVIDIA", total_vram_mb=24576, noise=False
        )
    )

    try:
        await _register_and_heartbeat(wa, sim)
        await _register_and_heartbeat(wb, sim)

        rest = TestClient(app)
        resp = rest.post(
            "/api/v1/gang-jobs",
            json={
                "worker_workload_type": "llama_rpc_server",
                "worker_args": ["--host", "0.0.0.0", "--port", "50052"],
                "worker_ready_signal": "listening",
                "worker_port": 50052,
                "controller_workload_type": "llama_cli",
                "controller_args": ["--model", "/models/demo.gguf"],
                "controller_endpoints_flag": "--rpc",
                "min_vram_mb": 20000,
                "requires_cuda": False,
            },
        )
        assert resp.status_code == 201, resp.text
        gang = resp.json()
        gang_id = gang["gang_job_id"]
        roles = {p["node_id"]: p["role"] for p in gang["participants"]}
        controller_id = next(n for n, r in roles.items() if r == "controller")
        worker_id = next(n for n, r in roles.items() if r == "worker")

        # Phase 1: the worker node pulls its pinned server job with coordination
        # fields, then reports WORKER_READY with its endpoint.
        wjob = await _poll(clients[worker_id])
        assert wjob is not None, "worker never received its gang job"
        assert wjob["workload_type"] == "llama_rpc_server"
        assert wjob["ready_signal"] == "listening"
        assert wjob["report_port"] == 50052

        worker_endpoint = f"{worker_id}-host:50052"
        await clients[worker_id].update_job_status(
            job_id=wjob["job_id"], status="WORKER_READY", endpoint=worker_endpoint
        )

        # Dispatch cycle promotes FORMING -> RUNNING and dispatches the controller.
        with SessionLocal() as db:
            await run_gang_dispatch_cycle(db, scheduler)
        assert rest.get(f"/api/v1/gang-jobs/{gang_id}").json()["status"] == "RUNNING"

        # Phase 2: the controller node pulls its job with worker endpoints injected.
        cjob = await _poll(clients[controller_id])
        assert cjob is not None, "controller never received its job"
        assert cjob["workload_type"] == "llama_cli"
        assert (
            cjob["ready_signal"] == ""
        )  # controller is a normal run-to-completion job
        assert "--rpc" in cjob["args"]
        assert worker_endpoint in cjob["args"]

        await clients[controller_id].update_job_status(
            job_id=cjob["job_id"], status="COMPLETED"
        )

        # Dispatch cycle propagates controller completion to the gang.
        with SessionLocal() as db:
            await run_gang_dispatch_cycle(db, scheduler)

        final = rest.get(f"/api/v1/gang-jobs/{gang_id}").json()
        assert final["status"] == "COMPLETED"
        worker_part = next(p for p in final["participants"] if p["role"] == "worker")
        assert worker_part["endpoint"] == worker_endpoint

    finally:
        await wa.close()
        await wb.close()
        await server.stop(None)
        _purge()
        _reset_scheduler()
