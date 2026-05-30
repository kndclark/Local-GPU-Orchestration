import uuid
import socket
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class WorkerSettings(BaseSettings):
    """Configuration for the Worker Agent daemon."""

    orchestrator_url: str = "localhost:50051"
    node_id: str = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    heartbeat_interval_seconds: float = 5.0
    job_poll_interval_seconds: float = 2.0
    supported_workloads: list[str] = ["python", "ffmpeg"]

    @field_validator("orchestrator_url")
    @classmethod
    def ensure_port(cls, v: str) -> str:
        if ":" not in v:
            return f"{v}:50051"
        return v

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8-sig", extra="ignore"
    )
