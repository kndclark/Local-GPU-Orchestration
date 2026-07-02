from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from control_plane.database.models import Base, Gpu, Node
from control_plane.gang_scheduler import GangScheduler


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _add_node(
    db,
    node_id,
    *,
    vendor="NVIDIA",
    free_vram_mb=10000,
    temp=50.0,
    heartbeat_age_sec=0,
    gpu_count=1,
):
    """Create a node with one-or-more GPUs and controllable telemetry."""
    hb = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_sec)
    node = Node(node_id=node_id, hostname=node_id, last_heartbeat=hb)
    db.add(node)
    for i in range(gpu_count):
        db.add(
            Gpu(
                node_id=node_id,
                gpu_index=i,
                vendor=vendor,
                free_vram_mb=free_vram_mb,
                temperature_c=temp,
                temperature_hotspot_c=temp,
            )
        )
    db.commit()
    return node


class TestFindGang:
    def test_two_nodes_form_gang(self, db_session):
        _add_node(db_session, "big", free_vram_mb=20000)
        _add_node(db_session, "small", free_vram_mb=15000)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)

        assert result.outcome == "OK"
        # Highest-VRAM node is controller by default
        assert result.controller_node.node_id == "big"
        assert {n.node_id for n in result.worker_nodes} == {"small"}

    def test_greedy_minimal_selection(self, db_session):
        # Controller(20k) + one worker(15k) = 35k >= 30k; third node unused.
        _add_node(db_session, "a", free_vram_mb=20000)
        _add_node(db_session, "b", free_vram_mb=15000)
        _add_node(db_session, "c", free_vram_mb=10000)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)

        assert result.outcome == "OK"
        assert result.controller_node.node_id == "a"
        assert {n.node_id for n in result.worker_nodes} == {"b"}

    def test_controller_alone_sufficient_still_adds_worker(self, db_session):
        # Controller alone meets min, but a gang needs >= 2 nodes.
        _add_node(db_session, "a", free_vram_mb=40000)
        _add_node(db_session, "b", free_vram_mb=10000)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)

        assert result.outcome == "OK"
        assert result.controller_node.node_id == "a"
        assert {n.node_id for n in result.worker_nodes} == {"b"}

    def test_no_nodes(self, db_session):
        sched = GangScheduler()
        result = sched.find_gang(min_vram_mb=1000, requires_cuda=False, db=db_session)
        assert result.outcome == "NO_NODES"
        assert result.controller_node is None

    def test_single_node_sufficient(self, db_session):
        _add_node(db_session, "solo", free_vram_mb=24000)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=20000, requires_cuda=False, db=db_session)

        assert result.outcome == "SINGLE_NODE_SUFFICIENT"
        assert "solo" in result.detail

    def test_single_node_insufficient(self, db_session):
        _add_node(db_session, "solo", free_vram_mb=8000)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=20000, requires_cuda=False, db=db_session)

        assert result.outcome == "INSUFFICIENT_VRAM"

    def test_multi_node_insufficient(self, db_session):
        _add_node(db_session, "a", free_vram_mb=5000)
        _add_node(db_session, "b", free_vram_mb=6000)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=40000, requires_cuda=False, db=db_session)

        assert result.outcome == "INSUFFICIENT_VRAM"

    def test_requires_cuda_excludes_amd(self, db_session):
        _add_node(db_session, "nv", vendor="NVIDIA", free_vram_mb=20000)
        _add_node(db_session, "amd", vendor="AMD", free_vram_mb=20000)
        sched = GangScheduler()

        # Only the NVIDIA node is eligible -> single node, and 20k < 30k min
        result = sched.find_gang(min_vram_mb=30000, requires_cuda=True, db=db_session)
        assert result.outcome == "INSUFFICIENT_VRAM"

        # Without cuda requirement, both count -> gang forms
        result2 = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)
        assert result2.outcome == "OK"

    def test_thermal_throttled_node_excluded(self, db_session, monkeypatch):
        monkeypatch.setenv("MAX_GPU_TEMP_C", "80.0")
        _add_node(db_session, "cool", free_vram_mb=20000, temp=50.0)
        _add_node(db_session, "hot", free_vram_mb=20000, temp=90.0)
        sched = GangScheduler()

        # Hot node excluded -> only cool remains -> single node, 20k < 30k
        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)
        assert result.outcome == "INSUFFICIENT_VRAM"

    def test_stale_node_excluded(self, db_session):
        _add_node(db_session, "fresh", free_vram_mb=20000, heartbeat_age_sec=5)
        _add_node(db_session, "stale", free_vram_mb=20000, heartbeat_age_sec=120)
        sched = GangScheduler()

        # Stale node excluded -> only fresh remains -> single node, 20k < 30k
        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)
        assert result.outcome == "INSUFFICIENT_VRAM"

    def test_zero_vram_node_excluded(self, db_session):
        # Sentinel free_vram (-1, sensor unavailable) must not count.
        _add_node(db_session, "good", free_vram_mb=20000)
        _add_node(db_session, "sensorless", free_vram_mb=-1)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)
        assert result.outcome == "INSUFFICIENT_VRAM"  # only "good" (20k) counts

    def test_explicit_controller_node_id(self, db_session):
        _add_node(db_session, "big", free_vram_mb=20000)
        _add_node(db_session, "small", free_vram_mb=15000)
        sched = GangScheduler()

        # Force the smaller node to be controller
        result = sched.find_gang(
            min_vram_mb=30000,
            requires_cuda=False,
            db=db_session,
            controller_node_id="small",
        )

        assert result.outcome == "OK"
        assert result.controller_node.node_id == "small"
        assert {n.node_id for n in result.worker_nodes} == {"big"}

    def test_explicit_controller_not_eligible(self, db_session):
        _add_node(db_session, "a", free_vram_mb=20000)
        _add_node(db_session, "b", free_vram_mb=20000)
        sched = GangScheduler()

        result = sched.find_gang(
            min_vram_mb=30000,
            requires_cuda=False,
            db=db_session,
            controller_node_id="nonexistent",
        )

        assert result.outcome == "CONTROLLER_NOT_ELIGIBLE"

    def test_multi_gpu_node_vram_summed(self, db_session):
        # One node with 2x 12k GPUs = 24k; another with 12k. Combined 36k >= 30k.
        _add_node(db_session, "dual", free_vram_mb=12000, gpu_count=2)
        _add_node(db_session, "single", free_vram_mb=12000, gpu_count=1)
        sched = GangScheduler()

        result = sched.find_gang(min_vram_mb=30000, requires_cuda=False, db=db_session)

        assert result.outcome == "OK"
        assert result.controller_node.node_id == "dual"  # 24k > 12k
        assert {n.node_id for n in result.worker_nodes} == {"single"}
