import grpc
import json
from sqlalchemy.orm import Session
from control_plane.proto import orchestrator_pb2, orchestrator_pb2_grpc
from control_plane.database.models import Node, Job
from control_plane.scheduler import FIFOScheduler

class OrchestratorService(orchestrator_pb2_grpc.OrchestratorServicer):
    def __init__(self, db_session_factory, scheduler: FIFOScheduler):
        self.db_session_factory = db_session_factory
        self.scheduler = scheduler

    async def RegisterNode(self, request, context):
        with self.db_session_factory() as db:
            node = db.query(Node).filter(Node.node_id == request.node_id).first()
            if not node:
                node = Node(node_id=request.node_id)
                db.add(node)
            
            node.hostname = request.hostname
            node.total_vram_mb = request.total_vram_mb
            node.gpu_count = request.gpu_count
            node.supported_workloads = ",".join(request.supported_workloads)
            db.commit()
            
        return orchestrator_pb2.RegisterNodeResponse(success=True, message="Node registered")

    async def SendHeartbeat(self, request, context):
        with self.db_session_factory() as db:
            node = db.query(Node).filter(Node.node_id == request.node_id).first()
            if node:
                node.free_vram_mb = request.free_vram_mb
                node.gpu_temperature_c = request.gpu_temperature_c
                node.gpu_utilization_percent = request.gpu_utilization_percent
                db.commit()
        return orchestrator_pb2.HeartbeatResponse(acknowledged=True)

    async def RequestJob(self, request, context):
        job_id = await self.scheduler.get_next_job()
        if not job_id:
            return orchestrator_pb2.JobRequest(job_id="")
            
        with self.db_session_factory() as db:
            job = db.query(Job).filter(Job.job_id == job_id).first()
            if job:
                job.assigned_node_id = request.node_id
                job.status = "RUNNING"
                db.commit()
                
                args = json.loads(job.args)
                env_vars = json.loads(job.env_vars)
                
                return orchestrator_pb2.JobRequest(
                    job_id=job.job_id,
                    workload_type=job.workload_type,
                    args=args,
                    env_vars=env_vars
                )
        return orchestrator_pb2.JobRequest(job_id="")

    async def UpdateJobStatus(self, request, context):
        with self.db_session_factory() as db:
            job = db.query(Job).filter(Job.job_id == request.job_id).first()
            if job:
                job.status = request.status
                if request.error_message:
                    job.error_message = request.error_message
                db.commit()
        return orchestrator_pb2.JobStatusResponse(acknowledged=True)
