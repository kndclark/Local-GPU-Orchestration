from worker_agent.config import WorkerSettings


def test_default_settings(clean_worker_env):
    settings = WorkerSettings(_env_file=str(clean_worker_env))
    assert settings.orchestrator_url == "auto"
    assert settings.node_id is not None
    assert settings.heartbeat_interval_seconds == 5.0
    assert settings.job_poll_interval_seconds == 2.0
    assert settings.supported_workloads == ["python", "ffmpeg"]


def test_override_settings_via_env(monkeypatch, clean_worker_env):
    monkeypatch.setenv("ORCHESTRATOR_URL", "10.0.0.5:50051")
    monkeypatch.setenv("NODE_ID", "custom-node-1")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_SECONDS", "10.0")

    settings = WorkerSettings(_env_file=str(clean_worker_env))
    assert settings.orchestrator_url == "10.0.0.5:50051"
    assert settings.node_id == "custom-node-1"
    assert settings.heartbeat_interval_seconds == 10.0
