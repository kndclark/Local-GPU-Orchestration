import logging
import socket
import asyncio
import ipaddress
import psutil
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser

logger = logging.getLogger(__name__)


def score_ip(ip: str) -> int:
    """
    Score IP address to prioritize standard local subnets over link-local.
    """
    if ip.startswith("192.168."):
        return 100
    if ip.startswith("10."):
        return 90
    if ip.startswith("172."):
        return 80
    if ip.startswith("169.254."):
        return 10
    if ip == "127.0.0.1":
        return 0
    return 50


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
                addresses.sort(key=score_ip, reverse=True)

                # Test connectivity to find a reachable IP concurrently
                async def check_ip(test_ip: str, port: int) -> str:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(test_ip, port), timeout=1.0
                    )
                    writer.close()
                    await writer.wait_closed()
                    return test_ip

                tasks = []
                for test_ip in addresses:
                    if test_ip == "127.0.0.1":
                        continue
                    tasks.append(asyncio.create_task(check_ip(test_ip, info.port)))

                if tasks:
                    while tasks:
                        done, pending = await asyncio.wait(
                            tasks, return_when=asyncio.FIRST_COMPLETED
                        )

                        reachable_ip = None
                        for task in tasks:
                            if task in done:
                                try:
                                    reachable_ip = task.result()
                                    break
                                except Exception:
                                    pass  # nosec B110

                        if reachable_ip:
                            # Cancel any remaining slow tasks
                            for task in pending:
                                task.cancel()

                            self.found_url = f"{reachable_ip}:{info.port}"
                            logger.info(
                                "Auto-discovery successful! "
                                f"Found reachable orchestrator at {self.found_url}"
                            )
                            return

                        tasks = list(pending)

                logger.warning(
                    "Auto-discovery found the orchestrator, "
                    "but none of its IPs were reachable."
                )


def get_local_subnet_ips() -> list[str]:
    ips_to_scan = set()
    try:
        for interface, snics in psutil.net_if_addrs().items():
            for snic in snics:
                if snic.family == socket.AF_INET:
                    ip = snic.address
                    netmask = snic.netmask
                    if ip == "127.0.0.1" or not netmask:
                        continue

                    try:
                        network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                        if network.prefixlen < 24:
                            network = ipaddress.IPv4Network(f"{ip}/24", strict=False)

                        for host in network.hosts():
                            ips_to_scan.add(str(host))
                    except ValueError:
                        continue
    except Exception as e:
        logger.warning(f"Failed to enumerate local subnets: {e}")

    return list(ips_to_scan)


async def check_orchestrator(
    test_ip: str, grpc_port: int = 50051, api_port: int = 8080
) -> str | None:
    """Attempts to connect to gRPC port, then verifies via HTTP API."""
    try:
        # Step 1: Fast TCP check on the gRPC port
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(test_ip, grpc_port), timeout=0.5
        )
        writer.close()
        await writer.wait_closed()

        # Step 2: If gRPC port is open, verify it's our orchestrator via HTTP API
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(test_ip, api_port), timeout=1.0
        )
        request = f"GET /api/v1/nodes HTTP/1.0\r\nHost: {test_ip}\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        response = await asyncio.wait_for(reader.read(1024), timeout=1.0)
        writer.close()
        await writer.wait_closed()

        if b"200 OK" in response:
            return f"{test_ip}:{grpc_port}"

    except Exception:
        pass
    return None


async def run_subnet_scanner(
    timeout: float = 5.0, grpc_port: int = 50051
) -> str | None:
    ips = get_local_subnet_ips()
    if not ips:
        return None

    tasks = [
        asyncio.create_task(check_orchestrator(ip, grpc_port=grpc_port)) for ip in ips
    ]

    start_time = asyncio.get_event_loop().time()

    while tasks and (asyncio.get_event_loop().time() - start_time) < timeout:
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED, timeout=0.5
        )
        for task in done:
            try:
                result = task.result()
                if result:
                    # Cancel all remaining tasks
                    for p in pending:
                        p.cancel()
                    return result
            except Exception:
                pass
        tasks = list(pending)

    # Timeout reached, cancel remaining
    for task in tasks:
        task.cancel()

    return None


async def discover_orchestrator(
    timeout: float = 5.0,
    service_type: str = "_gpuorch._tcp.local.",
    grpc_port: int = 50051,
) -> str | None:
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
    browser = AsyncServiceBrowser(
        zeroconf.zeroconf,
        service_type,
        handlers=[listener.on_service_state_change],
    )

    import time

    start_time = time.time()
    scanner_task = asyncio.create_task(run_subnet_scanner(timeout, grpc_port))

    try:
        # Poll the listener until a service is found or timeout is reached
        while time.time() - start_time < timeout:
            if listener.found_url:
                scanner_task.cancel()
                return listener.found_url

            if scanner_task.done():
                result = scanner_task.result()
                if result:
                    logger.info(f"Found reachable orchestrator at {result}")
                    return result

            await asyncio.sleep(0.1)

        logger.warning(f"Auto-discovery timed out after {timeout} seconds.")
    except Exception as e:
        logger.error(f"Auto-discovery failed: {e}")
    finally:
        scanner_task.cancel()
        await browser.async_cancel()
        await zeroconf.async_close()

    return None
