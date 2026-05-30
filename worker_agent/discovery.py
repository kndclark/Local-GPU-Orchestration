import logging
import socket
import asyncio
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser

logger = logging.getLogger(__name__)

class OrchestratorListener:
    def __init__(self):
        self.found_url = None

    def on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change != ServiceStateChange.Added:
            return
        asyncio.create_task(self._resolve_service(zeroconf, service_type, name))

    async def _resolve_service(self, zeroconf, service_type, name):
        async_zc = AsyncZeroconf(zc=zeroconf)
        info = await async_zc.async_get_service_info(service_type, name)
        if info:
            addresses = [socket.inet_ntoa(a) for a in info.addresses]
            if addresses:
                def _score_ip(ip: str) -> int:
                    if ip.startswith("192.168."): return 100
                    if ip.startswith("10."): return 90
                    if ip.startswith("172."): return 80
                    if ip.startswith("169.254."): return 10
                    if ip == "127.0.0.1": return 0
                    return 50

                addresses.sort(key=_score_ip, reverse=True)
                ip = addresses[0]
                self.found_url = f"{ip}:{info.port}"
                logger.info(f"Auto-discovery successful! Found orchestrator at {self.found_url}")

async def discover_orchestrator(timeout: float = 5.0) -> str | None:
    """
    Finds the Control Plane on the local network using mDNS (Zeroconf).
    
    Returns:
        The URL of the orchestrator (e.g. '192.168.0.93:50051') if found,
        otherwise None.
    """
    logger.info("Starting mDNS auto-discovery for Control Plane...")
    
    zeroconf = AsyncZeroconf()
    listener = OrchestratorListener()
    
    # Start browsing for the GPU Orchestrator service
    browser = AsyncServiceBrowser(zeroconf.zeroconf, "_gpuorch._tcp.local.", handlers=[listener.on_service_state_change])
    
    import time
    start_time = time.time()
    
    try:
        # Poll the listener until a service is found or timeout is reached
        while time.time() - start_time < timeout:
            if listener.found_url:
                return listener.found_url
            await asyncio.sleep(0.1)
            
        logger.warning(f"Auto-discovery timed out after {timeout} seconds.")
    except Exception as e:
        logger.error(f"Auto-discovery failed: {e}")
    finally:
        await browser.async_cancel()
        await zeroconf.async_close()
        
    return None
