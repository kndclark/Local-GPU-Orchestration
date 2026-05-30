"""Base dataclasses and abstract interface for GPU telemetry backends.

All telemetry numeric fields default to -1 / -1.0 to indicate
"sensor not available", distinguishing missing data from a real zero reading.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ──────────────────────────────────────────────
# Telemetry Dataclasses
# ──────────────────────────────────────────────

SENSOR_NOT_AVAILABLE_INT = -1
SENSOR_NOT_AVAILABLE_FLOAT = -1.0


@dataclass
class GpuDevice:
    """Static GPU information discovered at registration time."""

    index: int
    vendor: str  # "NVIDIA" | "AMD"
    model: str
    driver_version: str = ""
    total_vram_mb: int = 0


@dataclass
class GpuTelemetry:
    """Live GPU telemetry snapshot.

    All numeric fields default to -1 / -1.0 meaning 'sensor not available'.
    """

    index: int
    # Memory
    free_vram_mb: int = SENSOR_NOT_AVAILABLE_INT
    used_vram_mb: int = SENSOR_NOT_AVAILABLE_INT
    # Thermals & Power
    temperature_c: float = SENSOR_NOT_AVAILABLE_FLOAT
    temperature_hotspot_c: float = SENSOR_NOT_AVAILABLE_FLOAT
    fan_speed_percent: float = SENSOR_NOT_AVAILABLE_FLOAT
    power_draw_w: float = SENSOR_NOT_AVAILABLE_FLOAT
    power_limit_w: float = SENSOR_NOT_AVAILABLE_FLOAT
    # Utilization
    gpu_utilization_percent: float = SENSOR_NOT_AVAILABLE_FLOAT
    memory_utilization_percent: float = SENSOR_NOT_AVAILABLE_FLOAT
    encoder_utilization_percent: float = SENSOR_NOT_AVAILABLE_FLOAT
    decoder_utilization_percent: float = SENSOR_NOT_AVAILABLE_FLOAT
    # Clocks
    clock_core_mhz: int = SENSOR_NOT_AVAILABLE_INT
    clock_memory_mhz: int = SENSOR_NOT_AVAILABLE_INT
    clock_core_max_mhz: int = SENSOR_NOT_AVAILABLE_INT
    clock_memory_max_mhz: int = SENSOR_NOT_AVAILABLE_INT
    # PCIe
    pcie_gen: int = SENSOR_NOT_AVAILABLE_INT
    pcie_width: int = SENSOR_NOT_AVAILABLE_INT
    pcie_bandwidth_percent: float = SENSOR_NOT_AVAILABLE_FLOAT


@dataclass
class DiskTelemetry:
    """Disk usage and I/O snapshot."""

    mount_point: str
    total_bytes: int = 0
    free_bytes: int = 0
    read_bytes_per_sec: float = 0.0
    write_bytes_per_sec: float = 0.0


@dataclass
class NetworkTelemetry:
    """Network interface I/O snapshot."""

    interface_name: str
    send_bytes_per_sec: float = 0.0
    recv_bytes_per_sec: float = 0.0


@dataclass
class SystemTelemetry:
    """Aggregated system telemetry from a single node."""

    gpus: list[GpuTelemetry] = field(default_factory=list)
    cpu_utilization_percent: float = 0.0
    ram_utilization_percent: float = 0.0
    ram_available_mb: int = 0
    disks: list[DiskTelemetry] = field(default_factory=list)
    network: list[NetworkTelemetry] = field(default_factory=list)


# ──────────────────────────────────────────────
# Abstract Backend Interface
# ──────────────────────────────────────────────


class GpuBackend(ABC):
    """Abstract interface for GPU telemetry backends.

    Implementations must handle their own library imports and
    gracefully report availability via ``is_available()``.
    """

    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name, e.g. 'NVIDIA (pynvml)'."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend can operate on the current machine."""
        ...

    @abstractmethod
    def discover_gpus(self) -> list[GpuDevice]:
        """Enumerate GPUs and return static device information."""
        ...

    @abstractmethod
    def read_telemetry(self, gpu_index: int) -> GpuTelemetry:
        """Read live telemetry for a specific GPU by index.

        Returns a GpuTelemetry with -1 / -1.0 for any metric whose
        sensor is not available on this hardware/driver combination.
        """
        ...

    def shutdown(self) -> None:
        """Release any resources held by this backend.

        Default implementation is a no-op. Override if needed
        (e.g. pynvml.nvmlShutdown).
        """
        pass
