from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()


class Node(Base):
    __tablename__ = "nodes"

    node_id = Column(String, primary_key=True)
    hostname = Column(String, nullable=False)
    supported_workloads = Column(String, default="")

    # System info
    os = Column(String, default="")
    os_version = Column(String, default="")
    cpu_count = Column(Integer, default=0)
    cpu_model = Column(String, default="")
    total_ram_mb = Column(Integer, default=0)

    # Live system telemetry
    cpu_utilization_percent = Column(Float, default=0.0)
    ram_utilization_percent = Column(Float, default=0.0)
    ram_available_mb = Column(Integer, default=0)

    last_heartbeat = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    gpus = relationship("Gpu", back_populates="node", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="node")


class Gpu(Base):
    __tablename__ = "gpus"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String, ForeignKey("nodes.node_id"), nullable=False)
    gpu_index = Column(Integer, nullable=False)

    # Static info
    vendor = Column(String, default="")
    model_name = Column(String, default="")
    driver_version = Column(String, default="")

    # Memory
    total_vram_mb = Column(Integer, default=0)
    free_vram_mb = Column(Integer, default=-1)
    used_vram_mb = Column(Integer, default=-1)

    # Thermals & Power
    temperature_c = Column(Float, default=-1.0)
    temperature_hotspot_c = Column(Float, default=-1.0)
    fan_speed_percent = Column(Float, default=-1.0)
    power_draw_w = Column(Float, default=-1.0)
    power_limit_w = Column(Float, default=-1.0)

    # Utilization
    gpu_utilization_percent = Column(Float, default=-1.0)
    memory_utilization_percent = Column(Float, default=-1.0)
    encoder_utilization_percent = Column(Float, default=-1.0)
    decoder_utilization_percent = Column(Float, default=-1.0)

    # Clocks
    clock_core_mhz = Column(Integer, default=-1)
    clock_memory_mhz = Column(Integer, default=-1)
    clock_core_max_mhz = Column(Integer, default=-1)
    clock_memory_max_mhz = Column(Integer, default=-1)

    # PCIe
    pcie_gen = Column(Integer, default=-1)
    pcie_width = Column(Integer, default=-1)
    pcie_bandwidth_percent = Column(Float, default=-1.0)

    node = relationship("Node", back_populates="gpus")


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True)
    workload_type = Column(String, nullable=False)
    args = Column(String, default="[]")  # JSON string
    env_vars = Column(String, default="{}")  # JSON string
    requires_cuda = Column(Boolean, default=False)

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
