"""Tests for worker_agent.metrics — Prometheus gauge registration and updates."""

import pytest
from prometheus_client import CollectorRegistry

from worker_agent.hal.base import (
    GpuDevice,
    GpuTelemetry,
    SystemTelemetry,
)
from worker_agent.metrics import WorkerMetrics


@pytest.fixture
def registry():
    """Fresh Prometheus registry so tests don't leak state."""
    return CollectorRegistry()


@pytest.fixture
def metrics(registry):
    return WorkerMetrics(registry=registry)


@pytest.fixture
def gpu_devices():
    return [
        GpuDevice(
            index=0,
            vendor="NVIDIA",
            model="RTX 4090",
            driver_version="555.42",
            total_vram_mb=24576,
        ),
        GpuDevice(
            index=1,
            vendor="AMD",
            model="RX 7600",
            driver_version="6.1.0",
            total_vram_mb=8192,
        ),
    ]


@pytest.fixture
def system_telemetry():
    return SystemTelemetry(
        gpus=[
            GpuTelemetry(
                index=0,
                free_vram_mb=20000,
                used_vram_mb=4576,
                temperature_c=65.0,
                temperature_hotspot_c=78.0,
                fan_speed_percent=45.0,
                power_draw_w=250.0,
                power_limit_w=450.0,
                gpu_utilization_percent=82.0,
                memory_utilization_percent=18.6,
                encoder_utilization_percent=5.0,
                decoder_utilization_percent=3.0,
                clock_core_mhz=2520,
                clock_memory_mhz=1313,
                clock_core_max_mhz=2520,
                clock_memory_max_mhz=1313,
                pcie_gen=4,
                pcie_width=16,
                pcie_bandwidth_percent=12.5,
            ),
            GpuTelemetry(
                index=1,
                free_vram_mb=7000,
                used_vram_mb=1192,
                temperature_c=55.0,
                temperature_hotspot_c=60.0,
                fan_speed_percent=30.0,
                power_draw_w=120.0,
                power_limit_w=165.0,
                gpu_utilization_percent=40.0,
                memory_utilization_percent=14.5,
                encoder_utilization_percent=0.0,
                decoder_utilization_percent=0.0,
                clock_core_mhz=2200,
                clock_memory_mhz=2250,
                clock_core_max_mhz=2700,
                clock_memory_max_mhz=2250,
                pcie_gen=4,
                pcie_width=8,
                pcie_bandwidth_percent=5.0,
            ),
        ],
        cpu_utilization_percent=35.0,
        ram_utilization_percent=60.0,
        ram_available_mb=12800,
    )


# ──────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────


class TestGaugeRegistration:
    """Verify all expected gauges are registered."""

    def test_system_gauges_registered(self, metrics, registry):
        families = {m.name for m in registry.collect()}
        for name in [
            "worker_cpu_utilization_percent",
            "worker_ram_utilization_percent",
            "worker_ram_available_mb",
            "worker_active_jobs",
        ]:
            assert name in families, f"Missing system gauge: {name}"

    def test_gpu_gauges_registered(self, metrics, registry):
        families = {m.name for m in registry.collect()}
        gpu_gauges = [
            "worker_gpu_temperature_c",
            "worker_gpu_temperature_hotspot_c",
            "worker_gpu_fan_speed_percent",
            "worker_gpu_power_draw_w",
            "worker_gpu_power_limit_w",
            "worker_gpu_utilization_percent",
            "worker_gpu_memory_utilization_percent",
            "worker_gpu_vram_total_mb",
            "worker_gpu_vram_free_mb",
            "worker_gpu_vram_used_mb",
            "worker_gpu_clock_core_mhz",
            "worker_gpu_clock_memory_mhz",
            "worker_gpu_encoder_utilization_percent",
            "worker_gpu_decoder_utilization_percent",
            "worker_gpu_pcie_bandwidth_percent",
        ]
        for name in gpu_gauges:
            assert name in families, f"Missing GPU gauge: {name}"


# ──────────────────────────────────────────────
# update_metrics
# ──────────────────────────────────────────────


class TestUpdateMetrics:
    """Verify update_metrics sets gauge values correctly."""

    def test_system_metrics_updated(
        self, metrics, registry, gpu_devices, system_telemetry
    ):
        metrics.update(
            node_id="test-node",
            telemetry=system_telemetry,
            gpu_devices=gpu_devices,
            active_job_count=3,
        )

        # System-level gauges
        val = registry.get_sample_value(
            "worker_cpu_utilization_percent",
            {"node_id": "test-node"},
        )
        assert val == 35.0

        val = registry.get_sample_value(
            "worker_ram_utilization_percent",
            {"node_id": "test-node"},
        )
        assert val == 60.0

        val = registry.get_sample_value(
            "worker_ram_available_mb",
            {"node_id": "test-node"},
        )
        assert val == 12800

        val = registry.get_sample_value(
            "worker_active_jobs",
            {"node_id": "test-node"},
        )
        assert val == 3

    def test_gpu_metrics_labeled_correctly(
        self, metrics, registry, gpu_devices, system_telemetry
    ):
        metrics.update(
            node_id="test-node",
            telemetry=system_telemetry,
            gpu_devices=gpu_devices,
            active_job_count=0,
        )

        # GPU 0 (NVIDIA RTX 4090)
        labels_0 = {
            "node_id": "test-node",
            "gpu_index": "0",
            "vendor": "NVIDIA",
            "model": "RTX 4090",
        }
        assert registry.get_sample_value("worker_gpu_temperature_c", labels_0) == 65.0
        assert registry.get_sample_value("worker_gpu_power_draw_w", labels_0) == 250.0
        assert registry.get_sample_value("worker_gpu_vram_total_mb", labels_0) == 24576
        assert registry.get_sample_value("worker_gpu_vram_free_mb", labels_0) == 20000
        assert (
            registry.get_sample_value("worker_gpu_utilization_percent", labels_0)
            == 82.0
        )

        # GPU 1 (AMD RX 7600)
        labels_1 = {
            "node_id": "test-node",
            "gpu_index": "1",
            "vendor": "AMD",
            "model": "RX 7600",
        }
        assert registry.get_sample_value("worker_gpu_temperature_c", labels_1) == 55.0
        assert registry.get_sample_value("worker_gpu_power_draw_w", labels_1) == 120.0
        assert registry.get_sample_value("worker_gpu_vram_total_mb", labels_1) == 8192

    def test_update_overwrites_previous_values(
        self, metrics, registry, gpu_devices, system_telemetry
    ):
        """Calling update twice should overwrite, not accumulate."""
        metrics.update(
            node_id="test-node",
            telemetry=system_telemetry,
            gpu_devices=gpu_devices,
            active_job_count=1,
        )

        # Now update with different values
        updated_telem = SystemTelemetry(
            gpus=[
                GpuTelemetry(index=0, temperature_c=90.0),
                GpuTelemetry(index=1, temperature_c=70.0),
            ],
            cpu_utilization_percent=95.0,
            ram_utilization_percent=80.0,
            ram_available_mb=6400,
        )
        metrics.update(
            node_id="test-node",
            telemetry=updated_telem,
            gpu_devices=gpu_devices,
            active_job_count=5,
        )

        assert (
            registry.get_sample_value(
                "worker_cpu_utilization_percent",
                {"node_id": "test-node"},
            )
            == 95.0
        )

        labels_0 = {
            "node_id": "test-node",
            "gpu_index": "0",
            "vendor": "NVIDIA",
            "model": "RTX 4090",
        }
        assert registry.get_sample_value("worker_gpu_temperature_c", labels_0) == 90.0

    def test_active_jobs_tracks_correctly(self, metrics, registry, gpu_devices):
        """Active jobs gauge should reflect exact count each update."""
        telem = SystemTelemetry(cpu_utilization_percent=10.0)

        metrics.update(
            node_id="node-a",
            telemetry=telem,
            gpu_devices=[],
            active_job_count=0,
        )
        assert (
            registry.get_sample_value("worker_active_jobs", {"node_id": "node-a"}) == 0
        )

        metrics.update(
            node_id="node-a",
            telemetry=telem,
            gpu_devices=[],
            active_job_count=7,
        )
        assert (
            registry.get_sample_value("worker_active_jobs", {"node_id": "node-a"}) == 7
        )
