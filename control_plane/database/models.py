from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()


class Node(Base):
    __tablename__ = "nodes"

    node_id = Column(String, primary_key=True)
    hostname = Column(String, nullable=False)
    total_vram_mb = Column(Integer, default=0)
    gpu_count = Column(Integer, default=0)
    supported_workloads = Column(String, default="")

    last_heartbeat = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    free_vram_mb = Column(Integer, default=0)
    gpu_temperature_c = Column(Float, default=0.0)
    gpu_utilization_percent = Column(Float, default=0.0)

    jobs = relationship("Job", back_populates="node")


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True)
    workload_type = Column(String, nullable=False)
    args = Column(String, default="[]")  # JSON string
    env_vars = Column(String, default="{}")  # JSON string

    status = Column(String, default="PENDING")
    error_message = Column(String, nullable=True)

    assigned_node_id = Column(String, ForeignKey("nodes.node_id"), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    node = relationship("Node", back_populates="jobs")
