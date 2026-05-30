import json
from control_plane.proto import orchestrator_pb2, orchestrator_pb2_grpc
from control_plane.database.models import Node, Gpu, Job
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
            node.os = request.os
            node.os_version = request.os_version
            node.cpu_count = request.cpu_count
            node.cpu_model = request.cpu_model
            node.total_ram_mb = request.total_ram_mb
            node.supported_workloads = ",".join(request.supported_workloads)

            # Upsert GPU records
            # Delete existing GPUs for this node, then re-create
            existing_gpus = (
                db.query(Gpu).filter(Gpu.node_id == request.node_id).all()
            )
            for g in existing_gpus:
                db.delete(g)

            for gpu_info in request.gpus:
                gpu = Gpu(
                    node_id=request.node_id,
                    gpu_index=gpu_info.index,
                    vendor=gpu_info.vendor,
                    model_name=gpu_info.model,
                    driver_version=gpu_info.driver_version,
                    total_vram_mb=gpu_info.total_vram_mb,
                    free_vram_mb=gpu_info.free_vram_mb,
                    used_vram_mb=gpu_info.used_vram_mb,
                    temperature_c=gpu_info.temperature_c,
                    temperature_hotspot_c=gpu_info.temperature_hotspot_c,
                    fan_speed_percent=gpu_info.fan_speed_percent,
                    power_draw_w=gpu_info.power_draw_w,
                    power_limit_w=gpu_info.power_limit_w,
                    gpu_utilization_percent=gpu_info.gpu_utilization_percent,
                    memory_utilization_percent=gpu_info.memory_utilization_percent,
                    encoder_utilization_percent=gpu_info.encoder_utilization_percent,
                    decoder_utilization_percent=gpu_info.decoder_utilization_percent,
                    clock_core_mhz=gpu_info.clock_core_mhz,
                    clock_memory_mhz=gpu_info.clock_memory_mhz,
                    clock_core_max_mhz=gpu_info.clock_core_max_mhz,
                    clock_memory_max_mhz=gpu_info.clock_memory_max_mhz,
                    pcie_gen=gpu_info.pcie_gen,
                    pcie_width=gpu_info.pcie_width,
                    pcie_bandwidth_percent=gpu_info.pcie_bandwidth_percent,
                )
                db.add(gpu)

            db.commit()

        return orchestrator_pb2.RegisterNodeResponse(
            success=True, message="Node registered"
        )

    async def SendHeartbeat(self, request, context):
        with self.db_session_factory() as db:
            node = db.query(Node).filter(Node.node_id == request.node_id).first()
            if node:
                node.cpu_utilization_percent = request.cpu_utilization_percent
                node.ram_utilization_percent = request.ram_utilization_percent
                node.ram_available_mb = request.ram_available_mb

                # Update per-GPU telemetry
                for gpu_info in request.gpus:
                    gpu = (
                        db.query(Gpu)
                        .filter(
                            Gpu.node_id == request.node_id,
                            Gpu.gpu_index == gpu_info.index,
                        )
                        .first()
                    )
                    if gpu:
                        gpu.free_vram_mb = gpu_info.free_vram_mb
                        gpu.used_vram_mb = gpu_info.used_vram_mb
                        gpu.temperature_c = gpu_info.temperature_c
                        gpu.temperature_hotspot_c = gpu_info.temperature_hotspot_c
                        gpu.fan_speed_percent = gpu_info.fan_speed_percent
                        gpu.power_draw_w = gpu_info.power_draw_w
                        gpu.power_limit_w = gpu_info.power_limit_w
                        gpu.gpu_utilization_percent = gpu_info.gpu_utilization_percent
                        gpu.memory_utilization_percent = (
                            gpu_info.memory_utilization_percent
                        )
                        gpu.encoder_utilization_percent = (
                            gpu_info.encoder_utilization_percent
                        )
                        gpu.decoder_utilization_percent = (
                            gpu_info.decoder_utilization_percent
                        )
                        gpu.clock_core_mhz = gpu_info.clock_core_mhz
                        gpu.clock_memory_mhz = gpu_info.clock_memory_mhz
                        gpu.clock_core_max_mhz = gpu_info.clock_core_max_mhz
                        gpu.clock_memory_max_mhz = gpu_info.clock_memory_max_mhz
                        gpu.pcie_gen = gpu_info.pcie_gen
                        gpu.pcie_width = gpu_info.pcie_width
                        gpu.pcie_bandwidth_percent = gpu_info.pcie_bandwidth_percent

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
                    env_vars=env_vars,
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
