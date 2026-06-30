import grpc
import logging
from worker_agent.proto import orchestrator_pb2, orchestrator_pb2_grpc
from worker_agent.hal.base import GpuDevice, GpuTelemetry, SystemTelemetry

logger = logging.getLogger(__name__)


def _gpu_device_to_proto(gpu: GpuDevice) -> orchestrator_pb2.GpuInfo:
    """Convert a HAL GpuDevice to a protobuf GpuInfo."""
    return orchestrator_pb2.GpuInfo(
        index=gpu.index,
        vendor=gpu.vendor,
        model=gpu.model,
        driver_version=gpu.driver_version,
        total_vram_mb=gpu.total_vram_mb,
    )


def _gpu_telemetry_to_proto(telem: GpuTelemetry) -> orchestrator_pb2.GpuInfo:
    """Convert a HAL GpuTelemetry to a protobuf GpuInfo."""
    return orchestrator_pb2.GpuInfo(
        index=telem.index,
        free_vram_mb=telem.free_vram_mb,
        used_vram_mb=telem.used_vram_mb,
        temperature_c=telem.temperature_c,
        temperature_hotspot_c=telem.temperature_hotspot_c,
        fan_speed_percent=telem.fan_speed_percent,
        power_draw_w=telem.power_draw_w,
        power_limit_w=telem.power_limit_w,
        gpu_utilization_percent=telem.gpu_utilization_percent,
        memory_utilization_percent=telem.memory_utilization_percent,
        encoder_utilization_percent=telem.encoder_utilization_percent,
        decoder_utilization_percent=telem.decoder_utilization_percent,
        clock_core_mhz=telem.clock_core_mhz,
        clock_memory_mhz=telem.clock_memory_mhz,
        clock_core_max_mhz=telem.clock_core_max_mhz,
        clock_memory_max_mhz=telem.clock_memory_max_mhz,
        pcie_gen=telem.pcie_gen,
        pcie_width=telem.pcie_width,
        pcie_bandwidth_percent=telem.pcie_bandwidth_percent,
    )


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
        gpus: list[GpuDevice],
        supported_workloads: list[str],
        os_name: str = "",
        os_version: str = "",
        cpu_count: int = 0,
        cpu_model: str = "",
        total_ram_mb: int = 0,
        metrics_ip: str = "",
        metrics_port: int = 0,
        colocated: bool = False,
    ) -> bool:
        if not self.stub:
            self.connect()

        req = orchestrator_pb2.RegisterNodeRequest(
            node_id=self.node_id,
            hostname=hostname,
            os=os_name,
            os_version=os_version,
            cpu_count=cpu_count,
            cpu_model=cpu_model,
            total_ram_mb=total_ram_mb,
            metrics_ip=metrics_ip,
            metrics_port=metrics_port,
            colocated=colocated,
            gpus=[_gpu_device_to_proto(g) for g in gpus],
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
        telemetry: SystemTelemetry,
        active_jobs: list[str],
    ) -> bool:
        if not self.stub:
            self.connect()

        req = orchestrator_pb2.HeartbeatRequest(
            node_id=self.node_id,
            gpus=[_gpu_telemetry_to_proto(g) for g in telemetry.gpus],
            cpu_utilization_percent=telemetry.cpu_utilization_percent,
            ram_utilization_percent=telemetry.ram_utilization_percent,
            ram_available_mb=telemetry.ram_available_mb,
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
