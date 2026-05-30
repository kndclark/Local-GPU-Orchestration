import pytest
from worker_agent.hal.base import (
    GpuBackend,
    GpuDevice,
    GpuTelemetry,
    DiskTelemetry,
    NetworkTelemetry,
    SystemTelemetry,
    SENSOR_NOT_AVAILABLE_INT,
    SENSOR_NOT_AVAILABLE_FLOAT,
)

# ──────────────────────────────────────────────
# GpuDevice dataclass tests
# ──────────────────────────────────────────────


class TestGpuDevice:
    def test_construction_with_all_fields(self):
        gpu = GpuDevice(
            index=0,
            vendor="NVIDIA",
            model="RTX 4090",
            driver_version="555.42.02",
            total_vram_mb=24576,
        )
        assert gpu.index == 0
        assert gpu.vendor == "NVIDIA"
        assert gpu.model == "RTX 4090"
        assert gpu.driver_version == "555.42.02"
        assert gpu.total_vram_mb == 24576

    def test_construction_with_defaults(self):
        gpu = GpuDevice(index=1, vendor="AMD", model="RX 7600")
        assert gpu.driver_version == ""
        assert gpu.total_vram_mb == 0

    @pytest.mark.parametrize(
        "vendor",
        ["NVIDIA", "AMD", "INTEL"],
        ids=["nvidia", "amd", "intel"],
    )
    def test_vendor_values(self, vendor):
        gpu = GpuDevice(index=0, vendor=vendor, model="Test GPU")
        assert gpu.vendor == vendor


# ──────────────────────────────────────────────
# GpuTelemetry dataclass tests
# ──────────────────────────────────────────────


class TestGpuTelemetry:
    def test_all_defaults_are_sensor_not_available(self):
        """Every optional field should default to -1 / -1.0."""
        telem = GpuTelemetry(index=0)

        # Integer fields
        for field_name in [
            "free_vram_mb",
            "used_vram_mb",
            "clock_core_mhz",
            "clock_memory_mhz",
            "clock_core_max_mhz",
            "clock_memory_max_mhz",
            "pcie_gen",
            "pcie_width",
        ]:
            assert (
                getattr(telem, field_name) == SENSOR_NOT_AVAILABLE_INT
            ), f"{field_name} should default to {SENSOR_NOT_AVAILABLE_INT}"

        # Float fields
        for field_name in [
            "temperature_c",
            "temperature_hotspot_c",
            "fan_speed_percent",
            "power_draw_w",
            "power_limit_w",
            "gpu_utilization_percent",
            "memory_utilization_percent",
            "encoder_utilization_percent",
            "decoder_utilization_percent",
            "pcie_bandwidth_percent",
        ]:
            assert (
                getattr(telem, field_name) == SENSOR_NOT_AVAILABLE_FLOAT
            ), f"{field_name} should default to {SENSOR_NOT_AVAILABLE_FLOAT}"

    def test_construction_with_values(self):
        telem = GpuTelemetry(
            index=0,
            free_vram_mb=12000,
            used_vram_mb=12576,
            temperature_c=72.0,
            gpu_utilization_percent=95.0,
            clock_core_mhz=2520,
            pcie_gen=4,
            pcie_width=16,
        )
        assert telem.free_vram_mb == 12000
        assert telem.temperature_c == 72.0
        assert telem.gpu_utilization_percent == 95.0
        assert telem.clock_core_mhz == 2520
        assert telem.pcie_gen == 4
        assert telem.pcie_width == 16
        # Unset fields should still be sentinel
        assert telem.encoder_utilization_percent == SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.clock_memory_max_mhz == SENSOR_NOT_AVAILABLE_INT

    def test_sentinel_distinguishes_missing_from_zero(self):
        """A real 0.0 fan speed is different from 'sensor missing'."""
        telem_missing = GpuTelemetry(index=0)
        telem_zero = GpuTelemetry(index=0, fan_speed_percent=0.0)

        assert telem_missing.fan_speed_percent == -1.0
        assert telem_zero.fan_speed_percent == 0.0
        assert telem_missing.fan_speed_percent != telem_zero.fan_speed_percent


# ──────────────────────────────────────────────
# DiskTelemetry / NetworkTelemetry tests
# ──────────────────────────────────────────────


class TestDiskTelemetry:
    def test_construction(self):
        disk = DiskTelemetry(
            mount_point="/",
            total_bytes=500_000_000_000,
            free_bytes=250_000_000_000,
            read_bytes_per_sec=100_000_000.0,
            write_bytes_per_sec=50_000_000.0,
        )
        assert disk.mount_point == "/"
        assert disk.total_bytes == 500_000_000_000

    def test_defaults(self):
        disk = DiskTelemetry(mount_point="C:\\")
        assert disk.total_bytes == 0
        assert disk.free_bytes == 0
        assert disk.read_bytes_per_sec == 0.0
        assert disk.write_bytes_per_sec == 0.0


class TestNetworkTelemetry:
    def test_construction(self):
        net = NetworkTelemetry(
            interface_name="eth0",
            send_bytes_per_sec=1_000_000.0,
            recv_bytes_per_sec=2_000_000.0,
        )
        assert net.interface_name == "eth0"
        assert net.send_bytes_per_sec == 1_000_000.0

    def test_defaults(self):
        net = NetworkTelemetry(interface_name="lo")
        assert net.send_bytes_per_sec == 0.0
        assert net.recv_bytes_per_sec == 0.0


# ──────────────────────────────────────────────
# SystemTelemetry tests
# ──────────────────────────────────────────────


class TestSystemTelemetry:
    def test_defaults_are_empty(self):
        sys_telem = SystemTelemetry()
        assert sys_telem.gpus == []
        assert sys_telem.cpu_utilization_percent == 0.0
        assert sys_telem.ram_utilization_percent == 0.0
        assert sys_telem.ram_available_mb == 0
        assert sys_telem.disks == []
        assert sys_telem.network == []

    def test_construction_with_nested_telemetry(self):
        sys_telem = SystemTelemetry(
            gpus=[
                GpuTelemetry(index=0, temperature_c=65.0),
                GpuTelemetry(index=1, temperature_c=70.0),
            ],
            cpu_utilization_percent=45.0,
            ram_utilization_percent=62.0,
            ram_available_mb=16000,
            disks=[DiskTelemetry(mount_point="/")],
            network=[NetworkTelemetry(interface_name="eth0")],
        )
        assert len(sys_telem.gpus) == 2
        assert sys_telem.gpus[0].temperature_c == 65.0
        assert sys_telem.gpus[1].temperature_c == 70.0
        assert sys_telem.cpu_utilization_percent == 45.0
        assert len(sys_telem.disks) == 1
        assert len(sys_telem.network) == 1


# ──────────────────────────────────────────────
# GpuBackend ABC tests
# ──────────────────────────────────────────────


class TestGpuBackendABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError, match="abstract"):
            GpuBackend()

    def test_concrete_subclass_must_implement_all_methods(self):
        """A subclass missing any abstract method should raise TypeError."""

        class IncompleteBackend(GpuBackend):
            def name(self):
                return "incomplete"

        with pytest.raises(TypeError, match="abstract"):
            IncompleteBackend()

    def test_concrete_subclass_works(self):
        class ConcreteBackend(GpuBackend):
            def name(self):
                return "test"

            def is_available(self):
                return True

            def discover_gpus(self):
                return [GpuDevice(index=0, vendor="TEST", model="Test GPU")]

            def read_telemetry(self, gpu_index):
                return GpuTelemetry(index=gpu_index, temperature_c=42.0)

        backend = ConcreteBackend()
        assert backend.name() == "test"
        assert backend.is_available() is True
        assert len(backend.discover_gpus()) == 1
        assert backend.read_telemetry(0).temperature_c == 42.0

    def test_shutdown_is_noop_by_default(self):
        class MinimalBackend(GpuBackend):
            def name(self):
                return "minimal"

            def is_available(self):
                return False

            def discover_gpus(self):
                return []

            def read_telemetry(self, gpu_index):
                return GpuTelemetry(index=gpu_index)

        backend = MinimalBackend()
        # Should not raise
        backend.shutdown()
