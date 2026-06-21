import os
import stat
import sys

import pytest


@pytest.fixture()
def stub_ffmpeg(tmp_path, monkeypatch):
    """
    Creates a no-op ffmpeg stub in a temp directory and prepends it to PATH
    so executor PATH checks pass without requiring system-level ffmpeg.

    On Windows: ffmpeg.bat (found by shutil.which via PATHEXT).
    On Linux/macOS: executable shell script named ffmpeg.

    tmp_path and monkeypatch both clean up automatically after the test.
    """
    if sys.platform == "win32":
        stub = tmp_path / "ffmpeg.bat"
        stub.write_text("@echo off\n")
    else:
        stub = tmp_path / "ffmpeg"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    return stub


@pytest.fixture()
def clean_worker_env(monkeypatch, tmp_path):
    """
    Clears all worker-agent env vars and points pydantic-settings at an
    empty temp .env so the real on-disk .env never bleeds into unit tests.

    monkeypatch restores the original env state after each test automatically.
    Returns the path to the empty temp .env for passing to WorkerSettings.
    """
    for var in (
        "ORCHESTRATOR_URL",
        "NODE_ID",
        "HEARTBEAT_INTERVAL_SECONDS",
        "JOB_POLL_INTERVAL_SECONDS",
        "METRICS_PORT",
        "METRICS_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("")
    return env_file
