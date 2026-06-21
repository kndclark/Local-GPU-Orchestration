import asyncio
import socket
from control_plane.discovery import ZeroconfAdvertiser
from worker_agent.discovery import discover_orchestrator


import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_zeroconf_discovery():
    """Test that the ZeroconfAdvertiser can be discovered by the worker agent."""

    # Start a dummy TCP server on an ephemeral port for reliable test discovery
    async def dummy_handler(reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(dummy_handler, "0.0.0.0", 0)
    port = server.sockets[0].getsockname()[1]

    test_service_type = "_testorch._tcp.local."
    advertiser = ZeroconfAdvertiser(grpc_port=port, service_type=test_service_type)
    await advertiser.async_start()

    try:
        # Give zeroconf a moment to register the service
        await asyncio.sleep(1.0)

        # Run the discovery client
        url = await discover_orchestrator(timeout=5.0, service_type=test_service_type, grpc_port=port)

        assert url is not None, "Discovery failed to find the orchestrator"
        assert url.endswith(f":{port}"), f"URL does not end with port {port}: {url}"

        # Verify the IP is valid
        ip = url.split(":")[0]
        socket.inet_aton(ip)
    finally:
        await advertiser.async_stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "advertised_ips, reachable_ips, expected_ip",
    [
        # Standard case: highest scored IP is reachable
        (["192.168.1.100", "10.0.0.5"], ["192.168.1.100", "10.0.0.5"], "192.168.1.100"),
        # Highest scored IP is down, fallback to next
        (["192.168.1.100", "10.0.0.5"], ["10.0.0.5"], "10.0.0.5"),
        # Only loopback available (skipped by logic) -> no orchestrator found
        (["127.0.0.1"], ["127.0.0.1"], None),
        # Nothing is reachable
        (["192.168.1.100"], [], None),
    ],
)
async def test_discovery_reachability_logic(advertised_ips, reachable_ips, expected_ip):
    """Test that discovery correctly sorts IPs and tests TCP reachability."""
    from worker_agent.discovery import OrchestratorListener

    listener = OrchestratorListener()

    # Mock the Zeroconf info response
    mock_info = MagicMock()
    mock_info.port = 50051
    mock_info.addresses = [socket.inet_aton(ip) for ip in advertised_ips]

    mock_zc = MagicMock()
    mock_zc.async_get_service_info = AsyncMock(return_value=mock_info)

    # Mock asyncio.open_connection to simulate reachability
    async def mock_open_connection(ip, port):
        if ip in reachable_ips:
            mock_writer = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            return (MagicMock(), mock_writer)
        else:
            raise ConnectionError(f"Mock connection failed for {ip}")

    with patch("worker_agent.discovery.AsyncZeroconf", return_value=mock_zc):
        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            await listener._resolve_service(None, "_gpuorch._tcp.local.", "test")

    if expected_ip:
        assert listener.found_url == f"{expected_ip}:50051"
    else:
        assert listener.found_url is None


def test_ip_scoring():
    """Verify that auto-discovery IP scoring correctly prioritizes routable networks."""
    from worker_agent.discovery import score_ip

    assert score_ip("192.168.1.100") == 100
    assert score_ip("10.0.0.5") == 90
    assert score_ip("172.16.0.2") == 80
    assert score_ip("169.254.1.1") == 10
    assert score_ip("127.0.0.1") == 0
    assert score_ip("8.8.8.8") == 50

    # Verify sorting order (highest to lowest)
    ips = [
        "127.0.0.1",
        "169.254.1.1",
        "8.8.8.8",
        "192.168.1.100",
        "10.0.0.5",
        "172.16.0.2",
    ]
    ips.sort(key=score_ip, reverse=True)
    assert ips == [
        "192.168.1.100",
        "10.0.0.5",
        "172.16.0.2",
        "8.8.8.8",
        "169.254.1.1",
        "127.0.0.1",
    ]
