import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from control_plane.database.models import Base
import control_plane.main
import control_plane.grpc_server

# Setup in-memory DB
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Patch main module BEFORE tests import it
control_plane.main.engine = engine
control_plane.main.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _isolate_targets_json(tmp_path, monkeypatch):
    """Prevent every test from writing to the live monitoring/targets.json."""
    monkeypatch.setattr(
        control_plane.grpc_server,
        "Path",
        lambda _p: tmp_path / "targets.json",
    )


@pytest.fixture(autouse=True)
def override_get_db():
    def _get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    control_plane.main.app.dependency_overrides[control_plane.main.get_db] = _get_db
    yield
    control_plane.main.app.dependency_overrides.clear()
