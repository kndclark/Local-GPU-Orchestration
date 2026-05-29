import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from control_plane.database.models import Base, Node, Job


# Pytest fixture to setup an in-memory SQLite database
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_node(db_session):
    node = Node(
        node_id="test-node-1",
        hostname="desktop-rtx",
        total_vram_mb=24000,
        gpu_count=1,
        supported_workloads="cuda,ffmpeg",
    )
    db_session.add(node)
    db_session.commit()

    retrieved = db_session.query(Node).filter_by(node_id="test-node-1").first()
    assert retrieved is not None
    assert retrieved.hostname == "desktop-rtx"
    assert retrieved.total_vram_mb == 24000
    assert retrieved.gpu_count == 1
    assert retrieved.supported_workloads == "cuda,ffmpeg"


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
