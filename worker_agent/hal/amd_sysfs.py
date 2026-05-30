"""AMD GPU backend using Linux sysfs — zero external dependencies.

Reads GPU telemetry from ``/sys/class/drm/card*/device/`` and associated
hwmon nodes. Works on SteamOS (Steam Deck, ROG Ally X) without needing
ROCm or ``amdsmi``.

Dependency injection: pass ``_reader`` to the constructor for testing.
The reader must provide ``card_paths()``, ``read_file(path)``, and
``exists(path)`` methods.
"""

import glob
import logging
import os
import re
from worker_agent.hal.base import (
    GpuBackend,
    GpuDevice,
    GpuTelemetry,
    SENSOR_NOT_AVAILABLE_INT,
    SENSOR_NOT_AVAILABLE_FLOAT,
)

logger = logging.getLogger(__name__)

AMD_VENDOR_ID = "0x1002"


class _RealSysfsReader:
    """Reads from the actual Linux sysfs filesystem."""

    def card_paths(self):
        cards = sorted(glob.glob("/sys/class/drm/card[0-9]*/device"))
        return cards

    def read_file(self, path):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError, OSError):
            return None

    def exists(self, path):
        return os.path.exists(path)


def _find_hwmon(device_path, reader):
    """Find the first hwmon directory under a device path."""
    # Try hwmon0 through hwmon9
    for i in range(10):
        candidate = f"{device_path}/hwmon/hwmon{i}"
        if reader.exists(f"{candidate}/temp1_input") or reader.read_file(
            f"{candidate}/temp1_input"
        ) is not None:
            return candidate
    return None


def _parse_active_dpm_clock(dpm_text):
    """Parse the active clock frequency from DPM sysfs output.

    DPM output looks like:
        0: 200Mhz
        1: 800Mhz *
        2: 1600Mhz

    The line ending with ``*`` is the active frequency.
    Returns the frequency in MHz, or SENSOR_NOT_AVAILABLE_INT if not found.
    """
    if not dpm_text:
        return SENSOR_NOT_AVAILABLE_INT

    for line in dpm_text.strip().split("\n"):
        if "*" in line:
            match = re.search(r"(\d+)\s*Mhz", line, re.IGNORECASE)
            if match:
                return int(match.group(1))

    return SENSOR_NOT_AVAILABLE_INT


class AmdSysfsBackend(GpuBackend):
    """GPU telemetry backend for AMD GPUs via Linux sysfs."""

    def __init__(self, _reader=None):
        self._reader = _reader or _RealSysfsReader()
        self._initialized = False
        self._amd_card_paths = []

    def name(self) -> str:
        return "AMD (sysfs)"

    def is_available(self) -> bool:
        self._amd_card_paths = []

        for card_path in self._reader.card_paths():
            vendor = self._reader.read_file(f"{card_path}/vendor")
            if vendor and vendor.strip().lower() == AMD_VENDOR_ID:
                self._amd_card_paths.append(card_path)

        if self._amd_card_paths:
            self._initialized = True
            return True

        return False

    def discover_gpus(self) -> list[GpuDevice]:
        if not self._initialized:
            return []

        gpus = []
        for i, card_path in enumerate(self._amd_card_paths):
            device_id = self._reader.read_file(f"{card_path}/device") or "unknown"

            vram_total_str = self._reader.read_file(f"{card_path}/mem_info_vram_total")
            vram_total_mb = 0
            if vram_total_str:
                try:
                    vram_total_mb = int(vram_total_str) // (1024 * 1024)
                except ValueError:
                    pass

            gpus.append(
                GpuDevice(
                    index=i,
                    vendor="AMD",
                    model=f"AMD GPU ({device_id})",
                    driver_version="",
                    total_vram_mb=vram_total_mb,
                )
            )

        return gpus

    def read_telemetry(self, gpu_index: int) -> GpuTelemetry:
        if not self._initialized:
            return GpuTelemetry(index=gpu_index)

        if gpu_index < 0 or gpu_index >= len(self._amd_card_paths):
            raise IndexError(
                f"GPU index {gpu_index} out of range "
                f"(0..{len(self._amd_card_paths) - 1})"
            )

        card_path = self._amd_card_paths[gpu_index]
        hwmon = _find_hwmon(card_path, self._reader)

        # ── VRAM ──────────────────────────────
        free_vram = SENSOR_NOT_AVAILABLE_INT
        used_vram = SENSOR_NOT_AVAILABLE_INT
        vram_total_str = self._reader.read_file(f"{card_path}/mem_info_vram_total")
        vram_used_str = self._reader.read_file(f"{card_path}/mem_info_vram_used")
        if vram_total_str and vram_used_str:
            try:
                total_bytes = int(vram_total_str)
                used_bytes = int(vram_used_str)
                used_vram = used_bytes // (1024 * 1024)
                free_vram = (total_bytes - used_bytes) // (1024 * 1024)
            except ValueError:
                pass

        # ── Temperature ───────────────────────
        temperature = SENSOR_NOT_AVAILABLE_FLOAT
        if hwmon:
            temp_str = self._reader.read_file(f"{hwmon}/temp1_input")
            if temp_str:
                try:
                    temperature = int(temp_str) / 1000.0  # millidegrees → °C
                except ValueError:
                    pass

        # ── GPU utilization ───────────────────
        gpu_util = SENSOR_NOT_AVAILABLE_FLOAT
        busy_str = self._reader.read_file(f"{card_path}/gpu_busy_percent")
        if busy_str:
            try:
                gpu_util = float(busy_str)
            except ValueError:
                pass

        # ── Power ─────────────────────────────
        power_draw = SENSOR_NOT_AVAILABLE_FLOAT
        if hwmon:
            power_str = self._reader.read_file(f"{hwmon}/power1_average")
            if power_str:
                try:
                    power_draw = int(power_str) / 1_000_000.0  # microwatts → W
                except ValueError:
                    pass

        # ── Fan speed ─────────────────────────
        fan_speed = SENSOR_NOT_AVAILABLE_FLOAT
        if hwmon:
            pwm_str = self._reader.read_file(f"{hwmon}/pwm1")
            pwm_max_str = self._reader.read_file(f"{hwmon}/pwm1_max")
            if pwm_str is not None and pwm_max_str is not None:
                try:
                    pwm = int(pwm_str)
                    pwm_max = int(pwm_max_str)
                    if pwm_max > 0:
                        fan_speed = (pwm / pwm_max) * 100.0
                    else:
                        fan_speed = 0.0
                except ValueError:
                    pass

        # ── Clocks ────────────────────────────
        sclk_text = self._reader.read_file(f"{card_path}/pp_dpm_sclk")
        mclk_text = self._reader.read_file(f"{card_path}/pp_dpm_mclk")
        clock_core = _parse_active_dpm_clock(sclk_text)
        clock_mem = _parse_active_dpm_clock(mclk_text)

        return GpuTelemetry(
            index=gpu_index,
            free_vram_mb=free_vram,
            used_vram_mb=used_vram,
            temperature_c=temperature,
            temperature_hotspot_c=SENSOR_NOT_AVAILABLE_FLOAT,
            fan_speed_percent=fan_speed,
            power_draw_w=power_draw,
            power_limit_w=SENSOR_NOT_AVAILABLE_FLOAT,
            gpu_utilization_percent=gpu_util,
            memory_utilization_percent=SENSOR_NOT_AVAILABLE_FLOAT,
            encoder_utilization_percent=SENSOR_NOT_AVAILABLE_FLOAT,
            decoder_utilization_percent=SENSOR_NOT_AVAILABLE_FLOAT,
            clock_core_mhz=clock_core,
            clock_memory_mhz=clock_mem,
            clock_core_max_mhz=SENSOR_NOT_AVAILABLE_INT,
            clock_memory_max_mhz=SENSOR_NOT_AVAILABLE_INT,
            pcie_gen=SENSOR_NOT_AVAILABLE_INT,
            pcie_width=SENSOR_NOT_AVAILABLE_INT,
            pcie_bandwidth_percent=SENSOR_NOT_AVAILABLE_FLOAT,
        )
