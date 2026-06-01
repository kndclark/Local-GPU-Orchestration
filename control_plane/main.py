from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import asyncio
import uuid
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from prometheus_client import CollectorRegistry, make_asgi_app

from control_plane.database.models import Base, Job, Node, Gpu
from control_plane.scheduler import HardwareAwareScheduler
from control_plane.metrics import ControlPlaneMetrics
from contextlib import asynccontextmanager
import grpc.aio
from control_plane.proto import orchestrator_pb2_grpc
from control_plane.grpc_server import OrchestratorService

# Use a persistent SQLite database so registered nodes survive restarts
engine = create_engine(
    "sqlite:///orchestrator.db",
    connect_args={"check_same_thread": False},
)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

scheduler = HardwareAwareScheduler()
_cp_registry = CollectorRegistry()
cp_metrics = ControlPlaneMetrics(registry=_cp_registry)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gRPC server
    server = grpc.aio.server()
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(
        OrchestratorService(lambda: SessionLocal(), scheduler), server
    )
    server.add_insecure_port("[::]:50051")
    await server.start()
    from control_plane.discovery import ZeroconfAdvertiser

    advertiser = ZeroconfAdvertiser(grpc_port=50051)
    await advertiser.async_start()

    print("gRPC Control Plane listening on [::]:50051")

    # Start metrics refresh background task
    async def _metrics_refresh_loop():
        while True:
            try:
                with SessionLocal() as db:
                    cp_metrics.refresh(db)
            except Exception:  # nosec B110
                pass
            await asyncio.sleep(15)

    metrics_task = asyncio.create_task(_metrics_refresh_loop())

    yield

    metrics_task.cancel()
    await advertiser.async_stop()
    await server.stop(0)


app = FastAPI(title="GPU Orchestrator Control Plane", lifespan=lifespan)

# Mount Prometheus /metrics endpoint
metrics_app = make_asgi_app(registry=_cp_registry)
app.mount("/metrics", metrics_app)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────


class JobCreate(BaseModel):
    workload_type: str
    args: list[str] = []
    env_vars: dict[str, str] = {}
    requires_cuda: bool = False


class JobResponse(BaseModel):
    job_id: str
    workload_type: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class GpuResponse(BaseModel):
    gpu_index: int
    vendor: str
    model_name: str
    driver_version: str
    total_vram_mb: int
    free_vram_mb: int
    used_vram_mb: int
    temperature_c: float
    temperature_hotspot_c: float
    fan_speed_percent: float
    power_draw_w: float
    power_limit_w: float
    gpu_utilization_percent: float
    memory_utilization_percent: float
    encoder_utilization_percent: float
    decoder_utilization_percent: float
    clock_core_mhz: int
    clock_memory_mhz: int
    clock_core_max_mhz: int
    clock_memory_max_mhz: int
    pcie_gen: int
    pcie_width: int
    pcie_bandwidth_percent: float


class NodeResponse(BaseModel):
    node_id: str
    hostname: str
    os: str
    os_version: str
    cpu_count: int
    cpu_model: str
    total_ram_mb: int
    cpu_utilization_percent: float
    ram_utilization_percent: float
    ram_available_mb: int
    supported_workloads: str
    gpus: list[GpuResponse]


class NodeSummary(BaseModel):
    node_id: str
    hostname: str
    os: str
    gpu_count: int
    total_vram_mb: int


# ──────────────────────────────────────────────
# Job endpoints
# ──────────────────────────────────────────────


@app.post("/api/v1/jobs", response_model=JobResponse)
async def submit_job(job_req: JobCreate, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())

    # Save to DB
    job = Job(
        job_id=job_id,
        workload_type=job_req.workload_type,
        args=json.dumps(job_req.args),
        env_vars=json.dumps(job_req.env_vars),
        requires_cuda=job_req.requires_cuda,
        status="PENDING",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Submit to scheduler
    success = await scheduler.submit_job(job_id)
    if not success:
        raise HTTPException(status_code=503, detail="Scheduler queue is full")

    return JobResponse(
        job_id=job_id,
        workload_type=job.workload_type,
        status=job.status,
        created_at=job.created_at.isoformat() if job.created_at else None,
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        job_id=job.job_id,
        workload_type=job.workload_type,
        status=job.status,
        created_at=job.created_at.isoformat() if job.created_at else None,
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
    )


# ──────────────────────────────────────────────
# Node endpoints
# ──────────────────────────────────────────────


def _gpu_to_response(gpu: Gpu) -> GpuResponse:
    return GpuResponse(
        gpu_index=gpu.gpu_index,
        vendor=gpu.vendor,
        model_name=gpu.model_name,
        driver_version=gpu.driver_version,
        total_vram_mb=gpu.total_vram_mb,
        free_vram_mb=gpu.free_vram_mb,
        used_vram_mb=gpu.used_vram_mb,
        temperature_c=gpu.temperature_c,
        temperature_hotspot_c=gpu.temperature_hotspot_c,
        fan_speed_percent=gpu.fan_speed_percent,
        power_draw_w=gpu.power_draw_w,
        power_limit_w=gpu.power_limit_w,
        gpu_utilization_percent=gpu.gpu_utilization_percent,
        memory_utilization_percent=gpu.memory_utilization_percent,
        encoder_utilization_percent=gpu.encoder_utilization_percent,
        decoder_utilization_percent=gpu.decoder_utilization_percent,
        clock_core_mhz=gpu.clock_core_mhz,
        clock_memory_mhz=gpu.clock_memory_mhz,
        clock_core_max_mhz=gpu.clock_core_max_mhz,
        clock_memory_max_mhz=gpu.clock_memory_max_mhz,
        pcie_gen=gpu.pcie_gen,
        pcie_width=gpu.pcie_width,
        pcie_bandwidth_percent=gpu.pcie_bandwidth_percent,
    )


@app.get("/api/v1/nodes", response_model=list[NodeSummary])
async def list_nodes(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    summaries = []
    for node in nodes:
        total_vram = sum(g.total_vram_mb for g in node.gpus)
        summaries.append(
            NodeSummary(
                node_id=node.node_id,
                hostname=node.hostname,
                os=node.os,
                gpu_count=len(node.gpus),
                total_vram_mb=total_vram,
            )
        )
    return summaries


@app.get("/api/v1/nodes/{node_id}", response_model=NodeResponse)
async def get_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.node_id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    return NodeResponse(
        node_id=node.node_id,
        hostname=node.hostname,
        os=node.os,
        os_version=node.os_version,
        cpu_count=node.cpu_count,
        cpu_model=node.cpu_model,
        total_ram_mb=node.total_ram_mb,
        cpu_utilization_percent=node.cpu_utilization_percent,
        ram_utilization_percent=node.ram_utilization_percent,
        ram_available_mb=node.ram_available_mb,
        supported_workloads=node.supported_workloads,
        gpus=[_gpu_to_response(g) for g in node.gpus],
    )


@app.get("/api/v1/nodes/{node_id}/jobs", response_model=list[JobResponse])
async def get_node_jobs(node_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.node_id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Return all jobs assigned to this node, ordered by created_at descending
    jobs = (
        db.query(Job)
        .filter(Job.assigned_node_id == node_id)
        .order_by(Job.created_at.desc())
        .all()
    )

    return [
        JobResponse(
            job_id=j.job_id,
            workload_type=j.workload_type,
            status=j.status,
            created_at=j.created_at.isoformat() if j.created_at else None,
            updated_at=j.updated_at.isoformat() if j.updated_at else None,
        )
        for j in jobs
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "control_plane.main:app",
        host="0.0.0.0",  # nosec B104
        port=8080,
        reload=True,
    )
