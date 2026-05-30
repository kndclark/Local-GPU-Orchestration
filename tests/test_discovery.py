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
