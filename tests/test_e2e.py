import pytest
import asyncio
import grpc
from fastapi.testclient import TestClient

from control_plane.main import app, SessionLocal, scheduler
from control_plane.grpc_server import OrchestratorService
from control_plane.proto import orchestrator_pb2_grpc

from worker_agent.client import WorkerClient
from worker_agent.executor import JobExecutor
from worker_agent.hal.base import SystemTelemetry
from worker_agent.hal.simulated import SimulatedBackend, SimulatedConfig

NODE_ID = "test-node"


def _reset_scheduler():
    """Clear global scheduler state so runs don't bleed into each other."""
    scheduler.pending_jobs.clear()
    scheduler._initialized = False


def _purge_node(node_id: str):
    """Remove a node and any jobs assigned to it from the shared test DB."""
    from control_plane.database.models import Job, Node

    with SessionLocal() as db:
        db.query(Job).filter(Job.assigned_node_id == node_id).delete()
        node = db.query(Node).filter(Node.node_id == node_id).first()
        if node:
            db.delete(node)
        db.commit()


async def _poll_for_job(worker: WorkerClient, expected_job_id: str, attempts: int = 20):
    """Poll RequestJob until the expected job is handed out (robust to timing)."""
    for _ in range(attempts):
        job = await worker.request_job()
        if job and job["job_id"] == expected_job_id:
            return job
        await asyncio.sleep(0.05)
    return None


@pytest.mark.asyncio
async def test_end_to_end_orchestration():
    # Start an isolated gRPC server on an ephemeral port
    server = grpc.aio.server()
    service = OrchestratorService(db_session_factory=SessionLocal, scheduler=scheduler)
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(service, server)
    port = server.add_insecure_port("[::]:0")
    await server.start()

    # Start from clean global + DB state so prior runs can't interfere
    _reset_scheduler()
    _purge_node(NODE_ID)

    worker = WorkerClient(node_id=NODE_ID, server_address=f"localhost:{port}")

    try:
        # 1. Set up simulated hardware
        sim = SimulatedBackend(
            config=SimulatedConfig(
                num_gpus=1,
                vendor="NVIDIA",
                model="Simulated RTX 4090",
                total_vram_mb=24576,
                noise=False,
            )
        )
        sim_gpus = sim.discover_gpus()

        # 2. Worker Agent Registration with GPU info
        success = await worker.register_node(
            hostname="test-host",
            gpus=sim_gpus,
            supported_workloads=["ffmpeg", "python"],
            os_name="windows",
            os_version="11",
            cpu_count=8,
            cpu_model="Test CPU",
            total_ram_mb=16384,
        )
        assert success is True

        # 3. Send a heartbeat with telemetry
        sim_telem = SystemTelemetry(
            gpus=[sim.read_telemetry(0)],
            cpu_utilization_percent=25.0,
            ram_utilization_percent=40.0,
            ram_available_mb=10000,
        )
        hb_success = await worker.send_heartbeat(
            telemetry=sim_telem,
            active_jobs=[],
        )
        assert hb_success is True

        # 4. Submit a job via Control Plane API
        client = TestClient(app)
        response = client.post(
            "/api/v1/jobs",
            json={
                "workload_type": "python",
                "args": ["-c", "print('hello e2e')"],
                "env_vars": {},
            },
        )
        assert response.status_code == 200
        job_data = response.json()
        job_id = job_data["job_id"]
        assert job_data["status"] == "PENDING"

        # 5. Worker polls for the job (retry instead of a fixed sleep)
        job = await _poll_for_job(worker, job_id)
        assert job is not None, "Worker never received the submitted job"
        assert job["job_id"] == job_id

        # 6. Worker executes the job
        import sys

        executor = JobExecutor()
        exec_success, err = await executor.execute_job(
            job_id=job["job_id"],
            executable=sys.executable,
            args=job["args"],
            env_vars=job["env_vars"],
        )
        assert exec_success is True, err

        # 7. Worker updates status
        updated = await worker.update_job_status(job_id=job_id, status="COMPLETED")
        assert updated is True

        # 8. Verify job status in database
        with SessionLocal() as db:
            from control_plane.database.models import Job, Node, Gpu

            db_job = db.query(Job).filter(Job.job_id == job_id).first()
            assert db_job.status == "COMPLETED"
            assert db_job.assigned_node_id == NODE_ID

            # 9. Verify node registration persisted with GPU info
            db_node = db.query(Node).filter(Node.node_id == NODE_ID).first()
            assert db_node is not None
            assert db_node.hostname == "test-host"
            assert db_node.os == "windows"
            assert db_node.cpu_count == 8

            # 10. Verify GPU telemetry round-tripped
            db_gpus = db.query(Gpu).filter(Gpu.node_id == NODE_ID).all()
            assert len(db_gpus) == 1
            assert db_gpus[0].vendor == "NVIDIA"
            assert db_gpus[0].model_name == "Simulated RTX 4090"
            assert db_gpus[0].total_vram_mb == 24576
            assert db_gpus[0].temperature_c > 0

        # 11. Verify node API endpoints
        nodes_resp = client.get("/api/v1/nodes")
        assert nodes_resp.status_code == 200
        nodes = nodes_resp.json()
        test_nodes = [n for n in nodes if n["node_id"] == NODE_ID]
        assert len(test_nodes) == 1
        assert test_nodes[0]["gpu_count"] == 1

        detail_resp = client.get(f"/api/v1/nodes/{NODE_ID}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["os"] == "windows"
        assert len(detail["gpus"]) == 1
        assert detail["gpus"][0]["vendor"] == "NVIDIA"

    finally:
        await worker.close()
        await server.stop(None)
        _purge_node(NODE_ID)
        _reset_scheduler()
