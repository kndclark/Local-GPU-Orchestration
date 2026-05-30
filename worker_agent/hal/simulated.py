"""Simulated GPU backend for CI testing and development without hardware.

Produces configurable, realistic-looking GPU telemetry data. When
``noise=True`` (the default), readings fluctuate slightly on each call
to mimic real sensor behaviour.
"""

import random
from dataclasses import dataclass

from worker_agent.hal.base import GpuBackend, GpuDevice, GpuTelemetry


@dataclass
class SimulatedConfig:
    """Configuration for the simulated GPU backend."""

    num_gpus: int = 1
    vendor: str = "NVIDIA"
    model: str = "Simulated RTX 4090"
    total_vram_mb: int = 24576
    noise: bool = True


# Base values for deterministic (no-noise) mode
_BASE = {
    "temperature_c": 55.0,
    "temperature_hotspot_c": 62.0,
    "fan_speed_percent": 40.0,
    "power_draw_w": 180.0,
    "power_limit_w": 350.0,
    "gpu_utilization_percent": 45.0,
    "memory_utilization_percent": 35.0,
    "encoder_utilization_percent": 10.0,
    "decoder_utilization_percent": 5.0,
    "clock_core_mhz": 2100,
    "clock_memory_mhz": 1313,
    "clock_core_max_mhz": 2520,
    "clock_memory_max_mhz": 1313,
    "pcie_gen": 4,
    "pcie_width": 16,
    "pcie_bandwidth_percent": 12.0,
    "vram_used_fraction": 0.4,
}


def _noisy(base: float, amplitude: float = 5.0) -> float:
    """Add uniform random noise to a base value."""
    return base + random.uniform(-amplitude, amplitude)  # nosec B311


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class SimulatedBackend(GpuBackend):
    """Fake GPU backend that returns configurable telemetry data."""

    def __init__(self, config: SimulatedConfig | None = None):
        self._config = config or SimulatedConfig()

    def name(self) -> str:
        return "Simulated"

    def is_available(self) -> bool:
        return True

    def discover_gpus(self) -> list[GpuDevice]:
        return [
            GpuDevice(
                index=i,
                vendor=self._config.vendor,
                model=self._config.model,
                driver_version="sim-1.0.0",
                total_vram_mb=self._config.total_vram_mb,
            )
            for i in range(self._config.num_gpus)
        ]

    def read_telemetry(self, gpu_index: int) -> GpuTelemetry:
        if gpu_index < 0 or gpu_index >= self._config.num_gpus:
            raise IndexError(
                f"GPU index {gpu_index} out of range "
                f"(0..{self._config.num_gpus - 1})"
            )

        if self._config.noise:
            temp = _clamp(_noisy(_BASE["temperature_c"], 8.0), 25.0, 90.0)
            hotspot = _clamp(temp + random.uniform(3.0, 10.0), 28.0, 95.0)  # nosec B311
            util = _clamp(_noisy(_BASE["gpu_utilization_percent"], 15.0), 0.0, 100.0)
            mem_util = _clamp(
                _noisy(_BASE["memory_utilization_percent"], 10.0), 0.0, 100.0
            )
            fan = _clamp(_noisy(_BASE["fan_speed_percent"], 10.0), 0.0, 100.0)
            power = _clamp(_noisy(_BASE["power_draw_w"], 30.0), 20.0, 340.0)
            enc = _clamp(_noisy(_BASE["encoder_utilization_percent"], 5.0), 0.0, 100.0)
            dec = _clamp(_noisy(_BASE["decoder_utilization_percent"], 3.0), 0.0, 100.0)
            core_clk = max(800, int(_noisy(_BASE["clock_core_mhz"], 200)))
            mem_clk = max(800, int(_noisy(_BASE["clock_memory_mhz"], 50)))
            pcie_bw = _clamp(_noisy(_BASE["pcie_bandwidth_percent"], 5.0), 0.0, 100.0)
            vram_frac = _clamp(
                _BASE["vram_used_fraction"] + random.uniform(-0.1, 0.1),
                0.05,
                0.95,  # nosec B311
            )
        else:
            temp = _BASE["temperature_c"]
            hotspot = _BASE["temperature_hotspot_c"]
            util = _BASE["gpu_utilization_percent"]
            mem_util = _BASE["memory_utilization_percent"]
            fan = _BASE["fan_speed_percent"]
            power = _BASE["power_draw_w"]
            enc = _BASE["encoder_utilization_percent"]
            dec = _BASE["decoder_utilization_percent"]
            core_clk = _BASE["clock_core_mhz"]
            mem_clk = _BASE["clock_memory_mhz"]
            pcie_bw = _BASE["pcie_bandwidth_percent"]
            vram_frac = _BASE["vram_used_fraction"]

        used = int(self._config.total_vram_mb * vram_frac)
        free = self._config.total_vram_mb - used

        return GpuTelemetry(
            index=gpu_index,
            free_vram_mb=free,
            used_vram_mb=used,
            temperature_c=temp,
            temperature_hotspot_c=hotspot,
            fan_speed_percent=fan,
            power_draw_w=power,
            power_limit_w=_BASE["power_limit_w"],
            gpu_utilization_percent=util,
            memory_utilization_percent=mem_util,
            encoder_utilization_percent=enc,
            decoder_utilization_percent=dec,
            clock_core_mhz=int(core_clk),
            clock_memory_mhz=int(mem_clk),
            clock_core_max_mhz=int(_BASE["clock_core_max_mhz"]),
            clock_memory_max_mhz=int(_BASE["clock_memory_max_mhz"]),
            pcie_gen=int(_BASE["pcie_gen"]),
            pcie_width=int(_BASE["pcie_width"]),
            pcie_bandwidth_percent=pcie_bw,
        )
