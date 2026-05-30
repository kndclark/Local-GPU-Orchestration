import asyncio
import logging

logger = logging.getLogger(__name__)

class DiscoveryServerProtocol(asyncio.DatagramProtocol):
    """UDP protocol to respond to worker agent discovery broadcasts."""
    
    def __init__(self, grpc_port: int = 50051):
        self.grpc_port = grpc_port
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info("UDP Discovery Server started on port 50052")

    def datagram_received(self, data, addr):
        message = data.decode('utf-8', errors='ignore').strip()
        if message == "GPU_ORCHESTRATOR_DISCOVER":
            logger.info(f"Received discovery request from {addr}")
            response = f"GPU_ORCHESTRATOR_HERE:{self.grpc_port}"
            self.transport.sendto(response.encode('utf-8'), addr)
