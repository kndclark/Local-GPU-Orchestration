from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import uuid
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from control_plane.database.models import Base, Job
from control_plane.scheduler import FIFOScheduler

# For phase 1, we use in-memory sqlite to avoid requiring running Postgres just for tests.
engine = create_engine(
    "sqlite:///:memory:", 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

scheduler = FIFOScheduler(maxsize=100)
app = FastAPI(title="GPU Orchestrator Control Plane")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class JobCreate(BaseModel):
    workload_type: str
    args: list[str] = []
    env_vars: dict[str, str] = {}

class JobResponse(BaseModel):
    job_id: str
    status: str

@app.post("/api/v1/jobs", response_model=JobResponse)
async def submit_job(job_req: JobCreate, db: Session = Depends(get_db)):
    job_id = str(uuid.uuid4())
    
    # Save to DB
    job = Job(
        job_id=job_id,
        workload_type=job_req.workload_type,
        args=json.dumps(job_req.args),
        env_vars=json.dumps(job_req.env_vars),
        status="PENDING"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Submit to scheduler
    success = await scheduler.submit_job(job_id)
    if not success:
        raise HTTPException(status_code=503, detail="Scheduler queue is full")

    return JobResponse(job_id=job_id, status=job.status)
