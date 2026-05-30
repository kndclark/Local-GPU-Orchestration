import os
from worker_agent.config import WorkerSettings


def test_default_settings():
    # Ensure no env vars interfere
    os.environ.pop("ORCHESTRATOR_URL", None)
    os.environ.pop("NODE_ID", None)

    settings = WorkerSettings()
    assert settings.orchestrator_url == "localhost:50051"
    assert settings.node_id is not None  # Auto-generated
    assert settings.heartbeat_interval_seconds == 5.0
    assert settings.job_poll_interval_seconds == 2.0
    assert settings.supported_workloads == ["python", "ffmpeg"]


def test_override_settings_via_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_URL", "10.0.0.5:50051")
    monkeypatch.setenv("NODE_ID", "custom-node-1")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "10.0")

    settings = WorkerSettings()
    assert settings.orchestrator_url == "10.0.0.5:50051"
    assert settings.node_id == "custom-node-1"
    assert settings.heartbeat_interval_seconds == 10.0
