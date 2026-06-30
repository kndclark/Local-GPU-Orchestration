import pytest
import asyncio
import contextlib
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


@contextlib.asynccontextmanager
async def _running_daemon(settings, advertise_return=("", False)):
    """Start an AgentDaemon with all external deps mocked, run it briefly, stop it.

    Yields (mock_client, mock_resolve, mock_start_http) for assertions on how the
    daemon wired the self-advertised metrics address into registration.
    """
    with (
        patch("worker_agent.main.WorkerClient") as mock_client_cls,
        patch("worker_agent.main.HardwareManager") as mock_hw_cls,
        patch("worker_agent.main.JobExecutor"),
        patch("worker_agent.main.WorkerMetrics"),
        patch("worker_agent.main.start_http_server") as mock_start_http,
        patch(
            "worker_agent.discovery.resolve_advertise_address",
            return_value=advertise_return,
        ) as mock_resolve,
    ):
        mock_client = AsyncMock()
        mock_client.connect = MagicMock()
        # The real WorkerClient stores the orchestrator URL; mirror that so the
        # daemon reads back a real address rather than an auto-generated mock.
        mock_client.server_address = settings.orchestrator_url
        mock_client.register_node.return_value = True
        mock_client.send_heartbeat.return_value = True
        mock_client.request_job.return_value = None
        mock_client_cls.return_value = mock_client

        mock_hw = MagicMock()
        mock_hw.get_gpu_devices.return_value = []
        mock_hw.get_system_telemetry.return_value = MagicMock()
        mock_hw_cls.return_value = mock_hw

        daemon = AgentDaemon(settings=settings)
        task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.2)  # let it register + start loops
        try:
            yield mock_client, mock_resolve, mock_start_http
        finally:
            await daemon.stop()
            await task


@pytest.mark.parametrize(
    "metrics_enabled, advertise_return, orch_url, "
    "expected_ip, expected_port, expected_colocated, resolve_called, http_called",
    [
        # Remote worker: advertises its LAN IP, runs the metrics server.
        (
            True,
            ("192.168.0.55", False),
            "192.168.0.190:50051",
            "192.168.0.55",
            9101,
            False,
            True,
            True,
        ),
        # Colocated worker: advertises colocated=True (control plane maps it).
        (
            True,
            ("", True),
            "localhost:50051",
            "",
            9101,
            True,
            True,
            True,
        ),
        # Metrics disabled: nothing advertised, resolution + server skipped.
        (
            False,
            ("", False),
            "192.168.0.190:50051",
            "",
            0,
            False,
            False,
            False,
        ),
    ],
)
@pytest.mark.asyncio
async def test_agent_daemon_metrics_wiring(
    metrics_enabled,
    advertise_return,
    orch_url,
    expected_ip,
    expected_port,
    expected_colocated,
    resolve_called,
    http_called,
):
    """The daemon resolves its scrape address (when metrics are on) and forwards it to register_node."""
    settings = WorkerSettings(
        orchestrator_url=orch_url,
        node_id="wiring-node",
        heartbeat_interval_seconds=0.1,
        job_poll_interval_seconds=0.1,
        metrics_port=9101,
        metrics_enabled=metrics_enabled,
    )

    async with _running_daemon(settings, advertise_return=advertise_return) as (
        mock_client,
        mock_resolve,
        mock_start_http,
    ):
        pass

    if resolve_called:
        mock_resolve.assert_called_once_with(orch_url)
    else:
        mock_resolve.assert_not_called()

    if http_called:
        mock_start_http.assert_called_once()
    else:
        mock_start_http.assert_not_called()

    mock_client.register_node.assert_called_once()
    kwargs = mock_client.register_node.call_args.kwargs
    assert kwargs["metrics_ip"] == expected_ip
    assert kwargs["metrics_port"] == expected_port
    assert kwargs["colocated"] is expected_colocated


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
