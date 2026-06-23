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


@pytest.mark.asyncio
async def test_register_node_remote_ip(clean_db, mock_scheduler, targets_file):
    """Test that a remote IP does not get mapped to host.docker.internal."""
    service = OrchestratorService(clean_db, mock_scheduler)

    mock_context = MagicMock()
    mock_context.peer.return_value = "ipv4:192.168.1.100:54321"

    req = orchestrator_pb2.RegisterNodeRequest(
        node_id="test-node-remote", hostname="test-host", os="linux"
    )

    # Mock socket to ensure 192.168.1.100 is NOT considered a local IP
    with patch("socket.gethostbyname_ex", return_value=("test", [], ["10.0.0.1"])):
        resp = await service.RegisterNode(req, mock_context)

    assert resp.success is True

    # Verify targets.json
    data = json.loads(targets_file.read_text())
    assert len(data) == 1
    assert data[0]["targets"] == ["192.168.1.100:9101"]


@pytest.mark.asyncio
async def test_register_node_localhost(clean_db, mock_scheduler, targets_file):
    """Test that 127.0.0.1 is mapped to host.docker.internal."""
    service = OrchestratorService(clean_db, mock_scheduler)

    mock_context = MagicMock()
    mock_context.peer.return_value = "ipv4:127.0.0.1:54321"

    req = orchestrator_pb2.RegisterNodeRequest(
        node_id="test-node-local", hostname="test-host"
    )

    resp = await service.RegisterNode(req, mock_context)
    assert resp.success is True

    data = json.loads(targets_file.read_text())
    assert len(data) == 1
    assert data[0]["targets"] == ["host.docker.internal:9101"]


@pytest.mark.asyncio
async def test_register_node_local_host_ip(clean_db, mock_scheduler, targets_file):
    """
    Test that an IP belonging to the host machine is mapped to host.docker.internal.
    """
    service = OrchestratorService(clean_db, mock_scheduler)

    mock_context = MagicMock()
    # E.g. worker connects via WSL virtual IP
    mock_context.peer.return_value = "ipv4:192.168.64.1:54321"

    req = orchestrator_pb2.RegisterNodeRequest(
        node_id="test-node-host-ip", hostname="test-host"
    )

    # Mock socket to claim that 192.168.64.1 is one of the host's local IPs
    with patch(
        "socket.gethostbyname_ex",
        return_value=("test-pc", [], ["192.168.0.50", "192.168.64.1"]),
    ):
        resp = await service.RegisterNode(req, mock_context)

    assert resp.success is True

    data = json.loads(targets_file.read_text())
    assert len(data) == 1
    # It must be mapped!
    assert data[0]["targets"] == ["host.docker.internal:9101"]


@pytest.mark.asyncio
async def test_register_node_docker_gateway(clean_db, mock_scheduler, targets_file):
    """Test that the Docker bridge gateway IP is mapped to host.docker.internal.

    On bridge-networked Docker containers, connections from the host's native
    worker appear as the default gateway IP (e.g. 172.19.0.1). This test
    verifies that IP is correctly translated to host.docker.internal so
    Prometheus can scrape the co-located worker.
    """
    service = OrchestratorService(clean_db, mock_scheduler)

    mock_context = MagicMock()
    mock_context.peer.return_value = "ipv4:172.19.0.1:54321"

    req = orchestrator_pb2.RegisterNodeRequest(
        node_id="test-node-gateway", hostname="test-host"
    )

    with patch(
        "socket.gethostbyname_ex", return_value=("container", [], ["172.19.0.2"])
    ):
        with patch(
            "control_plane.grpc_server._get_docker_gateway", return_value="172.19.0.1"
        ):
            resp = await service.RegisterNode(req, mock_context)

    assert resp.success is True
    data = json.loads(targets_file.read_text())
    assert len(data) == 1
    assert data[0]["targets"] == ["host.docker.internal:9101"]


@pytest.mark.asyncio
async def test_register_node_docker_gateway_no_match(
    clean_db, mock_scheduler, targets_file
):
    """
    Test that a non-gateway remote IP is not incorrectly mapped
    when gateway detection runs.
    """
    service = OrchestratorService(clean_db, mock_scheduler)

    mock_context = MagicMock()
    mock_context.peer.return_value = "ipv4:192.168.1.100:54321"

    req = orchestrator_pb2.RegisterNodeRequest(
        node_id="test-node-remote2", hostname="remote-host"
    )

    with patch(
        "socket.gethostbyname_ex", return_value=("container", [], ["172.19.0.2"])
    ):
        with patch(
            "control_plane.grpc_server._get_docker_gateway", return_value="172.19.0.1"
        ):
            resp = await service.RegisterNode(req, mock_context)

    assert resp.success is True
    data = json.loads(targets_file.read_text())
    assert len(data) == 1
    assert data[0]["targets"] == ["192.168.1.100:9101"]


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
