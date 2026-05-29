import pytest
from unittest.mock import AsyncMock, patch
from worker_agent.executor import JobExecutor
import asyncio

@pytest.mark.asyncio
async def test_execute_job_success():
    executor = JobExecutor()
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b'success output', b'')
        mock_exec.return_value = mock_process
        
        success, err = await executor.execute_job(
            job_id="job-1",
            executable="ffmpeg",
            args=["-i", "in.mp4", "out.mp4"],
            env_vars={"CUDA_VISIBLE_DEVICES": "0"}
        )
        
        assert success is True
        assert err == ""
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        assert args[0] == "ffmpeg"
        assert args[1] == "-i"
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "0"

@pytest.mark.asyncio
async def test_execute_job_failure():
    executor = JobExecutor()
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b'', b'Something went wrong')
        mock_exec.return_value = mock_process
        
        success, err = await executor.execute_job(
            job_id="job-2",
            executable="ffmpeg",
            args=["-invalid"],
            env_vars={}
        )
        
        assert success is False
        assert err == "Something went wrong"

@pytest.mark.asyncio
async def test_execute_job_exception():
    executor = JobExecutor()
    
    with patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError("ffmpeg not found")):
        success, err = await executor.execute_job(
            job_id="job-3",
            executable="ffmpeg",
            args=[],
            env_vars={}
        )
        
        assert success is False
        assert "ffmpeg not found" in err
