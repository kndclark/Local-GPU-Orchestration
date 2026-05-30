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


@pytest.mark.asyncio
async def test_end_to_end_orchestration():
    # 1. Start gRPC server
    server = grpc.aio.server()
    service = OrchestratorService(db_session_factory=SessionLocal, scheduler=scheduler)
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(service, server)
    server.add_insecure_port("[::]:50051")
    await server.start()

    try:
        # Clear the global scheduler queue from any previous test runs
        while not scheduler.queue.empty():
            scheduler.queue.get_nowait()

        # 2. Set up simulated hardware
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

        # 3. Worker Agent Registration with GPU info
        worker = WorkerClient(node_id="test-node", server_address="localhost:50051")
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

        # 4. Send a heartbeat with telemetry
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

        # 5. Submit a job via Control Plane API
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

        # 6. Worker polls for job
        await asyncio.sleep(0.1)
        job = await worker.request_job()
        assert job is not None
        assert job["job_id"] == job_id

        # 7. Worker executes job
        executor = JobExecutor()
        import sys

        success, err = await executor.execute_job(
            job_id=job["job_id"],
            executable=sys.executable,
            args=job["args"],
            env_vars=job["env_vars"],
        )
        assert success is True

        # 8. Worker updates status
        updated = await worker.update_job_status(job_id=job_id, status="COMPLETED")
        assert updated is True

        # 9. Verify job status in database
        with SessionLocal() as db:
            from control_plane.database.models import Job, Node, Gpu

            db_job = db.query(Job).filter(Job.job_id == job_id).first()
            assert db_job.status == "COMPLETED"
            assert db_job.assigned_node_id == "test-node"

            # 10. Verify node registration persisted with GPU info
            db_node = db.query(Node).filter(Node.node_id == "test-node").first()
            assert db_node is not None
            assert db_node.hostname == "test-host"
            assert db_node.os == "windows"
            assert db_node.cpu_count == 8

            # 11. Verify GPU telemetry round-tripped
            db_gpus = db.query(Gpu).filter(Gpu.node_id == "test-node").all()
            assert len(db_gpus) == 1
            assert db_gpus[0].vendor == "NVIDIA"
            assert db_gpus[0].model_name == "Simulated RTX 4090"
            assert db_gpus[0].total_vram_mb == 24576
            # Telemetry from heartbeat should be persisted
            assert db_gpus[0].temperature_c > 0

        # 12. Verify node API endpoints
        nodes_resp = client.get("/api/v1/nodes")
        assert nodes_resp.status_code == 200
        nodes = nodes_resp.json()
        # Find our test node in the list
        test_nodes = [n for n in nodes if n["node_id"] == "test-node"]
        assert len(test_nodes) == 1
        assert test_nodes[0]["gpu_count"] == 1

        detail_resp = client.get("/api/v1/nodes/test-node")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["os"] == "windows"
        assert len(detail["gpus"]) == 1
        assert detail["gpus"][0]["vendor"] == "NVIDIA"

    finally:
        await server.stop(None)
