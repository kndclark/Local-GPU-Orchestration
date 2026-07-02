import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from control_plane.database.models import (
    Base,
    Node,
    Gpu,
    Job,
    GangJob,
    GangJobParticipant,
)


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


# ──────────────────────────────────────────────
# GangJob / GangJobParticipant model tests (Phase 5)
# ──────────────────────────────────────────────


class TestGangJobModel:
    def test_create_gang_job_with_fields(self, db_session):
        gang = GangJob(
            gang_job_id="gang-1",
            worker_workload_type="llama_rpc_server",
            worker_args='["--host", "0.0.0.0", "--port", "50052"]',
            worker_ready_signal="listening",
            worker_port=50052,
            controller_workload_type="llama_cli",
            controller_args='["--model", "/models/llama-70b.gguf"]',
            controller_endpoints_flag="--rpc",
            min_vram_mb=40000,
            requires_cuda=True,
        )
        db_session.add(gang)
        db_session.commit()

        retrieved = db_session.query(GangJob).filter_by(gang_job_id="gang-1").first()
        assert retrieved is not None
        assert retrieved.worker_workload_type == "llama_rpc_server"
        assert retrieved.worker_args == '["--host", "0.0.0.0", "--port", "50052"]'
        assert retrieved.worker_ready_signal == "listening"
        assert retrieved.worker_port == 50052
        assert retrieved.controller_workload_type == "llama_cli"
        assert retrieved.controller_args == '["--model", "/models/llama-70b.gguf"]'
        assert retrieved.controller_endpoints_flag == "--rpc"
        assert retrieved.min_vram_mb == 40000
        assert retrieved.requires_cuda is True

    def test_gang_job_defaults(self, db_session):
        gang = GangJob(
            gang_job_id="gang-min",
            worker_workload_type="llama_rpc_server",
            controller_workload_type="llama_cli",
            min_vram_mb=1000,
        )
        db_session.add(gang)
        db_session.commit()

        retrieved = db_session.query(GangJob).filter_by(gang_job_id="gang-min").first()
        assert retrieved.status == "FORMING"
        assert retrieved.requires_cuda is False
        assert retrieved.controller_args == "[]"
        assert retrieved.worker_args == "[]"
        assert retrieved.worker_ready_signal == ""
        assert retrieved.worker_port == 0
        assert retrieved.controller_endpoints_flag == "--rpc"
        assert retrieved.participants == []
        assert retrieved.created_at is not None
        assert retrieved.updated_at is not None

    @pytest.mark.parametrize(
        "status",
        ["FORMING", "RUNNING", "COMPLETED", "FAILED"],
    )
    def test_gang_job_status_transitions(self, db_session, status):
        gang = GangJob(
            gang_job_id=f"gang-{status}",
            worker_workload_type="w",
            controller_workload_type="c",
            min_vram_mb=1000,
            status=status,
        )
        db_session.add(gang)
        db_session.commit()

        retrieved = (
            db_session.query(GangJob).filter_by(gang_job_id=f"gang-{status}").first()
        )
        assert retrieved.status == status


class TestGangJobParticipantModel:
    def _make_gang_and_nodes(self, db_session):
        gang = GangJob(
            gang_job_id="gang-1",
            worker_workload_type="llama_rpc_server",
            controller_workload_type="llama_cli",
            min_vram_mb=40000,
        )
        db_session.add(gang)
        for node_id in ("worker-node", "controller-node"):
            db_session.add(Node(node_id=node_id, hostname=node_id))
        db_session.commit()
        return gang

    def test_create_participants_with_roles(self, db_session):
        self._make_gang_and_nodes(db_session)

        worker = GangJobParticipant(
            gang_job_id="gang-1",
            node_id="worker-node",
            role="worker",
            job_id=None,
            endpoint=None,
        )
        controller = GangJobParticipant(
            gang_job_id="gang-1",
            node_id="controller-node",
            role="controller",
        )
        db_session.add_all([worker, controller])
        db_session.commit()

        parts = (
            db_session.query(GangJobParticipant)
            .filter_by(gang_job_id="gang-1")
            .order_by(GangJobParticipant.role)
            .all()
        )
        assert len(parts) == 2
        assert {p.role for p in parts} == {"worker", "controller"}

    def test_participant_endpoint_starts_null_then_updates(self, db_session):
        self._make_gang_and_nodes(db_session)
        worker = GangJobParticipant(
            gang_job_id="gang-1", node_id="worker-node", role="worker"
        )
        db_session.add(worker)
        db_session.commit()

        assert worker.endpoint is None
        assert worker.job_id is None

        worker.endpoint = "192.168.1.50:50052"
        db_session.commit()

        retrieved = (
            db_session.query(GangJobParticipant).filter_by(role="worker").first()
        )
        assert retrieved.endpoint == "192.168.1.50:50052"

    def test_gang_job_participants_relationship(self, db_session):
        self._make_gang_and_nodes(db_session)
        db_session.add_all(
            [
                GangJobParticipant(
                    gang_job_id="gang-1", node_id="worker-node", role="worker"
                ),
                GangJobParticipant(
                    gang_job_id="gang-1", node_id="controller-node", role="controller"
                ),
            ]
        )
        db_session.commit()

        gang = db_session.query(GangJob).filter_by(gang_job_id="gang-1").first()
        assert len(gang.participants) == 2
        assert gang.participants[0].gang_job.gang_job_id == "gang-1"

    def test_cascade_delete_participants(self, db_session):
        """Deleting a GangJob should cascade-delete its participants."""
        self._make_gang_and_nodes(db_session)
        db_session.add(
            GangJobParticipant(
                gang_job_id="gang-1", node_id="worker-node", role="worker"
            )
        )
        db_session.commit()
        assert db_session.query(GangJobParticipant).count() == 1

        gang = db_session.query(GangJob).filter_by(gang_job_id="gang-1").first()
        db_session.delete(gang)
        db_session.commit()

        assert db_session.query(GangJobParticipant).count() == 0
