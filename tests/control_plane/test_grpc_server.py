import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from control_plane.grpc_server import (
    OrchestratorService,
    compute_active_machines,
    reconcile_prometheus_targets,
)
from control_plane.metrics import STALE_NODE_SECONDS
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
async def test_update_prometheus_targets_uses_targets_subdir(
    clean_db, mock_scheduler, tmp_path, monkeypatch
):
    """Targets live in a targets/ subdirectory, created if absent.

    Prometheus bind-mounts the targets *directory*, not a single file — a
    single-file bind mount makes Docker create targets.json as a root-owned
    directory on a fresh host. Writing into monitoring/targets/ keeps the
    mount a real directory that Docker (and the control plane) handle cleanly.
    """
    import control_plane.grpc_server as gs

    # Honor the real relative path (rooted under tmp_path) so the nested
    # location can be asserted; overrides conftest's path-flattening fixture.
    monkeypatch.setattr(gs, "Path", lambda p: tmp_path / p)

    service = OrchestratorService(clean_db, mock_scheduler)
    service._update_prometheus_targets("192.168.1.100", "WorkerOne")

    expected = tmp_path / "monitoring" / "targets" / "workers.json"
    assert expected.exists(), "targets must be written under monitoring/targets/"
    data = json.loads(expected.read_text())
    assert data[0]["labels"]["machine"] == "WorkerOne"


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


# ──────────────────────────────────────────────
# Stale-node detection + Prometheus target pruning
# ──────────────────────────────────────────────

_FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "hb_offset_seconds, expected_active",
    [
        pytest.param(0, True, id="exactly-now"),
        pytest.param(STALE_NODE_SECONDS // 2, True, id="mid-window"),
        pytest.param(STALE_NODE_SECONDS - 1, True, id="just-inside-window"),
        pytest.param(STALE_NODE_SECONDS, False, id="exactly-at-boundary"),
        pytest.param(STALE_NODE_SECONDS + 1, False, id="just-past-window"),
        pytest.param(STALE_NODE_SECONDS * 10, False, id="long-stale"),
    ],
)
def test_compute_active_machines_staleness(
    clean_db, hb_offset_seconds, expected_active
):
    """A node counts as active only if its heartbeat is within the stale window.

    Offsets are expressed relative to STALE_NODE_SECONDS so the boundary
    semantics still hold if the window is ever retuned.
    """
    with clean_db() as db:
        db.add(
            Node(
                node_id="n1",
                hostname="host1",
                last_heartbeat=_FIXED_NOW - timedelta(seconds=hb_offset_seconds),
            )
        )
        db.commit()

    with clean_db() as db:
        active = compute_active_machines(db, now=_FIXED_NOW)

    assert active == ({"host1"} if expected_active else set())


def test_compute_active_machines_treats_naive_heartbeat_as_utc(clean_db):
    """SQLite returns naive datetimes; they must be interpreted as UTC.

    This is the real production path (the DB layer strips tzinfo), so assert
    it explicitly rather than relying on the round-trip in other tests.
    """
    naive_recent = datetime(2026, 1, 1, 11, 59, 30)  # 30s before _FIXED_NOW, no tz
    assert naive_recent.tzinfo is None

    with clean_db() as db:
        db.add(Node(node_id="n1", hostname="naive-host", last_heartbeat=naive_recent))
        db.commit()

    with clean_db() as db:
        active = compute_active_machines(db, now=_FIXED_NOW)

    assert active == {"naive-host"}


def test_compute_active_machines_excludes_null_heartbeat(clean_db):
    """A node that has never reported (NULL heartbeat) is not active."""
    with clean_db() as db:
        node = Node(node_id="never", hostname="never-host")
        db.add(node)
        db.commit()
        # Force a NULL heartbeat (bypasses the column default, which only
        # applies on INSERT) to exercise the defensive None branch.
        node.last_heartbeat = None
        db.commit()

    with clean_db() as db:
        active = compute_active_machines(db, now=_FIXED_NOW)

    assert active == set()


def test_compute_active_machines_mixed(clean_db):
    """Only the live nodes' hostnames are returned from a mixed population."""
    with clean_db() as db:
        db.add(
            Node(
                node_id="a",
                hostname="alive",
                last_heartbeat=_FIXED_NOW - timedelta(seconds=10),
            )
        )
        db.add(
            Node(
                node_id="d",
                hostname="dead",
                last_heartbeat=_FIXED_NOW - timedelta(seconds=300),
            )
        )
        db.commit()

    with clean_db() as db:
        active = compute_active_machines(db, now=_FIXED_NOW)

    assert active == {"alive"}


def _seed_targets():
    return [
        {
            "targets": ["192.168.0.55:9101"],
            "labels": {"component": "worker_agent", "machine": "alive"},
        },
        {
            "targets": ["192.168.0.99:9101"],
            "labels": {"component": "worker_agent", "machine": "dead"},
        },
        {
            "targets": ["host.docker.internal:9101"],
            "labels": {"component": "worker_agent", "machine": "laptop"},
        },
    ]


@pytest.mark.parametrize(
    "active_machines, expected_kept, expected_removed",
    [
        pytest.param(
            {"alive", "dead", "laptop"},
            ["alive", "dead", "laptop"],
            0,
            id="all-active-none-removed",
        ),
        pytest.param(
            {"alive", "laptop"}, ["alive", "laptop"], 1, id="one-stale-pruned"
        ),
        pytest.param({"alive"}, ["alive"], 2, id="multiple-stale-pruned"),
        pytest.param(set(), [], 3, id="all-stale-file-emptied"),
        pytest.param(
            {"alive", "ghost"}, ["alive"], 2, id="active-machine-not-in-file-ignored"
        ),
    ],
)
def test_reconcile_prometheus_targets(
    targets_file, active_machines, expected_kept, expected_removed
):
    """Targets whose machine label isn't in the active set are pruned from the file."""
    targets_file.write_text(json.dumps(_seed_targets()))

    removed = reconcile_prometheus_targets(active_machines)

    assert removed == expected_removed
    data = json.loads(targets_file.read_text())
    assert sorted(w["labels"]["machine"] for w in data) == sorted(expected_kept)


def test_reconcile_prometheus_targets_missing_file_returns_zero(targets_file):
    """Reconciling when no targets file exists is a no-op."""
    assert not targets_file.exists()
    assert reconcile_prometheus_targets({"anything"}) == 0


def test_reconcile_prometheus_targets_handles_missing_labels(targets_file):
    """An entry without a machine label is treated as inactive and pruned."""
    targets_file.write_text(
        json.dumps([{"targets": ["10.0.0.1:9101"]}])  # no "labels" key
    )

    removed = reconcile_prometheus_targets({"alive"})

    assert removed == 1
    assert json.loads(targets_file.read_text()) == []


def test_reconcile_prometheus_targets_handles_corrupt_json(targets_file):
    """A corrupt targets file is a no-op rather than crashing the reconcile loop."""
    targets_file.write_text("{ this is not valid json ]")

    assert reconcile_prometheus_targets({"alive"}) == 0
    # The unreadable file is left untouched for inspection.
    assert targets_file.read_text() == "{ this is not valid json ]"


@pytest.mark.asyncio
async def test_register_node_is_immediately_active(
    clean_db, mock_scheduler, targets_file
):
    """A freshly-registered node is active at once, so reconcile won't prune it."""
    service = OrchestratorService(clean_db, mock_scheduler)
    req = orchestrator_pb2.RegisterNodeRequest(node_id="new-node", hostname="new-host")

    await service.RegisterNode(req, MagicMock())

    with clean_db() as db:
        # Default now=utcnow(); registration just set last_heartbeat, so active.
        active = compute_active_machines(db)
    assert "new-host" in active


@pytest.mark.asyncio
async def test_register_then_reconcile_prunes_only_stale_worker(
    clean_db, mock_scheduler, targets_file
):
    """End-to-end: the target a worker registers is pruned once that node goes stale.

    Exercises the real composition the control plane loop uses
    (RegisterNode -> compute_active_machines -> reconcile_prometheus_targets)
    and proves the registered ``machine`` label matches what staleness returns.
    """
    service = OrchestratorService(clean_db, mock_scheduler)

    for node_id, host, ip in [
        ("a", "alive-host", "192.168.0.10"),
        ("d", "dead-host", "192.168.0.11"),
    ]:
        req = orchestrator_pb2.RegisterNodeRequest(
            node_id=node_id, hostname=host, metrics_ip=ip, metrics_port=9101
        )
        await service.RegisterNode(req, MagicMock())

    # Both workers wrote their scrape targets on registration.
    machines = {w["labels"]["machine"] for w in json.loads(targets_file.read_text())}
    assert machines == {"alive-host", "dead-host"}

    # Age out one node well past the stale window.
    with clean_db() as db:
        dead = db.query(Node).filter(Node.node_id == "d").first()
        dead.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_NODE_SECONDS * 10
        )
        db.commit()

    # Run the exact pipeline the reconcile loop runs.
    with clean_db() as db:
        removed = reconcile_prometheus_targets(compute_active_machines(db))

    assert removed == 1
    machines = {w["labels"]["machine"] for w in json.loads(targets_file.read_text())}
    assert machines == {"alive-host"}
