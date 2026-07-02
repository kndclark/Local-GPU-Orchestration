import sys
import pytest
from unittest.mock import AsyncMock, patch
from worker_agent.executor import JobExecutor


def _py(code):
    return sys.executable, ["-c", code]


@pytest.mark.asyncio
async def test_execute_job_success(stub_ffmpeg):
    executor = JobExecutor()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"success output", b"")
        mock_exec.return_value = mock_process

        success, err = await executor.execute_job(
            job_id="job-1",
            executable="ffmpeg",
            args=["-i", "in.mp4", "out.mp4"],
            env_vars={"CUDA_VISIBLE_DEVICES": "0"},
        )

        assert success is True
        assert err == ""
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        assert args[0] == "ffmpeg"
        assert args[1] == "-i"
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "0"


@pytest.mark.asyncio
async def test_execute_job_failure(stub_ffmpeg):
    executor = JobExecutor()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b"", b"Something went wrong")
        mock_exec.return_value = mock_process

        success, err = await executor.execute_job(
            job_id="job-2", executable="ffmpeg", args=["-invalid"], env_vars={}
        )

        assert success is False
        assert err == "Something went wrong"


@pytest.mark.asyncio
async def test_execute_job_exception(stub_ffmpeg):
    executor = JobExecutor()

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("ffmpeg not found"),
    ):
        success, err = await executor.execute_job(
            job_id="job-3", executable="ffmpeg", args=[], env_vars={}
        )

        assert success is False
        assert "ffmpeg not found" in err


@pytest.mark.asyncio
async def test_execute_job_missing_executable():
    executor = JobExecutor()

    success, err = await executor.execute_job(
        job_id="job-4",
        executable="not-a-real-executable-xyzzy",
        args=[],
        env_vars={},
    )

    assert success is False
    assert "not found on PATH" in err


# ──────────────────────────────────────────────
# Server (gang worker) execution tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_server_job_fires_ready_then_completes():
    executor = JobExecutor()
    exe, args = _py(
        "import sys; print('main: RPC server listening on 127.0.0.1:50052', "
        "flush=True); sys.exit(0)"
    )
    on_ready = AsyncMock()

    success, err = await executor.execute_server_job(
        job_id="rpc-1",
        executable=exe,
        args=args,
        env_vars={},
        ready_signal="listening",
        on_ready=on_ready,
    )

    assert success is True
    assert err == ""
    on_ready.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_server_job_failure_without_ready():
    executor = JobExecutor()
    exe, args = _py(
        "import sys; print('error: failed to bind port', flush=True); sys.exit(1)"
    )
    on_ready = AsyncMock()

    success, err = await executor.execute_server_job(
        job_id="rpc-2",
        executable=exe,
        args=args,
        env_vars={},
        ready_signal="listening",
        on_ready=on_ready,
    )

    assert success is False
    assert "failed to bind" in err
    on_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_server_job_missing_executable():
    executor = JobExecutor()
    on_ready = AsyncMock()

    success, err = await executor.execute_server_job(
        job_id="rpc-3",
        executable="not-a-real-executable-xyzzy",
        args=[],
        env_vars={},
        ready_signal="listening",
        on_ready=on_ready,
    )

    assert success is False
    assert "not found on PATH" in err
    on_ready.assert_not_awaited()
