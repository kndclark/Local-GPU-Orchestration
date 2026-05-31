"""Integration tests for Prometheus metrics endpoints.

Verifies that the /metrics endpoints on both the control plane and
worker agent return valid Prometheus exposition format with expected
metric families.
"""

import pytest
from fastapi.testclient import TestClient

from control_plane.main import app, SessionLocal, cp_metrics
from control_plane.database.models import Node, Gpu, Job
from prometheus_client.parser import text_string_to_metric_families


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_db():
    """Seed the control plane DB with a node + GPU for metrics testing."""
    with SessionLocal() as db:
        # Clean up first
        db.query(Job).delete()
        db.query(Gpu).delete()
        db.query(Node).delete()
        db.commit()

        node = Node(
            node_id="integration-node",
            hostname="test-host",
            os="linux",
            cpu_utilization_percent=42.0,
            ram_utilization_percent=55.0,
        )
        db.add(node)

        gpu = Gpu(
            node_id="integration-node",
            gpu_index=0,
            vendor="NVIDIA",
            model_name="RTX 4090",
            total_vram_mb=24576,
            free_vram_mb=20000,
            temperature_c=65.0,
        )
        db.add(gpu)

        db.add(Job(job_id="ij1", workload_type="python", status="PENDING"))
        db.add(
            Job(
                job_id="ij2",
                workload_type="ffmpeg",
                status="RUNNING",
                assigned_node_id="integration-node",
            )
        )
        db.commit()

        # Force an immediate metrics refresh so gauges are populated
        cp_metrics.refresh(db)

    yield

    # Cleanup
    with SessionLocal() as db:
        db.query(Job).delete()
        db.query(Gpu).delete()
        db.query(Node).delete()
        db.commit()


class TestControlPlaneMetricsEndpoint:
    """Verify the /metrics endpoint returns valid Prometheus text format."""

    def test_metrics_endpoint_returns_200(self, client):
        resp = client.get("/metrics/")
        assert resp.status_code == 200

    def test_metrics_endpoint_content_type(self, client):
        resp = client.get("/metrics/")
        content_type = resp.headers.get("content-type", "")
        assert "text/plain" in content_type or "text/plain" in content_type

    def test_metrics_contain_cluster_gauges(self, client, seeded_db):
        resp = client.get("/metrics/")
        text = resp.text

        expected_metrics = [
            "cluster_nodes_total",
            "cluster_gpus_total",
            "cluster_gpus_by_vendor",
            "cluster_vram_total_mb",
            "cluster_vram_free_mb",
            "cluster_jobs_total",
        ]
        for metric in expected_metrics:
            assert metric in text, f"Missing metric: {metric}"

    def test_metrics_contain_node_gauges(self, client, seeded_db):
        resp = client.get("/metrics/")
        text = resp.text

        expected_metrics = [
            "node_cpu_utilization_percent",
            "node_ram_utilization_percent",
            "node_gpu_count",
            "node_last_heartbeat_age_seconds",
        ]
        for metric in expected_metrics:
            assert metric in text, f"Missing metric: {metric}"

    def test_metrics_parseable_as_prometheus_format(self, client, seeded_db):
        """Verify the output is valid Prometheus exposition format."""
        resp = client.get("/metrics/")
        families = list(text_string_to_metric_families(resp.text))
        family_names = {f.name for f in families}

        assert "cluster_nodes_total" in family_names
        assert "cluster_gpus_total" in family_names

    def test_metrics_values_match_db(self, client, seeded_db):
        """Verify that metric values reflect the seeded database state."""
        resp = client.get("/metrics/")
        families = {f.name: f for f in text_string_to_metric_families(resp.text)}

        # cluster_nodes_total should be 1
        nodes_samples = families["cluster_nodes_total"].samples
        assert any(s.value == 1.0 for s in nodes_samples)

        # cluster_gpus_total should be 1
        gpus_samples = families["cluster_gpus_total"].samples
        assert any(s.value == 1.0 for s in gpus_samples)

        # cluster_gpus_by_vendor{vendor="NVIDIA"} should be 1
        vendor_samples = families["cluster_gpus_by_vendor"].samples
        nvidia_samples = [
            s for s in vendor_samples if s.labels.get("vendor") == "NVIDIA"
        ]
        assert len(nvidia_samples) >= 1
        assert nvidia_samples[0].value == 1.0

        # cluster_jobs_total{status="PENDING"} should be 1
        job_samples = families["cluster_jobs_total"].samples
        pending = [s for s in job_samples if s.labels.get("status") == "PENDING"]
        assert len(pending) >= 1
        assert pending[0].value == 1.0

        running = [s for s in job_samples if s.labels.get("status") == "RUNNING"]
        assert len(running) >= 1
        assert running[0].value == 1.0
