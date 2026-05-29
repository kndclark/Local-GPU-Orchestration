import pytest
import grpc
from unittest.mock import AsyncMock, MagicMock
from worker_agent.client import WorkerClient


@pytest.mark.asyncio
async def test_register_node_success():
    client = WorkerClient(node_id="node-1")
    client.connect()

    mock_resp = MagicMock()
    mock_resp.success = True

    mock_stub = AsyncMock()
    mock_stub.RegisterNode.return_value = mock_resp
    client.stub = mock_stub

    success = await client.register_node(
        hostname="test-host",
        total_vram_mb=8000,
        gpu_count=1,
        supported_workloads=["ffmpeg"],
    )

    assert success is True
    mock_stub.RegisterNode.assert_called_once()


@pytest.mark.asyncio
async def test_register_node_network_failure():
    client = WorkerClient(node_id="node-1")
    client.connect()

    mock_stub = AsyncMock()
    mock_error = grpc.aio.AioRpcError(
        code=grpc.StatusCode.UNAVAILABLE,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="Connection refused",
        debug_error_string="debug",
    )
    mock_stub.RegisterNode.side_effect = mock_error
    client.stub = mock_stub

    success = await client.register_node(
        hostname="test-host",
        total_vram_mb=8000,
        gpu_count=1,
        supported_workloads=["ffmpeg"],
    )

    assert success is False


@pytest.mark.asyncio
async def test_send_heartbeat_success():
    client = WorkerClient(node_id="node-1")
    client.connect()

    mock_resp = MagicMock()
    mock_resp.acknowledged = True

    mock_stub = AsyncMock()
    mock_stub.SendHeartbeat.return_value = mock_resp
    client.stub = mock_stub

    success = await client.send_heartbeat(
        free_vram_mb=4000, temp_c=65.0, util_percent=80.0, active_jobs=["job-1"]
    )

    assert success is True
    mock_stub.SendHeartbeat.assert_called_once()
