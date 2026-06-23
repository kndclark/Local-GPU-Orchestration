import json
import logging
import socket
from pathlib import Path
from control_plane.proto import orchestrator_pb2, orchestrator_pb2_grpc
from control_plane.database.models import Node, Gpu, Job
from control_plane.scheduler import HardwareAwareScheduler


def _get_docker_gateway() -> str | None:
    """Return the Docker bridge gateway IP by reading the container's routing table.

    On bridge-networked Docker containers (both Windows and Linux hosts), the
    host machine's native processes appear as the default gateway IP rather than
    a local IP address. This detects that case so the worker can be registered
    under host.docker.internal instead of the unreachable gateway IP.
    """
    try:
        with open("/proc/net/route") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return socket.inet_ntoa(bytes.fromhex(parts[2])[::-1])
    except (OSError, IndexError, ValueError):
        pass  # nosec B110
    return None


class OrchestratorService(orchestrator_pb2_grpc.OrchestratorServicer):
    def __init__(self, db_session_factory, scheduler: HardwareAwareScheduler):
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
            existing_gpus = db.query(Gpu).filter(Gpu.node_id == request.node_id).all()
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

        # Extract peer IP and auto-register with Prometheus
        import urllib.parse

        peer = urllib.parse.unquote(context.peer())
        ip = None
        if peer.startswith("ipv4:"):
            ip = peer.split(":")[1]
        elif peer.startswith("ipv6:"):
            ip = peer.split("]:")[0].replace("ipv6:[", "")

        if ip:
            # Check if this IP is actually one of the host's own local IPs
            is_local = False
            if ip in ("127.0.0.1", "::1", "localhost"):
                is_local = True
            else:
                try:
                    local_ips = socket.gethostbyname_ex(socket.gethostname())[2]
                    if ip in local_ips:
                        is_local = True
                except Exception:
                    pass  # nosec B110

            # On Docker bridge networks the host's native worker appears as the
            # bridge gateway IP (e.g. 172.19.0.1), not a local IP.
            if not is_local and ip == _get_docker_gateway():
                is_local = True

            if is_local:
                # Prometheus runs in docker, so it needs host.docker.internal
                # to reach the worker running on the host machine.
                ip = "host.docker.internal"

            try:
                self._update_prometheus_targets(ip, request.hostname)
            except Exception as e:
                logging.getLogger(__name__).error(
                    "Failed to update prometheus targets: %s", e
                )

        return orchestrator_pb2.RegisterNodeResponse(
            success=True, message="Node registered"
        )

    def _update_prometheus_targets(self, ip: str, hostname: str, port: int = 9101):
        targets_file = Path("monitoring/targets.json")
        if not targets_file.exists():
            targets_file.parent.mkdir(parents=True, exist_ok=True)
            workers = []
        else:
            try:
                with open(targets_file, "r") as f:
                    workers = json.load(f)
            except Exception:
                workers = []

        target_str = f"{ip}:{port}"

        # Check if already exists
        for w in workers:
            if target_str in w.get("targets", []):
                # Update the machine label if it changed
                w.setdefault("labels", {})["machine"] = hostname
                with open(targets_file, "w") as f:
                    json.dump(workers, f, indent=2)
                return

        # Add new
        workers.append(
            {
                "targets": [target_str],
                "labels": {"component": "worker_agent", "machine": hostname},
            }
        )

        with open(targets_file, "w") as f:
            json.dump(workers, f, indent=2)

    async def SendHeartbeat(self, request, context):
        from datetime import datetime, timezone

        with self.db_session_factory() as db:
            node = db.query(Node).filter(Node.node_id == request.node_id).first()
            if node:
                node.cpu_utilization_percent = request.cpu_utilization_percent
                node.ram_utilization_percent = request.ram_utilization_percent
                node.ram_available_mb = request.ram_available_mb
                node.last_heartbeat = datetime.now(timezone.utc)

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
        with self.db_session_factory() as db:
            job_id = await self.scheduler.get_next_job_for_node(request.node_id, db)
            if not job_id:
                return orchestrator_pb2.JobRequest(job_id="")

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
