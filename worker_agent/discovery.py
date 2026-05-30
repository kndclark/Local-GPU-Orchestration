import socket
import logging

logger = logging.getLogger(__name__)

def discover_orchestrator(discovery_port: int = 50052, timeout: float = 3.0) -> str | None:
    """
    Broadcasts a UDP packet to find the Control Plane on the local network.
    
    Returns:
        The URL of the orchestrator (e.g. '192.168.0.93:50051') if found,
        otherwise None.
    """
    logger.info("Starting UDP auto-discovery for Control Plane...")
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    # Enable broadcasting mode
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    # Set a timeout so it doesn't block forever
    sock.settimeout(timeout)

    message = b"GPU_ORCHESTRATOR_DISCOVER"
    
    try:
        # Send broadcast to the specific discovery port
        sock.sendto(message, ('<broadcast>', discovery_port))
        
        # Wait for a response
        data, addr = sock.recvfrom(1024)
        resp = data.decode('utf-8', errors='ignore').strip()
        
        if resp.startswith("GPU_ORCHESTRATOR_HERE:"):
            grpc_port = resp.split(":")[1]
            server_ip = addr[0]
            url = f"{server_ip}:{grpc_port}"
            logger.info(f"Auto-discovery successful! Found orchestrator at {url}")
            return url
            
    except socket.timeout:
        logger.warning(f"Auto-discovery timed out after {timeout} seconds.")
    except Exception as e:
        logger.error(f"Auto-discovery failed: {e}")
    finally:
        sock.close()
        
    return None
