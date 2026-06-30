import pytest
import grpc
from unittest.mock import AsyncMock, MagicMock
from worker_agent.client import WorkerClient
from worker_agent.hal.base import GpuDevice, GpuTelemetry, SystemTelemetry

# ──────────────────────────────────────────────
# Registration tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_node_success():
    client = WorkerClient(node_id="node-1")
    client.connect()

    mock_resp = MagicMock()
    mock_resp.success = True

    mock_stub = AsyncMock()
    mock_stub.RegisterNode.return_value = mock_resp
    client.stub = mock_stub

    gpus = [
        GpuDevice(
            index=0,
            vendor="NVIDIA",
            model="RTX 4090",
            driver_version="555.42",
            total_vram_mb=24576,
        )
    ]

    success = await client.register_node(
        hostname="test-host",
        gpus=gpus,
        supported_workloads=["ffmpeg", "cuda"],
        os_name="windows",
        os_version="11",
        cpu_count=16,
        cpu_model="i9-13900K",
        total_ram_mb=65536,
    )

    assert success is True
    mock_stub.RegisterNode.assert_called_once()

    # Verify the proto message has GPU info
    call_args = mock_stub.RegisterNode.call_args
    req = call_args[0][0]
    assert req.node_id == "node-1"
    assert req.hostname == "test-host"
    assert req.os == "windows"
    assert req.cpu_count == 16
    assert len(req.gpus) == 1
    assert req.gpus[0].vendor == "NVIDIA"
    assert req.gpus[0].total_vram_mb == 24576


@pytest.mark.parametrize(
    "metrics_ip, metrics_port, colocated",
    [
        ("192.168.0.55", 9101, False),  # remote worker advertises its LAN IP
        ("", 9101, True),  # colocated worker (non-default bool)
        ("", 0, False),  # metrics disabled
    ],
)
@pytest.mark.asyncio
async def test_register_node_transmits_advertise_fields(
    metrics_ip, metrics_port, colocated
):
    """The self-advertised Prometheus scrape fields are transmitted in the proto."""
    client = WorkerClient(node_id="node-1")
    client.connect()

    mock_resp = MagicMock()
    mock_resp.success = True
    mock_stub = AsyncMock()
    mock_stub.RegisterNode.return_value = mock_resp
    client.stub = mock_stub

    await client.register_node(
        hostname="test-host",
        gpus=[],
        supported_workloads=[],
        metrics_ip=metrics_ip,
        metrics_port=metrics_port,
        colocated=colocated,
    )

    req = mock_stub.RegisterNode.call_args[0][0]
    assert req.metrics_ip == metrics_ip
    assert req.metrics_port == metrics_port
    assert req.colocated is colocated


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
        gpus=[],
        supported_workloads=["ffmpeg"],
    )

    assert success is False


# ──────────────────────────────────────────────
# Heartbeat tests
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_heartbeat_with_telemetry():
    client = WorkerClient(node_id="node-1")
    client.connect()

    mock_resp = MagicMock()
    mock_resp.acknowledged = True

    mock_stub = AsyncMock()
    mock_stub.SendHeartbeat.return_value = mock_resp
    client.stub = mock_stub

    telemetry = SystemTelemetry(
        gpus=[
            GpuTelemetry(
                index=0,
                temperature_c=72.0,
                gpu_utilization_percent=95.0,
                free_vram_mb=12000,
                used_vram_mb=12576,
                clock_core_mhz=2520,
            ),
        ],
        cpu_utilization_percent=45.0,
        ram_utilization_percent=62.0,
        ram_available_mb=25000,
    )

    success = await client.send_heartbeat(
        telemetry=telemetry,
        active_jobs=["job-1", "job-2"],
    )

    assert success is True
    mock_stub.SendHeartbeat.assert_called_once()

    # Verify proto message
    call_args = mock_stub.SendHeartbeat.call_args
    req = call_args[0][0]
    assert req.node_id == "node-1"
    assert req.cpu_utilization_percent == 45.0
    assert req.ram_utilization_percent == 62.0
    assert len(req.gpus) == 1
    assert req.gpus[0].temperature_c == 72.0
    assert req.gpus[0].clock_core_mhz == 2520
    assert list(req.active_job_ids) == ["job-1", "job-2"]


@pytest.mark.asyncio
async def test_send_heartbeat_network_failure():
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
    mock_stub.SendHeartbeat.side_effect = mock_error
    client.stub = mock_stub

    telemetry = SystemTelemetry()

    success = await client.send_heartbeat(
        telemetry=telemetry,
        active_jobs=[],
    )

    assert success is False
