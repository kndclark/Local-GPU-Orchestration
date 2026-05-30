from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uuid
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from control_plane.database.models import Base, Job, Node, Gpu
from control_plane.scheduler import FIFOScheduler
from contextlib import asynccontextmanager
import grpc.aio
from control_plane.proto import orchestrator_pb2_grpc
from control_plane.grpc_server import OrchestratorService

# For phase 1/2, we use in-memory sqlite to avoid requiring
# running Postgres just for tests.
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

scheduler = FIFOScheduler(maxsize=100)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gRPC server
    server = grpc.aio.server()
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(
        OrchestratorService(lambda: SessionLocal(), scheduler), server
    )
    server.add_insecure_port("[::]:50051")
    await server.start()
    print("gRPC Control Plane listening on [::]:50051")
    yield
    await server.stop(0)


app = FastAPI(title="GPU Orchestrator Control Plane", lifespan=lifespan)


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


class JobResponse(BaseModel):
    job_id: str
    status: str


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
        status="PENDING",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Submit to scheduler
    success = await scheduler.submit_job(job_id)
    if not success:
        raise HTTPException(status_code=503, detail="Scheduler queue is full")

    return JobResponse(job_id=job_id, status=job.status)


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "control_plane.main:app", host="0.0.0.0", port=8000, reload=True
    )  # nosec B104
