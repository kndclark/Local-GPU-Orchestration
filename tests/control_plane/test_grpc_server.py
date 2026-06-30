import json
import pytest
from unittest.mock import MagicMock, patch

from control_plane.grpc_server import OrchestratorService
from control_plane.proto import orchestrator_pb2
from control_plane.database.models import Node, Job
from control_plane.main import SessionLocal


@pytest.fixture
def clean_db():
    # Provide a clean test database session factory
    with SessionLocal() as db:
        db.query(Node).delete()
        db.commit()
    yield SessionLocal


@pytest.fixture
def mock_scheduler():
    return MagicMock()


@pytest.fixture
def targets_file(tmp_path):
    # The global _isolate_targets_json fixture in conftest.py already redirects
    # Path to tmp_path / "targets.json" for every test; just return that path.
    return tmp_path / "targets.json"


@pytest.mark.asyncio
async def test_update_prometheus_targets(clean_db, mock_scheduler, targets_file):
    """Test that prometheus targets are correctly written to the JSON file."""
    service = OrchestratorService(clean_db, mock_scheduler)

    # 1. Add first worker
    service._update_prometheus_targets("192.168.1.100", "WorkerOne")
    assert targets_file.exists()

    data = json.loads(targets_file.read_text())
    assert len(data) == 1
    assert data[0]["targets"] == ["192.168.1.100:9101"]
    assert data[0]["labels"]["machine"] == "WorkerOne"

    # 2. Add second worker
    service._update_prometheus_targets("10.0.0.5", "WorkerTwo")
    data = json.loads(targets_file.read_text())
    assert len(data) == 2
    assert data[1]["targets"] == ["10.0.0.5:9101"]

    # 3. Update existing worker (machine name changed)
    service._update_prometheus_targets("192.168.1.100", "WorkerOne-Updated")
    data = json.loads(targets_file.read_text())
    assert len(data) == 2
    assert data[0]["labels"]["machine"] == "WorkerOne-Updated"


@pytest.mark.parametrize(
    "metrics_ip, metrics_port, colocated, expected_target",
    [
        # Remote worker: self-advertised LAN IP written verbatim.
        ("192.168.0.55", 9101, False, "192.168.0.55:9101"),
        # Custom metrics port is honored.
        ("192.168.0.55", 9200, False, "192.168.0.55:9200"),
        # Colocated worker is mapped to host.docker.internal.
        ("", 9101, True, "host.docker.internal:9101"),
        # Metrics disabled (no advertised address): no target written.
        ("", 0, False, None),
    ],
)
@pytest.mark.asyncio
async def test_register_node_prometheus_target(
    clean_db,
    mock_scheduler,
    targets_file,
    metrics_ip,
    metrics_port,
    colocated,
    expected_target,
):
    """The worker's self-advertised address determines the Prometheus scrape target."""
    service = OrchestratorService(clean_db, mock_scheduler)
    mock_context = MagicMock()

    req = orchestrator_pb2.RegisterNodeRequest(
        node_id="reg-node",
        hostname="reg-host",
        metrics_ip=metrics_ip,
        metrics_port=metrics_port,
        colocated=colocated,
    )

    resp = await service.RegisterNode(req, mock_context)
    assert resp.success is True

    if expected_target is None:
        assert not targets_file.exists()
    else:
        data = json.loads(targets_file.read_text())
        assert len(data) == 1
        assert data[0]["targets"] == [expected_target]


@pytest.mark.asyncio
async def test_request_job(clean_db, mock_scheduler):
    service = OrchestratorService(clean_db, mock_scheduler)
    mock_context = MagicMock()

    # Setup mock scheduler behavior
    async def mock_get_job(*args, **kwargs):
        return "job-123"

    mock_scheduler.get_next_job_for_node = mock_get_job

    with clean_db() as db:
        job = Job(job_id="job-123", workload_type="test", status="PENDING")
        db.add(job)
        db.commit()

    req = orchestrator_pb2.JobRequestPlaceholder(node_id="test-node")
    resp = await service.RequestJob(req, mock_context)

    assert resp.job_id == "job-123"
    assert resp.workload_type == "test"

    with clean_db() as db:
        job = db.query(Job).filter(Job.job_id == "job-123").first()
        assert job.status == "RUNNING"
        assert job.assigned_node_id == "test-node"


@pytest.mark.asyncio
async def test_request_job_no_job(clean_db, mock_scheduler):
    service = OrchestratorService(clean_db, mock_scheduler)
    mock_context = MagicMock()

    async def mock_get_no_job(*args, **kwargs):
        return None

    mock_scheduler.get_next_job_for_node = mock_get_no_job

    req = orchestrator_pb2.JobRequestPlaceholder(node_id="test-node")
    resp = await service.RequestJob(req, mock_context)

    assert resp.job_id == ""


@pytest.mark.asyncio
async def test_send_heartbeat_updates_last_heartbeat(clean_db, mock_scheduler):
    service = OrchestratorService(clean_db, mock_scheduler)
    mock_context = MagicMock()

    from datetime import datetime, timezone, timedelta

    old_time = datetime.now(timezone.utc) - timedelta(minutes=5)

    with clean_db() as db:
        node = Node(node_id="hb-test", hostname="host", last_heartbeat=old_time)
        db.add(node)
        db.commit()

    req = orchestrator_pb2.HeartbeatRequest(
        node_id="hb-test",
        cpu_utilization_percent=50.0,
        ram_utilization_percent=50.0,
        ram_available_mb=1000,
        gpus=[],
    )
    resp = await service.SendHeartbeat(req, mock_context)
    assert resp.acknowledged is True

    with clean_db() as db:
        node = db.query(Node).filter(Node.node_id == "hb-test").first()
        hb = (
            node.last_heartbeat.replace(tzinfo=timezone.utc)
            if node.last_heartbeat.tzinfo is None
            else node.last_heartbeat
        )
        assert hb > old_time
