"""Prometheus metrics exporter for the Worker Agent.

Defines all Prometheus gauges for system and GPU telemetry and provides
an ``update()`` method that sets gauge values from HAL dataclasses.
"""

from prometheus_client import CollectorRegistry, Gauge, REGISTRY

from worker_agent.hal.base import GpuDevice, SystemTelemetry


class WorkerMetrics:
    """Manages Prometheus gauges for a single worker node.

    Args:
        registry: Prometheus ``CollectorRegistry``. Uses the global
            default registry when ``None`` (production). Pass a fresh
            registry in tests to avoid state leakage.
    """

    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or REGISTRY

        # ── System-level gauges ───────────────
        self.cpu_util = Gauge(
            "worker_cpu_utilization_percent",
            "CPU utilization percentage",
            ["node_id"],
            registry=self._registry,
        )
        self.ram_util = Gauge(
            "worker_ram_utilization_percent",
            "RAM utilization percentage",
            ["node_id"],
            registry=self._registry,
        )
        self.ram_available = Gauge(
            "worker_ram_available_mb",
            "Available RAM in MB",
            ["node_id"],
            registry=self._registry,
        )
        self.active_jobs = Gauge(
            "worker_active_jobs",
            "Number of currently active jobs",
            ["node_id"],
            registry=self._registry,
        )

        # ── GPU gauges ────────────────────────
        gpu_labels = ["node_id", "gpu_index", "vendor", "model"]

        self.gpu_temp = Gauge(
            "worker_gpu_temperature_c",
            "GPU edge temperature in Celsius",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_temp_hotspot = Gauge(
            "worker_gpu_temperature_hotspot_c",
            "GPU hotspot temperature in Celsius",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_fan = Gauge(
            "worker_gpu_fan_speed_percent",
            "GPU fan speed percentage",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_power_draw = Gauge(
            "worker_gpu_power_draw_w",
            "GPU power draw in watts",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_power_limit = Gauge(
            "worker_gpu_power_limit_w",
            "GPU power limit in watts",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_util = Gauge(
            "worker_gpu_utilization_percent",
            "GPU core utilization percentage",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_mem_util = Gauge(
            "worker_gpu_memory_utilization_percent",
            "GPU memory utilization percentage",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_vram_total = Gauge(
            "worker_gpu_vram_total_mb",
            "Total GPU VRAM in MB",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_vram_free = Gauge(
            "worker_gpu_vram_free_mb",
            "Free GPU VRAM in MB",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_vram_used = Gauge(
            "worker_gpu_vram_used_mb",
            "Used GPU VRAM in MB",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_clock_core = Gauge(
            "worker_gpu_clock_core_mhz",
            "GPU core clock in MHz",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_clock_memory = Gauge(
            "worker_gpu_clock_memory_mhz",
            "GPU memory clock in MHz",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_encoder_util = Gauge(
            "worker_gpu_encoder_utilization_percent",
            "GPU encoder utilization percentage",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_decoder_util = Gauge(
            "worker_gpu_decoder_utilization_percent",
            "GPU decoder utilization percentage",
            gpu_labels,
            registry=self._registry,
        )
        self.gpu_pcie_bw = Gauge(
            "worker_gpu_pcie_bandwidth_percent",
            "GPU PCIe bandwidth utilization percentage",
            gpu_labels,
            registry=self._registry,
        )

    def update(
        self,
        node_id: str,
        telemetry: SystemTelemetry,
        gpu_devices: list[GpuDevice],
        active_job_count: int,
    ) -> None:
        """Set all gauge values from the latest telemetry snapshot.

        This is designed to be called once per heartbeat cycle so
        that metrics stay in sync with what the gRPC heartbeat sends.

        Args:
            node_id: Unique identifier for this worker node.
            telemetry: Latest SystemTelemetry from the HAL.
            gpu_devices: Static GPU device info (for labels).
            active_job_count: Current number of active jobs.
        """
        # ── System ────────────────────────────
        self.cpu_util.labels(node_id=node_id).set(
            telemetry.cpu_utilization_percent
        )
        self.ram_util.labels(node_id=node_id).set(
            telemetry.ram_utilization_percent
        )
        self.ram_available.labels(node_id=node_id).set(
            telemetry.ram_available_mb
        )
        self.active_jobs.labels(node_id=node_id).set(active_job_count)

        # ── GPUs ──────────────────────────────
        # Build a lookup from gpu index → static device info for labels
        device_map = {d.index: d for d in gpu_devices}

        for gpu_telem in telemetry.gpus:
            device = device_map.get(gpu_telem.index)
            labels = {
                "node_id": node_id,
                "gpu_index": str(gpu_telem.index),
                "vendor": device.vendor if device else "unknown",
                "model": device.model if device else "unknown",
            }

            self.gpu_temp.labels(**labels).set(gpu_telem.temperature_c)
            self.gpu_temp_hotspot.labels(**labels).set(
                gpu_telem.temperature_hotspot_c
            )
            self.gpu_fan.labels(**labels).set(gpu_telem.fan_speed_percent)
            self.gpu_power_draw.labels(**labels).set(gpu_telem.power_draw_w)
            self.gpu_power_limit.labels(**labels).set(gpu_telem.power_limit_w)
            self.gpu_util.labels(**labels).set(
                gpu_telem.gpu_utilization_percent
            )
            self.gpu_mem_util.labels(**labels).set(
                gpu_telem.memory_utilization_percent
            )
            self.gpu_clock_core.labels(**labels).set(gpu_telem.clock_core_mhz)
            self.gpu_clock_memory.labels(**labels).set(
                gpu_telem.clock_memory_mhz
            )
            self.gpu_encoder_util.labels(**labels).set(
                gpu_telem.encoder_utilization_percent
            )
            self.gpu_decoder_util.labels(**labels).set(
                gpu_telem.decoder_utilization_percent
            )
            self.gpu_pcie_bw.labels(**labels).set(
                gpu_telem.pcie_bandwidth_percent
            )

            # VRAM: combine static total from device + live free/used
            vram_total = device.total_vram_mb if device else 0
            self.gpu_vram_total.labels(**labels).set(vram_total)
            self.gpu_vram_free.labels(**labels).set(gpu_telem.free_vram_mb)
            self.gpu_vram_used.labels(**labels).set(gpu_telem.used_vram_mb)
