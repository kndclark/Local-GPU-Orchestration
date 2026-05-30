"""HardwareManager — main entry point for the HAL.

Orchestrates backend auto-detection, GPU discovery, and system-wide
telemetry aggregation (GPU + CPU + RAM + disk + network via psutil).
"""

import logging
from worker_agent.hal.base import (
    GpuBackend,
    GpuDevice,
    GpuTelemetry,
    SystemTelemetry,
    DiskTelemetry,
    NetworkTelemetry,
)

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class HardwareManager:
    """Detects available GPU hardware and aggregates system telemetry.

    Args:
        backends: Optional list of GpuBackend instances to probe, in
            priority order. If ``None``, the default discovery order is
            used: NVIDIA → AMD sysfs → Simulated (fallback).
    """

    def __init__(self, backends: list[GpuBackend] | None = None):
        self._backends = backends or self._default_backends()
        self.active_backend: GpuBackend | None = None
        self._gpu_devices: list[GpuDevice] = []

    @staticmethod
    def _default_backends() -> list[GpuBackend]:
        """Build the default backend list with lazy imports."""
        backends: list[GpuBackend] = []

        try:
            from worker_agent.hal.nvidia import NvidiaBackend

            backends.append(NvidiaBackend())
        except Exception:  # nosec B110
            pass

        try:
            from worker_agent.hal.amd_sysfs import AmdSysfsBackend

            backends.append(AmdSysfsBackend())
        except Exception:  # nosec B110
            pass

        # Simulated is always the last fallback
        from worker_agent.hal.simulated import SimulatedBackend

        backends.append(SimulatedBackend())

        return backends

    def detect(self) -> None:
        """Probe backends in order and select the first available one."""
        for backend in self._backends:
            try:
                if backend.is_available():
                    self.active_backend = backend
                    self._gpu_devices = backend.discover_gpus()
                    logger.info(
                        f"HAL: using {backend.name()} — "
                        f"found {len(self._gpu_devices)} GPU(s)"
                    )
                    return
            except Exception as e:
                logger.warning(f"HAL: {backend.name()} probe failed: {e}")
                continue

        logger.warning("HAL: no GPU backend available")

    def get_gpu_devices(self) -> list[GpuDevice]:
        """Return the discovered GPU devices (empty if detect() not called)."""
        return self._gpu_devices

    def detected_vendors(self) -> set[str]:
        """Return the set of GPU vendor strings from discovered devices.

        Useful for the pytest auto-skip hardware marker system:
        ``pytest -m hardware`` auto-detects vendors and skips tests
        for hardware not present on this machine.
        """
        return {gpu.vendor for gpu in self._gpu_devices}

    def get_system_telemetry(self) -> SystemTelemetry:
        """Collect a full system telemetry snapshot.

        Aggregates GPU telemetry from the active backend with CPU, RAM,
        disk, and network data from psutil.
        """
        # ── GPU telemetry ─────────────────────
        gpu_telemetry: list[GpuTelemetry] = []
        if self.active_backend and self._gpu_devices:
            for gpu in self._gpu_devices:
                try:
                    telem = self.active_backend.read_telemetry(gpu.index)
                    gpu_telemetry.append(telem)
                except Exception as e:
                    logger.warning(
                        f"HAL: failed to read telemetry for GPU {gpu.index}: {e}"
                    )

        # ── CPU / RAM ─────────────────────────
        cpu_util = 0.0
        ram_util = 0.0
        ram_available_mb = 0

        if psutil is not None:
            try:
                cpu_util = psutil.cpu_percent(interval=None)
            except Exception:
                pass
            try:
                vm = psutil.virtual_memory()
                ram_util = vm.percent
                ram_available_mb = int(vm.available / (1024 * 1024))
            except Exception:
                pass

        # ── Disk ──────────────────────────────
        disks: list[DiskTelemetry] = []
        if psutil is not None:
            try:
                for part in psutil.disk_partitions():
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        disks.append(
                            DiskTelemetry(
                                mount_point=part.mountpoint,
                                total_bytes=usage.total,
                                free_bytes=usage.free,
                            )
                        )
                    except (PermissionError, OSError):
                        pass
            except Exception:
                pass

        # ── Network ───────────────────────────
        network: list[NetworkTelemetry] = []
        # Network I/O is aggregated (not per-interface) for simplicity
        if psutil is not None:
            try:
                net_io = psutil.net_io_counters()
                network.append(
                    NetworkTelemetry(
                        interface_name="all",
                        send_bytes_per_sec=float(net_io.bytes_sent),
                        recv_bytes_per_sec=float(net_io.bytes_recv),
                    )
                )
            except Exception:
                pass

        return SystemTelemetry(
            gpus=gpu_telemetry,
            cpu_utilization_percent=cpu_util,
            ram_utilization_percent=ram_util,
            ram_available_mb=ram_available_mb,
            disks=disks,
            network=network,
        )

    def shutdown(self) -> None:
        """Release resources held by the active backend."""
        if self.active_backend:
            try:
                self.active_backend.shutdown()
            except Exception:
                pass
