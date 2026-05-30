import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from worker_agent.main import AgentDaemon
from worker_agent.config import WorkerSettings


@pytest.fixture
def mock_settings():
    return WorkerSettings(
        orchestrator_url="localhost:50051",
        node_id="test-daemon-node",
        heartbeat_interval_seconds=0.1,
        job_poll_interval_seconds=0.1,
        supported_workloads=["test-workload"],
    )


@pytest.mark.asyncio
async def test_agent_daemon_lifecycle(mock_settings):
    # Mock all external dependencies
    with (
        patch("worker_agent.main.WorkerClient") as mock_client_cls,
        patch("worker_agent.main.HardwareManager") as mock_hw_cls,
        patch("worker_agent.main.JobExecutor") as mock_exec_cls,
    ):

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.connect = MagicMock()
        mock_client.register_node.return_value = True
        mock_client.send_heartbeat.return_value = True

        # Simulate one job being returned, then none
        mock_client.request_job.side_effect = [
            {
                "job_id": "job-1",
                "workload_type": "test-workload",
                "args": [],
                "env_vars": {},
            },
            None,
            None,
        ]
        mock_client.update_job_status.return_value = True
        mock_client_cls.return_value = mock_client

        # Setup mock HW manager
        mock_hw = MagicMock()
        mock_hw.get_gpu_devices.return_value = []
        mock_hw.get_system_telemetry.return_value = MagicMock()
        mock_hw_cls.return_value = mock_hw

        # Setup mock executor
        mock_executor = AsyncMock()
        mock_executor.execute_job.return_value = (True, "")
        mock_exec_cls.return_value = mock_executor

        daemon = AgentDaemon(settings=mock_settings)

        # Run the daemon as a background task for a short time
        daemon_task = asyncio.create_task(daemon.start())

        # Let it run long enough to register, send a heartbeat, and process the mock job
        await asyncio.sleep(0.3)

        # Signal shutdown
        await daemon.stop()
        await daemon_task

        # Verify interactions
        mock_hw.detect.assert_called_once()
        mock_client.connect.assert_called_once()
        mock_client.register_node.assert_called_once()

        # Heartbeat loop should have run at least once
        assert mock_client.send_heartbeat.call_count >= 1

        # Job executor should have processed job-1
        mock_executor.execute_job.assert_called_once()

        # Job status should have been updated to COMPLETED
        mock_client.update_job_status.assert_called_with(
            job_id="job-1", status="COMPLETED", error_message=""
        )

        # Verify shutdown cleanup
        mock_client.close.assert_called_once()
        mock_hw.shutdown.assert_called_once()
