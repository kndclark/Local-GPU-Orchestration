import pytest

from control_plane.scheduler import HardwareAwareScheduler
from control_plane.database.models import Node, Gpu, Job
from control_plane.main import SessionLocal


@pytest.fixture
def db():
    session = SessionLocal()
    # Clean db
    session.query(Job).delete()
    session.query(Gpu).delete()
    session.query(Node).delete()
    session.commit()
    yield session
    session.close()


@pytest.mark.asyncio
async def test_scheduler_capability_matching(db):
    scheduler = HardwareAwareScheduler()

    # Create an AMD Node
    amd_node = Node(node_id="amd-node", hostname="amd-host")
    amd_gpu = Gpu(
        node_id="amd-node",
        gpu_index=0,
        vendor="AMD",
        temperature_c=50.0,
        temperature_hotspot_c=55.0,
    )
    db.add(amd_node)
    db.add(amd_gpu)

    # Create an NVIDIA Node
    nv_node = Node(node_id="nv-node", hostname="nv-host")
    nv_gpu = Gpu(
        node_id="nv-node",
        gpu_index=0,
        vendor="NVIDIA",
        temperature_c=50.0,
        temperature_hotspot_c=55.0,
    )
    db.add(nv_node)
    db.add(nv_gpu)

    # Create jobs
    cuda_job = Job(
        job_id="cuda-job", workload_type="test", requires_cuda=True, status="PENDING"
    )
    normal_job = Job(
        job_id="normal-job", workload_type="test", requires_cuda=False, status="PENDING"
    )
    db.add(cuda_job)
    db.add(normal_job)
    db.commit()

    await scheduler.submit_job("cuda-job")
    await scheduler.submit_job("normal-job")

    # AMD node should skip the cuda job and get the normal job
    job_id = await scheduler.get_next_job_for_node("amd-node", db)
    assert job_id == "normal-job"

    # NV node should get the cuda job
    job_id = await scheduler.get_next_job_for_node("nv-node", db)
    assert job_id == "cuda-job"


@pytest.mark.asyncio
async def test_scheduler_thermal_throttling(db, monkeypatch):
    monkeypatch.setenv("MAX_GPU_TEMP_C", "80.0")
    scheduler = HardwareAwareScheduler()

    hot_node = Node(node_id="hot-node", hostname="hot-host")
    hot_gpu = Gpu(
        node_id="hot-node",
        gpu_index=0,
        vendor="AMD",
        temperature_c=85.0,
        temperature_hotspot_c=90.0,
    )
    db.add(hot_node)
    db.add(hot_gpu)

    normal_job = Job(
        job_id="job1", workload_type="test", requires_cuda=False, status="PENDING"
    )
    db.add(normal_job)
    db.commit()

    await scheduler.submit_job("job1")

    job_id = await scheduler.get_next_job_for_node("hot-node", db)
    assert job_id is None  # Throttled!


@pytest.mark.asyncio
async def test_scheduler_initialize_from_db(db):
    scheduler = HardwareAwareScheduler()

    pending_job = Job(
        job_id="pending-1", workload_type="test", requires_cuda=False, status="PENDING"
    )
    running_job = Job(
        job_id="running-1", workload_type="test", requires_cuda=False, status="RUNNING"
    )
    db.add(pending_job)
    db.add(running_job)
    db.commit()

    # Initialization is lazy, triggered on first get_next_job_for_node
    # We can mock a node
    node = Node(node_id="test-node", hostname="test-host")
    gpu = Gpu(
        node_id="test-node",
        gpu_index=0,
        vendor="AMD",
        temperature_c=50.0,
        temperature_hotspot_c=50.0,
    )
    db.add(node)
    db.add(gpu)
    db.commit()

    job_id = await scheduler.get_next_job_for_node("test-node", db)
    assert job_id == "pending-1"


@pytest.mark.asyncio
async def test_scheduler_respects_node_pinning(db):
    """A job pre-pinned via assigned_node_id must only dispatch to that node."""
    scheduler = HardwareAwareScheduler()

    for node_id in ("node-a", "node-b"):
        db.add(Node(node_id=node_id, hostname=node_id))
        db.add(
            Gpu(
                node_id=node_id,
                gpu_index=0,
                vendor="NVIDIA",
                temperature_c=50.0,
                temperature_hotspot_c=50.0,
            )
        )

    # Pinned to node-b specifically (as gang worker jobs are).
    pinned = Job(
        job_id="pinned-b",
        workload_type="llama_rpc_server",
        requires_cuda=False,
        status="PENDING",
        assigned_node_id="node-b",
    )
    db.add(pinned)
    db.commit()

    await scheduler.submit_job("pinned-b")

    # node-a asks first but must NOT receive the job pinned to node-b.
    assert await scheduler.get_next_job_for_node("node-a", db) is None
    # node-b receives its pinned job.
    assert await scheduler.get_next_job_for_node("node-b", db) == "pinned-b"
