import pytest
import asyncio
import grpc
from fastapi.testclient import TestClient

from control_plane.main import app, SessionLocal, scheduler
from control_plane.grpc_server import OrchestratorService
from control_plane.proto import orchestrator_pb2_grpc

from worker_agent.client import WorkerClient
from worker_agent.executor import JobExecutor

@pytest.mark.asyncio
async def test_end_to_end_orchestration():
    # 1. Start gRPC server
    server = grpc.aio.server()
    service = OrchestratorService(db_session_factory=SessionLocal, scheduler=scheduler)
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(service, server)
    server.add_insecure_port('[::]:50051')
    await server.start()
    
    try:
        # 2. Worker Agent Registration
        worker = WorkerClient(node_id="test-node", server_address="localhost:50051")
        success = await worker.register_node(
            hostname="test-host",
            total_vram_mb=8000,
            gpu_count=1,
            supported_workloads=["ffmpeg", "python"]
        )
        assert success is True
        
        # 3. Submit a job via Control Plane API
        client = TestClient(app)
        response = client.post("/api/v1/jobs", json={
            "workload_type": "python",
            "args": ["-c", "print('hello e2e')"],
            "env_vars": {}
        })
        assert response.status_code == 200
        job_data = response.json()
        job_id = job_data["job_id"]
        assert job_data["status"] == "PENDING"
        
        # 4. Worker polls for job
        await asyncio.sleep(0.1) # Yield control so scheduler can process
        job = await worker.request_job()
        assert job is not None
        assert job["job_id"] == job_id
        
        # 5. Worker executes job
        executor = JobExecutor()
        import sys
        success, err = await executor.execute_job(
            job_id=job["job_id"],
            executable=sys.executable,
            args=job["args"],
            env_vars=job["env_vars"]
        )
        assert success is True
        
        # 6. Worker updates status
        updated = await worker.update_job_status(job_id=job_id, status="COMPLETED")
        assert updated is True
        
        # 7. Verify status in database
        with SessionLocal() as db:
            from control_plane.database.models import Job
            db_job = db.query(Job).filter(Job.job_id == job_id).first()
            assert db_job.status == "COMPLETED"
            assert db_job.assigned_node_id == "test-node"
            
    finally:
        await server.stop(None)
