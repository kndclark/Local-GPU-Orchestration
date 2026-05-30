import pytest
from worker_agent.hal.base import (
    GpuDevice,
    GpuTelemetry,
    SENSOR_NOT_AVAILABLE_FLOAT,
)
from worker_agent.hal.simulated import SimulatedBackend, SimulatedConfig

# ──────────────────────────────────────────────
# SimulatedConfig tests
# ──────────────────────────────────────────────


class TestSimulatedConfig:
    def test_default_config(self):
        cfg = SimulatedConfig()
        assert cfg.num_gpus == 1
        assert cfg.vendor == "NVIDIA"
        assert cfg.model == "Simulated RTX 4090"
        assert cfg.total_vram_mb == 24576
        assert cfg.noise is True

    def test_custom_config(self):
        cfg = SimulatedConfig(
            num_gpus=2,
            vendor="AMD",
            model="Simulated RX 7600",
            total_vram_mb=8192,
            noise=False,
        )
        assert cfg.num_gpus == 2
        assert cfg.vendor == "AMD"
        assert cfg.total_vram_mb == 8192


# ──────────────────────────────────────────────
# SimulatedBackend core behavior
# ──────────────────────────────────────────────


class TestSimulatedBackend:
    def test_name(self):
        backend = SimulatedBackend()
        assert "simulated" in backend.name().lower()

    def test_is_always_available(self):
        backend = SimulatedBackend()
        assert backend.is_available() is True

    def test_discover_gpus_default_single(self):
        backend = SimulatedBackend()
        gpus = backend.discover_gpus()
        assert len(gpus) == 1
        assert isinstance(gpus[0], GpuDevice)
        assert gpus[0].index == 0
        assert gpus[0].vendor == "NVIDIA"
        assert gpus[0].total_vram_mb == 24576

    @pytest.mark.parametrize("num_gpus", [1, 2, 4, 8])
    def test_discover_gpus_count(self, num_gpus):
        cfg = SimulatedConfig(num_gpus=num_gpus)
        backend = SimulatedBackend(config=cfg)
        gpus = backend.discover_gpus()
        assert len(gpus) == num_gpus
        for i, gpu in enumerate(gpus):
            assert gpu.index == i

    def test_discover_gpus_inherits_config_vendor(self):
        cfg = SimulatedConfig(vendor="AMD", model="Simulated RX 7900 XTX")
        backend = SimulatedBackend(config=cfg)
        gpus = backend.discover_gpus()
        assert all(gpu.vendor == "AMD" for gpu in gpus)
        assert all(gpu.model == "Simulated RX 7900 XTX" for gpu in gpus)

    def test_read_telemetry_returns_valid_data(self):
        backend = SimulatedBackend()
        telem = backend.read_telemetry(0)
        assert isinstance(telem, GpuTelemetry)
        assert telem.index == 0
        # All telemetry values should be real (not sentinel)
        assert telem.temperature_c != SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.gpu_utilization_percent != SENSOR_NOT_AVAILABLE_FLOAT
        assert telem.free_vram_mb >= 0
        assert telem.used_vram_mb >= 0
        assert telem.power_draw_w >= 0

    def test_read_telemetry_values_in_realistic_range(self):
        backend = SimulatedBackend()
        telem = backend.read_telemetry(0)
        assert 20.0 <= telem.temperature_c <= 95.0
        assert 0.0 <= telem.gpu_utilization_percent <= 100.0
        assert 0.0 <= telem.fan_speed_percent <= 100.0
        assert telem.power_draw_w <= telem.power_limit_w
        assert telem.free_vram_mb + telem.used_vram_mb > 0

    def test_read_telemetry_vram_sums_to_total(self):
        cfg = SimulatedConfig(total_vram_mb=8192, noise=False)
        backend = SimulatedBackend(config=cfg)
        telem = backend.read_telemetry(0)
        assert telem.free_vram_mb + telem.used_vram_mb == 8192

    def test_read_telemetry_invalid_index_raises(self):
        backend = SimulatedBackend()
        with pytest.raises(IndexError):
            backend.read_telemetry(99)

    def test_shutdown_is_safe(self):
        backend = SimulatedBackend()
        backend.shutdown()  # should not raise


# ──────────────────────────────────────────────
# Noise mode
# ──────────────────────────────────────────────


class TestSimulatedBackendNoise:
    def test_noise_mode_produces_varying_readings(self):
        """Multiple reads should produce different values when noise=True."""
        cfg = SimulatedConfig(noise=True)
        backend = SimulatedBackend(config=cfg)

        readings = [backend.read_telemetry(0).temperature_c for _ in range(20)]
        unique_readings = set(readings)
        # With noise, we should get at least a few distinct values over 20 reads
        assert len(unique_readings) > 1, "Noise mode should produce varying readings"

    def test_no_noise_mode_produces_deterministic_readings(self):
        """Reads should produce the same values when noise=False."""
        cfg = SimulatedConfig(noise=False)
        backend = SimulatedBackend(config=cfg)

        readings = [backend.read_telemetry(0).temperature_c for _ in range(10)]
        assert len(set(readings)) == 1, "No-noise mode should be deterministic"

    def test_no_noise_values_still_in_range(self):
        cfg = SimulatedConfig(noise=False)
        backend = SimulatedBackend(config=cfg)
        telem = backend.read_telemetry(0)
        assert 20.0 <= telem.temperature_c <= 95.0
        assert 0.0 <= telem.gpu_utilization_percent <= 100.0
