"""NVIDIA GPU backend using pynvml.

Reads GPU telemetry via the NVIDIA Management Library (NVML). The
``pynvml`` package is an optional dependency — the backend reports
itself as unavailable if it cannot be imported or initialised.

Dependency injection: pass ``_pynvml`` to the constructor for testing
with a mock object. In production, the real ``pynvml`` module is
imported lazily.
"""

import logging
from worker_agent.hal.base import (
    GpuBackend,
    GpuDevice,
    GpuTelemetry,
    SENSOR_NOT_AVAILABLE_INT,
    SENSOR_NOT_AVAILABLE_FLOAT,
)

logger = logging.getLogger(__name__)


class NvidiaBackend(GpuBackend):
    """GPU telemetry backend for NVIDIA GPUs via pynvml."""

    def __init__(self, _pynvml=None):
        """Initialise the backend.

        Args:
            _pynvml: Injected pynvml module (or mock) for testing.
                     If ``None``, the real ``pynvml`` module is imported.
        """
        self._pynvml = _pynvml
        self._initialized = False

        # Lazy-import real pynvml if not injected
        if self._pynvml is None:
            try:
                import pynvml

                self._pynvml = pynvml
            except ImportError:
                logger.debug("pynvml not installed — NVIDIA backend unavailable")
                self._pynvml = None

    def name(self) -> str:
        return "NVIDIA (pynvml)"

    def is_available(self) -> bool:
        if self._pynvml is None:
            return False
        try:
            self._pynvml.nvmlInit()
            self._initialized = True
            return True
        except self._pynvml.NVMLError as e:
            logger.debug(f"NVML init failed: {e}")
            return False

    def discover_gpus(self) -> list[GpuDevice]:
        if not self._initialized:
            return []

        nvml = self._pynvml
        driver = nvml.nvmlSystemGetDriverVersion()
        count = nvml.nvmlDeviceGetCount()
        gpus = []

        for i in range(count):
            handle = nvml.nvmlDeviceGetHandleByIndex(i)
            name = nvml.nvmlDeviceGetName(handle)
            mem_info = nvml.nvmlDeviceGetMemoryInfo(handle)

            gpus.append(
                GpuDevice(
                    index=i,
                    vendor="NVIDIA",
                    model=name,
                    driver_version=driver,
                    total_vram_mb=mem_info.total // (1024 * 1024),
                )
            )

        return gpus

    def read_telemetry(self, gpu_index: int) -> GpuTelemetry:
        if not self._initialized:
            return GpuTelemetry(index=gpu_index)

        nvml = self._pynvml

        try:
            handle = nvml.nvmlDeviceGetHandleByIndex(gpu_index)
        except nvml.NVMLError:
            raise IndexError(f"GPU index {gpu_index} not found")

        # ── Memory ────────────────────────────
        free_vram = SENSOR_NOT_AVAILABLE_INT
        used_vram = SENSOR_NOT_AVAILABLE_INT
        try:
            mem = nvml.nvmlDeviceGetMemoryInfo(handle)
            free_vram = mem.free // (1024 * 1024)
            used_vram = mem.used // (1024 * 1024)
        except nvml.NVMLError:
            pass

        # ── Temperature ───────────────────────
        temperature = SENSOR_NOT_AVAILABLE_FLOAT
        try:
            temperature = float(
                nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU)
            )
        except nvml.NVMLError:
            pass

        # ── Utilization ───────────────────────
        gpu_util = SENSOR_NOT_AVAILABLE_FLOAT
        mem_util = SENSOR_NOT_AVAILABLE_FLOAT
        try:
            rates = nvml.nvmlDeviceGetUtilizationRates(handle)
            gpu_util = float(rates.gpu)
            mem_util = float(rates.memory)
        except nvml.NVMLError:
            pass

        # ── Fan speed ─────────────────────────
        fan_speed = SENSOR_NOT_AVAILABLE_FLOAT
        try:
            fan_speed = float(nvml.nvmlDeviceGetFanSpeed(handle))
        except nvml.NVMLError:
            pass

        # ── Power ─────────────────────────────
        power_draw = SENSOR_NOT_AVAILABLE_FLOAT
        power_limit = SENSOR_NOT_AVAILABLE_FLOAT
        try:
            power_draw = nvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
        except nvml.NVMLError:
            pass
        try:
            power_limit = nvml.nvmlDeviceGetEnforcedPowerLimit(handle) / 1000.0
        except nvml.NVMLError:
            pass

        # ── Clocks ────────────────────────────
        clock_core = SENSOR_NOT_AVAILABLE_INT
        clock_mem = SENSOR_NOT_AVAILABLE_INT
        clock_core_max = SENSOR_NOT_AVAILABLE_INT
        clock_mem_max = SENSOR_NOT_AVAILABLE_INT
        try:
            clock_core = nvml.nvmlDeviceGetClockInfo(handle, nvml.NVML_CLOCK_GRAPHICS)
        except nvml.NVMLError:
            pass
        try:
            clock_mem = nvml.nvmlDeviceGetClockInfo(handle, nvml.NVML_CLOCK_MEM)
        except nvml.NVMLError:
            pass
        try:
            clock_core_max = nvml.nvmlDeviceGetMaxClockInfo(
                handle, nvml.NVML_CLOCK_GRAPHICS
            )
        except nvml.NVMLError:
            pass
        try:
            clock_mem_max = nvml.nvmlDeviceGetMaxClockInfo(handle, nvml.NVML_CLOCK_MEM)
        except nvml.NVMLError:
            pass

        # ── PCIe ──────────────────────────────
        pcie_gen = SENSOR_NOT_AVAILABLE_INT
        pcie_width = SENSOR_NOT_AVAILABLE_INT
        try:
            pcie_gen = nvml.nvmlDeviceGetCurrPcieLinkGeneration(handle)
        except nvml.NVMLError:
            pass
        try:
            pcie_width = nvml.nvmlDeviceGetCurrPcieLinkWidth(handle)
        except nvml.NVMLError:
            pass

        # ── Encoder / decoder ─────────────────
        encoder_util = SENSOR_NOT_AVAILABLE_FLOAT
        decoder_util = SENSOR_NOT_AVAILABLE_FLOAT
        try:
            enc_util, _ = nvml.nvmlDeviceGetEncoderUtilization(handle)
            encoder_util = float(enc_util)
        except nvml.NVMLError:
            pass
        try:
            dec_util, _ = nvml.nvmlDeviceGetDecoderUtilization(handle)
            decoder_util = float(dec_util)
        except nvml.NVMLError:
            pass

        return GpuTelemetry(
            index=gpu_index,
            free_vram_mb=free_vram,
            used_vram_mb=used_vram,
            temperature_c=temperature,
            temperature_hotspot_c=SENSOR_NOT_AVAILABLE_FLOAT,
            fan_speed_percent=fan_speed,
            power_draw_w=power_draw,
            power_limit_w=power_limit,
            gpu_utilization_percent=gpu_util,
            memory_utilization_percent=mem_util,
            encoder_utilization_percent=encoder_util,
            decoder_utilization_percent=decoder_util,
            clock_core_mhz=clock_core,
            clock_memory_mhz=clock_mem,
            clock_core_max_mhz=clock_core_max,
            clock_memory_max_mhz=clock_mem_max,
            pcie_gen=pcie_gen,
            pcie_width=pcie_width,
            pcie_bandwidth_percent=SENSOR_NOT_AVAILABLE_FLOAT,
        )

    def shutdown(self) -> None:
        if self._initialized and self._pynvml is not None:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:  # nosec B110
                pass
            self._initialized = False
