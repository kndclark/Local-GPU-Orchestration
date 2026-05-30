import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from control_plane.database.models import Base, Node, Gpu, Job


# Pytest fixture to setup an in-memory SQLite database
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ──────────────────────────────────────────────
# Node model tests
# ──────────────────────────────────────────────


class TestNodeModel:
    def test_create_node_with_system_info(self, db_session):
        node = Node(
            node_id="desktop-1",
            hostname="desktop-rtx",
            os="windows",
            os_version="11",
            cpu_count=16,
            cpu_model="Intel i9-13900K",
            total_ram_mb=65536,
            supported_workloads="cuda,ffmpeg",
        )
        db_session.add(node)
        db_session.commit()

        retrieved = db_session.query(Node).filter_by(node_id="desktop-1").first()
        assert retrieved is not None
        assert retrieved.hostname == "desktop-rtx"
        assert retrieved.os == "windows"
        assert retrieved.cpu_count == 16
        assert retrieved.cpu_model == "Intel i9-13900K"
        assert retrieved.total_ram_mb == 65536
        assert retrieved.supported_workloads == "cuda,ffmpeg"

    def test_node_defaults(self, db_session):
        node = Node(node_id="minimal", hostname="test")
        db_session.add(node)
        db_session.commit()

        retrieved = db_session.query(Node).filter_by(node_id="minimal").first()
        assert retrieved.os == ""
        assert retrieved.cpu_count == 0
        assert retrieved.cpu_utilization_percent == 0.0
        assert retrieved.ram_utilization_percent == 0.0
        assert retrieved.gpus == []

    def test_node_telemetry_update(self, db_session):
        node = Node(node_id="node-1", hostname="test")
        db_session.add(node)
        db_session.commit()

        node.cpu_utilization_percent = 45.0
        node.ram_utilization_percent = 62.0
        node.ram_available_mb = 25000
        db_session.commit()

        retrieved = db_session.query(Node).filter_by(node_id="node-1").first()
        assert retrieved.cpu_utilization_percent == 45.0
        assert retrieved.ram_utilization_percent == 62.0
        assert retrieved.ram_available_mb == 25000


# ──────────────────────────────────────────────
# Gpu model tests
# ──────────────────────────────────────────────


class TestGpuModel:
    @pytest.mark.parametrize(
        "vendor,model_name,vram",
        [
            ("NVIDIA", "RTX 4090", 24576),
            ("AMD", "RX 7600", 8192),
            ("NVIDIA", "RTX 4060 Ti", 16384),
        ],
        ids=["nvidia-4090", "amd-7600", "nvidia-4060ti"],
    )
    def test_create_gpu(self, db_session, vendor, model_name, vram):
        node = Node(node_id="test-node", hostname="test")
        db_session.add(node)
        db_session.commit()

        gpu = Gpu(
            node_id="test-node",
            gpu_index=0,
            vendor=vendor,
            model_name=model_name,
            total_vram_mb=vram,
        )
        db_session.add(gpu)
        db_session.commit()

        retrieved = db_session.query(Gpu).filter_by(node_id="test-node").first()
        assert retrieved.vendor == vendor
        assert retrieved.model_name == model_name
        assert retrieved.total_vram_mb == vram

    def test_gpu_defaults_are_sentinel(self, db_session):
        """All telemetry fields should default to -1 (sensor not available)."""
        node = Node(node_id="test-node", hostname="test")
        db_session.add(node)
        gpu = Gpu(node_id="test-node", gpu_index=0)
        db_session.add(gpu)
        db_session.commit()

        retrieved = db_session.query(Gpu).first()
        assert retrieved.free_vram_mb == -1
        assert retrieved.temperature_c == -1.0
        assert retrieved.fan_speed_percent == -1.0
        assert retrieved.power_draw_w == -1.0
        assert retrieved.clock_core_mhz == -1
        assert retrieved.pcie_gen == -1

    def test_gpu_telemetry_update(self, db_session):
        node = Node(node_id="test-node", hostname="test")
        db_session.add(node)
        gpu = Gpu(
            node_id="test-node",
            gpu_index=0,
            vendor="NVIDIA",
            model_name="RTX 4090",
            total_vram_mb=24576,
        )
        db_session.add(gpu)
        db_session.commit()

        gpu.temperature_c = 72.0
        gpu.gpu_utilization_percent = 95.0
        gpu.free_vram_mb = 12000
        gpu.used_vram_mb = 12576
        gpu.clock_core_mhz = 2520
        gpu.pcie_gen = 4
        gpu.pcie_width = 16
        db_session.commit()

        retrieved = db_session.query(Gpu).first()
        assert retrieved.temperature_c == 72.0
        assert retrieved.gpu_utilization_percent == 95.0
        assert retrieved.clock_core_mhz == 2520
        assert retrieved.pcie_gen == 4


# ──────────────────────────────────────────────
# Node ↔ Gpu relationship tests
# ──────────────────────────────────────────────


class TestNodeGpuRelationship:
    def test_node_with_multiple_gpus(self, db_session):
        node = Node(node_id="multi-gpu", hostname="workstation")
        db_session.add(node)

        for i in range(4):
            gpu = Gpu(
                node_id="multi-gpu",
                gpu_index=i,
                vendor="NVIDIA",
                model_name=f"RTX 4090 #{i}",
                total_vram_mb=24576,
            )
            db_session.add(gpu)
        db_session.commit()

        retrieved = db_session.query(Node).filter_by(node_id="multi-gpu").first()
        assert len(retrieved.gpus) == 4
        assert all(g.vendor == "NVIDIA" for g in retrieved.gpus)

    def test_cascade_delete_orphan(self, db_session):
        """Deleting a Node should cascade-delete its GPUs."""
        node = Node(node_id="delete-me", hostname="test")
        db_session.add(node)
        gpu = Gpu(node_id="delete-me", gpu_index=0, vendor="AMD")
        db_session.add(gpu)
        db_session.commit()

        assert db_session.query(Gpu).count() == 1

        db_session.delete(node)
        db_session.commit()

        assert db_session.query(Gpu).count() == 0

    def test_gpu_back_populates_node(self, db_session):
        node = Node(node_id="bp-test", hostname="test")
        db_session.add(node)
        gpu = Gpu(node_id="bp-test", gpu_index=0, vendor="NVIDIA")
        db_session.add(gpu)
        db_session.commit()

        retrieved_gpu = db_session.query(Gpu).first()
        assert retrieved_gpu.node.node_id == "bp-test"
        assert retrieved_gpu.node.hostname == "test"


# ──────────────────────────────────────────────
# Job model tests (preserved from Phase 1)
# ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "status, expected_valid",
    [
        ("PENDING", True),
        ("RUNNING", True),
        ("COMPLETED", True),
        ("FAILED", True),
    ],
)
def test_create_job(db_session, status, expected_valid):
    node = Node(node_id="worker-1", hostname="worker")
    db_session.add(node)

    job = Job(
        job_id="job-123",
        workload_type="ffmpeg",
        args="[]",
        env_vars="{}",
        status=status,
        assigned_node_id="worker-1",
    )
    db_session.add(job)
    db_session.commit()

    retrieved = db_session.query(Job).filter_by(job_id="job-123").first()
    assert retrieved is not None
    assert retrieved.status == status
    assert retrieved.node.node_id == "worker-1"
