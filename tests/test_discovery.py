import pytest
import asyncio
import socket
from control_plane.discovery import ZeroconfAdvertiser
from worker_agent.discovery import discover_orchestrator

async def test_zeroconf_discovery():
    """Test that the ZeroconfAdvertiser can be discovered by the worker agent."""
    advertiser = ZeroconfAdvertiser(grpc_port=50051)
    await advertiser.async_start()
    
    try:
        # Give zeroconf a moment to register the service
        await asyncio.sleep(1.0)
        
        # Run the discovery client
        url = await discover_orchestrator(timeout=5.0)
        
        assert url is not None, "Discovery failed to find the orchestrator"
        assert url.endswith(":50051"), f"URL does not end with port 50051: {url}"
        
        # Verify the IP is valid
        ip = url.split(":")[0]
        socket.inet_aton(ip)
    finally:
        await advertiser.async_stop()


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
        "172.16.0.2"
    ]
    ips.sort(key=score_ip, reverse=True)
    assert ips == [
        "192.168.1.100",
        "10.0.0.5",
        "172.16.0.2",
        "8.8.8.8",
        "169.254.1.1",
        "127.0.0.1"
    ]

