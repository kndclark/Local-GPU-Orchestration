"""Tests for the HardwareManager — backend auto-detection and system telemetry."""

import pytest
from unittest.mock import patch, MagicMock
from worker_agent.hal.base import (
    GpuBackend,
    GpuDevice,
    GpuTelemetry,
    SystemTelemetry,
)
from worker_agent.hal.simulated import SimulatedBackend, SimulatedConfig
from worker_agent.hal.manager import HardwareManager

# ──────────────────────────────────────────────
# Helper: Fake backend for injection
# ──────────────────────────────────────────────


class FakeBackend(GpuBackend):
    """A controllable fake backend for testing the manager."""

    def __init__(self, backend_name, available=True, gpu_count=1):
        self._name = backend_name
        self._available = available
        self._gpu_count = gpu_count

    def name(self):
        return self._name

    def is_available(self):
        return self._available

    def discover_gpus(self):
        return [
            GpuDevice(index=i, vendor="FAKE", model=f"Fake GPU {i}")
            for i in range(self._gpu_count)
        ]

    def read_telemetry(self, gpu_index):
        return GpuTelemetry(index=gpu_index, temperature_c=42.0)


# ──────────────────────────────────────────────
# Auto-detection priority
# ──────────────────────────────────────────────


class TestManagerDetection:
    def test_picks_first_available_backend(self):
        backends = [
            FakeBackend("first", available=True),
            FakeBackend("second", available=True),
        ]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        assert mgr.active_backend is not None
        assert mgr.active_backend.name() == "first"

    def test_skips_unavailable_backends(self):
        backends = [
            FakeBackend("unavailable", available=False),
            FakeBackend("available", available=True),
        ]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        assert mgr.active_backend.name() == "available"

    @pytest.mark.parametrize(
        "nvidia_avail,amd_avail,expected",
        [
            (True, False, "nvidia"),
            (False, True, "amd"),
            (True, True, "nvidia"),  # nvidia has priority
            (False, False, "simulated"),  # fallback
        ],
        ids=["nvidia-only", "amd-only", "both-nvidia-wins", "none-simulated-fallback"],
    )
    def test_detection_priority(self, nvidia_avail, amd_avail, expected):
        backends = [
            FakeBackend("nvidia", available=nvidia_avail),
            FakeBackend("amd", available=amd_avail),
            SimulatedBackend(),  # always available fallback
        ]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        # Simulated always matches if nothing else does
        if expected == "simulated":
            assert isinstance(mgr.active_backend, SimulatedBackend)
        else:
            assert mgr.active_backend.name() == expected

    def test_fallback_to_simulated_when_no_hardware(self):
        """When no real backends are available, fall back to SimulatedBackend."""
        backends = [
            FakeBackend("nvidia", available=False),
            FakeBackend("amd", available=False),
            SimulatedBackend(),
        ]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        assert isinstance(mgr.active_backend, SimulatedBackend)


# ──────────────────────────────────────────────
# GPU device discovery via manager
# ──────────────────────────────────────────────


class TestManagerGpuDevices:
    def test_get_gpu_devices(self):
        backends = [FakeBackend("test", available=True, gpu_count=3)]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        gpus = mgr.get_gpu_devices()
        assert len(gpus) == 3
        assert all(isinstance(g, GpuDevice) for g in gpus)

    def test_get_gpu_devices_before_detect_returns_empty(self):
        mgr = HardwareManager(backends=[FakeBackend("test", available=True)])
        gpus = mgr.get_gpu_devices()
        assert gpus == []


# ──────────────────────────────────────────────
# System telemetry aggregation
# ──────────────────────────────────────────────


class TestManagerSystemTelemetry:
    @patch("worker_agent.hal.manager.psutil")
    def test_get_system_telemetry(self, mock_psutil):
        # Mock psutil responses
        mock_psutil.cpu_percent.return_value = 35.0
        mock_psutil.virtual_memory.return_value = MagicMock(
            percent=60.0,
            available=16_000_000_000,  # ~15.26 GB
        )
        mock_psutil.disk_partitions.return_value = [
            MagicMock(mountpoint="/"),
            MagicMock(mountpoint="/boot"),
        ]
        mock_psutil.disk_usage.side_effect = lambda mp: MagicMock(
            total=500_000_000_000,
            free=250_000_000_000,
        )

        mock_disk_io = MagicMock()
        mock_disk_io.read_bytes = 1_000_000
        mock_disk_io.write_bytes = 500_000
        mock_psutil.disk_io_counters.return_value = mock_disk_io

        mock_net_io = MagicMock()
        mock_net_io.bytes_sent = 2_000_000
        mock_net_io.bytes_recv = 3_000_000
        mock_psutil.net_io_counters.return_value = mock_net_io

        backends = [FakeBackend("test", available=True, gpu_count=2)]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        telem = mgr.get_system_telemetry()

        assert isinstance(telem, SystemTelemetry)
        assert telem.cpu_utilization_percent == 35.0
        assert telem.ram_utilization_percent == 60.0
        assert telem.ram_available_mb > 0
        assert len(telem.gpus) == 2
        assert all(isinstance(g, GpuTelemetry) for g in telem.gpus)

    @patch("worker_agent.hal.manager.psutil")
    def test_get_system_telemetry_before_detect_returns_defaults(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.virtual_memory.return_value = MagicMock(
            percent=20.0, available=32_000_000_000
        )
        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = MagicMock(
            read_bytes=0, write_bytes=0
        )
        mock_psutil.net_io_counters.return_value = MagicMock(bytes_sent=0, bytes_recv=0)

        mgr = HardwareManager(backends=[FakeBackend("test", available=True)])
        telem = mgr.get_system_telemetry()

        assert telem.gpus == []  # No GPUs discovered yet
        assert telem.cpu_utilization_percent == 10.0


# ──────────────────────────────────────────────
# Detected hardware vendors (for auto-skip markers)
# ──────────────────────────────────────────────


class TestManagerDetectedVendors:
    def test_detected_vendors_with_backend(self):
        backends = [FakeBackend("nvidia", available=True)]
        mgr = HardwareManager(backends=backends)
        mgr.detect()

        vendors = mgr.detected_vendors()
        assert "FAKE" in vendors  # FakeBackend returns "FAKE" vendor

    def test_detected_vendors_before_detect_is_empty(self):
        mgr = HardwareManager(backends=[FakeBackend("test", available=True)])
        vendors = mgr.detected_vendors()
        assert vendors == set()

    def test_detected_vendors_with_simulated(self):
        """SimulatedBackend should report its configured vendor."""
        cfg = SimulatedConfig(vendor="NVIDIA")
        mgr = HardwareManager(backends=[SimulatedBackend(config=cfg)])
        mgr.detect()

        vendors = mgr.detected_vendors()
        assert "NVIDIA" in vendors
