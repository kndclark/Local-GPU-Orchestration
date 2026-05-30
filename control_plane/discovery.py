import logging
import socket
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf
import ifaddr

logger = logging.getLogger(__name__)

class ZeroconfAdvertiser:
    """Advertises the Control Plane gRPC service via mDNS/Zeroconf."""
    
    def __init__(self, grpc_port: int = 50051):
        self.grpc_port = grpc_port
        self.zeroconf = None
        self.info = None

    async def async_start(self):
        logger.info(f"Starting Zeroconf Advertiser for port {self.grpc_port}")
        
        # Collect all local IPv4 addresses (excluding 127.0.0.1 if possible)
        addresses = []
        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if ip.is_IPv4 and ip.ip != "127.0.0.1":
                    try:
                        addresses.append(socket.inet_aton(ip.ip))
                    except OSError:
                        pass
        
        # Fallback to localhost if no other IPs found
        if not addresses:
            addresses = [socket.inet_aton("127.0.0.1")]

        desc = {'service': 'GPU Orchestrator Control Plane'}
        
        # Standardize hostname format for Zeroconf
        hostname = socket.gethostname().replace(" ", "-").replace("_", "-")

        self.info = ServiceInfo(
            "_gpuorch._tcp.local.",
            f"{hostname}._gpuorch._tcp.local.",
            addresses=addresses,
            port=self.grpc_port,
            properties=desc,
            server=f"{hostname}.local.",
        )

        self.zeroconf = AsyncZeroconf()
        await self.zeroconf.async_register_service(self.info)
        logger.info("Zeroconf service registered successfully.")

    async def async_stop(self):
        if self.zeroconf and self.info:
            logger.info("Unregistering Zeroconf service...")
            await self.zeroconf.async_unregister_service(self.info)
            await self.zeroconf.async_close()
            self.zeroconf = None
            self.info = None
