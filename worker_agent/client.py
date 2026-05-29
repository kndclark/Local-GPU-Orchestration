import grpc
import logging
from worker_agent.proto import orchestrator_pb2, orchestrator_pb2_grpc

logger = logging.getLogger(__name__)


class WorkerClient:
    def __init__(self, node_id: str, server_address: str = "localhost:50051"):
        self.node_id = node_id
        self.server_address = server_address
        self.channel = None
        self.stub = None

    def connect(self):
        self.channel = grpc.aio.insecure_channel(self.server_address)
        self.stub = orchestrator_pb2_grpc.OrchestratorStub(self.channel)

    async def close(self):
        if self.channel:
            await self.channel.close()

    async def register_node(
        self,
        hostname: str,
        total_vram_mb: int,
        gpu_count: int,
        supported_workloads: list[str],
    ) -> bool:
        if not self.stub:
            self.connect()

        req = orchestrator_pb2.RegisterNodeRequest(
            node_id=self.node_id,
            hostname=hostname,
            total_vram_mb=total_vram_mb,
            gpu_count=gpu_count,
            supported_workloads=supported_workloads,
        )

        try:
            resp = await self.stub.RegisterNode(req)
            return resp.success
        except grpc.aio.AioRpcError as e:
            logger.error(f"Failed to register node: {e.code()} - {e.details()}")
            return False

    async def send_heartbeat(
        self,
        free_vram_mb: int,
        temp_c: float,
        util_percent: float,
        active_jobs: list[str],
    ) -> bool:
        if not self.stub:
            self.connect()

        req = orchestrator_pb2.HeartbeatRequest(
            node_id=self.node_id,
            free_vram_mb=free_vram_mb,
            gpu_temperature_c=temp_c,
            gpu_utilization_percent=util_percent,
            active_job_ids=active_jobs,
        )

        try:
            resp = await self.stub.SendHeartbeat(req)
            return resp.acknowledged
        except grpc.aio.AioRpcError as e:
            logger.error(f"Failed to send heartbeat: {e.code()} - {e.details()}")
            return False

    async def request_job(self) -> dict | None:
        if not self.stub:
            self.connect()
        req = orchestrator_pb2.JobRequestPlaceholder(node_id=self.node_id)
        try:
            resp = await self.stub.RequestJob(req)
            if resp.job_id:
                return {
                    "job_id": resp.job_id,
                    "workload_type": resp.workload_type,
                    "args": list(resp.args),
                    "env_vars": dict(resp.env_vars),
                }
        except grpc.aio.AioRpcError as e:
            logger.error(f"Failed to request job: {e.code()} - {e.details()}")
        return None

    async def update_job_status(
        self, job_id: str, status: str, error_message: str = ""
    ) -> bool:
        if not self.stub:
            self.connect()
        req = orchestrator_pb2.JobStatusUpdate(
            job_id=job_id,
            node_id=self.node_id,
            status=status,
            error_message=error_message,
        )
        try:
            resp = await self.stub.UpdateJobStatus(req)
            return resp.acknowledged
        except grpc.aio.AioRpcError as e:
            logger.error(f"Failed to update job status: {e.code()} - {e.details()}")
            return False
