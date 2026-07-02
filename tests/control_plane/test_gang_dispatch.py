import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock

from control_plane.database.models import (
    Base,
    Job,
    Node,
    GangJob,
    GangJobParticipant,
)
from control_plane.gang_scheduler import run_gang_dispatch_cycle


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _build_forming_gang(db, worker_endpoints, controller_args=None):
    """Create a FORMING gang with worker jobs; endpoints=None means not-ready."""
    db.add(Node(node_id="ctrl", hostname="ctrl"))
    gang = GangJob(
        gang_job_id="g-1",
        worker_workload_type="llama_rpc_server",
        controller_workload_type="llama_cli",
        controller_args=json.dumps(controller_args or ["--model", "/m.gguf"]),
        min_vram_mb=1000,
        status="FORMING",
    )
    db.add(gang)
    db.add(
        GangJobParticipant(
            gang_job_id="g-1", node_id="ctrl", role="controller", job_id=None
        )
    )
    for i, endpoint in enumerate(worker_endpoints):
        node_id = f"w{i}"
        job_id = f"wjob-{i}"
        db.add(Node(node_id=node_id, hostname=node_id))
        db.add(
            Job(
                job_id=job_id,
                workload_type="llama_rpc_server",
                status="RUNNING",
                assigned_node_id=node_id,
            )
        )
        db.add(
            GangJobParticipant(
                gang_job_id="g-1",
                node_id=node_id,
                role="worker",
                job_id=job_id,
                endpoint=endpoint,
            )
        )
    db.commit()
    return gang


@pytest.mark.asyncio
async def test_forming_gang_waits_when_workers_not_ready(db_session):
    _build_forming_gang(db_session, [None, "10.0.0.2:50052"])
    scheduler = AsyncMock()

    await run_gang_dispatch_cycle(db_session, scheduler)

    gang = db_session.query(GangJob).filter_by(gang_job_id="g-1").first()
    assert gang.status == "FORMING"
    scheduler.submit_job.assert_not_awaited()
    assert db_session.query(Job).filter_by(workload_type="llama_cli").count() == 0


@pytest.mark.asyncio
async def test_forming_gang_dispatches_controller_when_all_ready(db_session):
    _build_forming_gang(db_session, ["10.0.0.1:50052", "10.0.0.2:50052"])
    scheduler = AsyncMock()

    await run_gang_dispatch_cycle(db_session, scheduler)

    gang = db_session.query(GangJob).filter_by(gang_job_id="g-1").first()
    assert gang.status == "RUNNING"

    controller_job = db_session.query(Job).filter_by(workload_type="llama_cli").first()
    assert controller_job is not None
    assert controller_job.status == "PENDING"
    assert controller_job.assigned_node_id == "ctrl"

    args = json.loads(controller_job.args)
    assert "--rpc" in args
    rpc_value = args[args.index("--rpc") + 1]
    assert rpc_value == "10.0.0.1:50052,10.0.0.2:50052"
    assert "--model" in args

    controller_p = (
        db_session.query(GangJobParticipant)
        .filter_by(gang_job_id="g-1", role="controller")
        .first()
    )
    assert controller_p.job_id == controller_job.job_id
    scheduler.submit_job.assert_awaited_once_with(controller_job.job_id)


@pytest.mark.asyncio
async def test_controller_endpoints_flag_is_data_driven(db_session):
    gang = _build_forming_gang(db_session, ["10.0.0.1:50052"])
    gang.controller_endpoints_flag = "--peers"
    db_session.commit()
    scheduler = AsyncMock()

    await run_gang_dispatch_cycle(db_session, scheduler)

    controller_job = db_session.query(Job).filter_by(workload_type="llama_cli").first()
    args = json.loads(controller_job.args)
    assert "--rpc" not in args
    assert args[args.index("--peers") + 1] == "10.0.0.1:50052"


@pytest.mark.asyncio
async def test_forming_gang_fails_when_worker_failed(db_session):
    _build_forming_gang(db_session, ["10.0.0.1:50052", None])
    # Mark the not-ready worker's job FAILED.
    db_session.query(Job).filter_by(job_id="wjob-1").update({"status": "FAILED"})
    db_session.commit()
    scheduler = AsyncMock()

    await run_gang_dispatch_cycle(db_session, scheduler)

    gang = db_session.query(GangJob).filter_by(gang_job_id="g-1").first()
    assert gang.status == "FAILED"
    scheduler.submit_job.assert_not_awaited()
    assert db_session.query(Job).filter_by(workload_type="llama_cli").count() == 0


def _build_running_gang(db, controller_status):
    db.add(Node(node_id="ctrl", hostname="ctrl"))
    db.add(
        GangJob(
            gang_job_id="g-run",
            worker_workload_type="llama_rpc_server",
            controller_workload_type="llama_cli",
            min_vram_mb=1000,
            status="RUNNING",
        )
    )
    db.add(
        Job(
            job_id="cjob",
            workload_type="llama_cli",
            status=controller_status,
            assigned_node_id="ctrl",
        )
    )
    db.add(
        GangJobParticipant(
            gang_job_id="g-run", node_id="ctrl", role="controller", job_id="cjob"
        )
    )
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "controller_status, expected_gang_status",
    [
        ("COMPLETED", "COMPLETED"),
        ("FAILED", "FAILED"),
        ("RUNNING", "RUNNING"),
    ],
)
async def test_running_gang_follows_controller(
    db_session, controller_status, expected_gang_status
):
    _build_running_gang(db_session, controller_status)
    scheduler = AsyncMock()

    await run_gang_dispatch_cycle(db_session, scheduler)

    gang = db_session.query(GangJob).filter_by(gang_job_id="g-run").first()
    assert gang.status == expected_gang_status
