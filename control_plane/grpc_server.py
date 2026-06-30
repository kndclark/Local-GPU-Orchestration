import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from control_plane.proto import orchestrator_pb2, orchestrator_pb2_grpc
from control_plane.database.models import Node, Gpu, Job
from control_plane.metrics import STALE_NODE_SECONDS
from control_plane.scheduler import HardwareAwareScheduler


def compute_active_machines(db, now: datetime | None = None) -> set[str]:
    """Return the hostnames of nodes that are currently active (live).

    A node is active if it registered or sent a heartbeat within
    ``STALE_NODE_SECONDS``. ``now`` is injectable for deterministic testing.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    active: set[str] = set()
    for node in db.query(Node).all():
        hb = node.last_heartbeat
        if hb is None:
            continue
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        if (now - hb).total_seconds() < STALE_NODE_SECONDS:
            active.add(node.hostname)
    return active


def reconcile_prometheus_targets(
    active_machines, targets_path: str = "monitoring/targets.json"
) -> int:
    """Remove Prometheus scrape targets for workers that are no longer active.

    A target is kept only if its ``machine`` label matches the hostname of a
    currently-active node (one that has sent a heartbeat within the stale
    window). This stops Prometheus from scraping dead workers, so their stale
    series drop off the dashboards instead of accumulating.

    Args:
        active_machines: Hostnames (machine labels) of currently-active nodes.
        targets_path: Path to the Prometheus file_sd targets file.

    Returns:
        The number of target entries removed.
    """
    targets_file = Path(targets_path)
    if not targets_file.exists():
        return 0
    try:
        with open(targets_file, "r") as f:
            workers = json.load(f)
    except (OSError, ValueError):
        return 0

    kept = [w for w in workers if w.get("labels", {}).get("machine") in active_machines]
    removed = len(workers) - len(kept)
    if removed:
        with open(targets_file, "w") as f:
            json.dump(kept, f, indent=2)
    return removed


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
            node.last_heartbeat = datetime.now(timezone.utc)

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

        # Register the worker's self-advertised metrics endpoint with Prometheus.
        # The worker tells us where it can be scraped because we can't infer it
        # from the gRPC peer behind a Docker Desktop port proxy (every external
        # peer appears as the bridge gateway).
        if request.colocated:
            # Worker shares the host with the (Dockerized) control plane;
            # Prometheus must reach it via host.docker.internal, not a LAN IP.
            metrics_ip = "host.docker.internal"
        else:
            metrics_ip = request.metrics_ip

        metrics_port = request.metrics_port or 9101

        if metrics_ip:
            try:
                self._update_prometheus_targets(
                    metrics_ip, request.hostname, port=metrics_port
                )
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
