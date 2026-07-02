"""Tests for control_plane.metrics — Prometheus cluster-level gauges."""

import pytest
from datetime import datetime, timezone, timedelta
from prometheus_client import CollectorRegistry

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from control_plane.database.models import Base, Node, Gpu, Job, GangJob
from control_plane.metrics import ControlPlaneMetrics


@pytest.fixture
def registry():
    """Fresh Prometheus registry so tests don't leak state."""
    return CollectorRegistry()


@pytest.fixture
def metrics(registry):
    return ControlPlaneMetrics(registry=registry)


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def populated_db(db_session):
    """DB with 2 nodes, 3 GPUs, and jobs in various states."""
    # Node 1: desktop with 1 NVIDIA GPU
    node1 = Node(
        node_id="desktop-001",
        hostname="khamul-desktop",
        os="windows",
        os_version="11",
        cpu_count=16,
        cpu_model="Ryzen 9 7950X",
        total_ram_mb=65536,
        cpu_utilization_percent=25.0,
        ram_utilization_percent=40.0,
        ram_available_mb=39321,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    db_session.add(node1)

    gpu1 = Gpu(
        node_id="desktop-001",
        gpu_index=0,
        vendor="NVIDIA",
        model_name="RTX 4090",
        total_vram_mb=24576,
        free_vram_mb=20000,
        used_vram_mb=4576,
        temperature_c=65.0,
    )
    db_session.add(gpu1)

    # Node 2: ally with 1 AMD GPU
    node2 = Node(
        node_id="ally-002",
        hostname="rog-ally",
        os="linux",
        os_version="6.1.52",
        cpu_count=8,
        cpu_model="Ryzen Z1 Extreme",
        total_ram_mb=16384,
        cpu_utilization_percent=60.0,
        ram_utilization_percent=70.0,
        ram_available_mb=4915,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    db_session.add(node2)

    gpu2 = Gpu(
        node_id="ally-002",
        gpu_index=0,
        vendor="AMD",
        model_name="RDNA 3",
        total_vram_mb=8192,
        free_vram_mb=6000,
        used_vram_mb=2192,
        temperature_c=55.0,
    )
    db_session.add(gpu2)

    # Jobs in various states
    db_session.add(Job(job_id="j1", workload_type="python", status="PENDING"))
    db_session.add(Job(job_id="j2", workload_type="python", status="PENDING"))
    db_session.add(
        Job(
            job_id="j3",
            workload_type="ffmpeg",
            status="RUNNING",
            assigned_node_id="desktop-001",
        )
    )
    db_session.add(Job(job_id="j4", workload_type="python", status="COMPLETED"))
    db_session.add(
        Job(
            job_id="j5",
            workload_type="ffmpeg",
            status="FAILED",
            error_message="Segfault",
        )
    )

    db_session.commit()
    return db_session


# ──────────────────────────────────────────────
# Gauge Registration
# ──────────────────────────────────────────────


class TestGaugeRegistration:
    def test_cluster_gauges_registered(self, metrics, registry):
        families = {m.name for m in registry.collect()}
        for name in [
            "cluster_nodes_total",
            "cluster_gpus_total",
            "cluster_gpus_by_vendor",
            "cluster_vram_total_mb",
            "cluster_vram_free_mb",
            "cluster_jobs_total",
        ]:
            assert name in families, f"Missing cluster gauge: {name}"

    def test_node_gauges_registered(self, metrics, registry):
        families = {m.name for m in registry.collect()}
        for name in [
            "node_cpu_utilization_percent",
            "node_ram_utilization_percent",
            "node_gpu_count",
            "node_last_heartbeat_age_seconds",
        ]:
            assert name in families, f"Missing node gauge: {name}"


# ──────────────────────────────────────────────
# refresh_cluster_metrics
# ──────────────────────────────────────────────


class TestRefreshClusterMetrics:
    def test_cluster_totals(self, metrics, registry, populated_db):
        metrics.refresh(populated_db)

        assert registry.get_sample_value("cluster_nodes_total") == 2
        assert registry.get_sample_value("cluster_gpus_total") == 2
        assert registry.get_sample_value("cluster_vram_total_mb") == (24576 + 8192)
        assert registry.get_sample_value("cluster_vram_free_mb") == (20000 + 6000)

    def test_gpus_by_vendor(self, metrics, registry, populated_db):
        metrics.refresh(populated_db)

        assert (
            registry.get_sample_value("cluster_gpus_by_vendor", {"vendor": "NVIDIA"})
            == 1
        )
        assert (
            registry.get_sample_value("cluster_gpus_by_vendor", {"vendor": "AMD"}) == 1
        )

    def test_job_status_breakdown(self, metrics, registry, populated_db):
        metrics.refresh(populated_db)

        assert (
            registry.get_sample_value("cluster_jobs_total", {"status": "PENDING"}) == 2
        )
        assert (
            registry.get_sample_value("cluster_jobs_total", {"status": "RUNNING"}) == 1
        )
        assert (
            registry.get_sample_value("cluster_jobs_total", {"status": "COMPLETED"})
            == 1
        )
        assert (
            registry.get_sample_value("cluster_jobs_total", {"status": "FAILED"}) == 1
        )

    def test_per_node_metrics(self, metrics, registry, populated_db):
        metrics.refresh(populated_db)

        labels_1 = {"node_id": "desktop-001", "hostname": "khamul-desktop"}
        assert (
            registry.get_sample_value("node_cpu_utilization_percent", labels_1) == 25.0
        )
        assert (
            registry.get_sample_value("node_ram_utilization_percent", labels_1) == 40.0
        )
        assert registry.get_sample_value("node_gpu_count", labels_1) == 1

        labels_2 = {"node_id": "ally-002", "hostname": "rog-ally"}
        assert (
            registry.get_sample_value("node_cpu_utilization_percent", labels_2) == 60.0
        )

    def test_heartbeat_age(self, metrics, registry, populated_db):
        metrics.refresh(populated_db)

        labels_1 = {"node_id": "desktop-001", "hostname": "khamul-desktop"}
        age_1 = registry.get_sample_value("node_last_heartbeat_age_seconds", labels_1)
        # Node 1's heartbeat was 5 seconds ago
        assert 3.0 < age_1 < 30.0

        labels_2 = {"node_id": "ally-002", "hostname": "rog-ally"}
        age_2 = registry.get_sample_value("node_last_heartbeat_age_seconds", labels_2)
        # Node 2's heartbeat was 30 seconds ago
        assert 25.0 < age_2 < 60.0

    def test_empty_database(self, metrics, registry, db_session):
        """refresh() on an empty DB should produce zeros, not crash."""
        metrics.refresh(db_session)

        assert registry.get_sample_value("cluster_nodes_total") == 0
        assert registry.get_sample_value("cluster_gpus_total") == 0
        assert registry.get_sample_value("cluster_vram_total_mb") == 0
        assert registry.get_sample_value("cluster_vram_free_mb") == 0


# ──────────────────────────────────────────────
# Gang job metrics (Phase 5)
# ──────────────────────────────────────────────


def _gang(gang_job_id, status):
    return GangJob(
        gang_job_id=gang_job_id,
        worker_workload_type="w",
        controller_workload_type="c",
        min_vram_mb=1000,
        status=status,
    )


class TestGangMetrics:
    def test_gang_gauge_registered(self, metrics, registry):
        families = {m.name for m in registry.collect()}
        assert "cluster_gang_jobs_total" in families

    def test_gang_job_status_breakdown(self, metrics, registry, db_session):
        db_session.add(_gang("g1", "FORMING"))
        db_session.add(_gang("g2", "RUNNING"))
        db_session.add(_gang("g3", "RUNNING"))
        db_session.add(_gang("g4", "COMPLETED"))
        db_session.commit()

        metrics.refresh(db_session)

        def val(status):
            return registry.get_sample_value(
                "cluster_gang_jobs_total", {"status": status}
            )

        assert val("FORMING") == 1
        assert val("RUNNING") == 2
        assert val("COMPLETED") == 1
        assert val("FAILED") == 0

    def test_gang_metrics_empty_database(self, metrics, registry, db_session):
        metrics.refresh(db_session)
        assert (
            registry.get_sample_value("cluster_gang_jobs_total", {"status": "FORMING"})
            == 0
        )
