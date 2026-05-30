import uuid
import socket
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Configuration for the Worker Agent daemon."""

    orchestrator_url: str = "localhost:50051"
    node_id: str = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    heartbeat_interval_seconds: float = 5.0
    job_poll_interval_seconds: float = 2.0
    supported_workloads: list[str] = ["python", "ffmpeg"]

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
