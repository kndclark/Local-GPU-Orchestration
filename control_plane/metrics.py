"""Prometheus metrics for the Control Plane.

Exposes cluster-level and per-node gauges derived from the database.
Call ``refresh()`` periodically (e.g. every 15 s from a background task)
to keep gauges up-to-date.
"""

from datetime import datetime, timezone
from collections import Counter

from prometheus_client import CollectorRegistry, Gauge, REGISTRY
from sqlalchemy.orm import Session

from control_plane.database.models import Node, Gpu, Job


class ControlPlaneMetrics:
    """Manages Prometheus gauges for cluster-wide telemetry.

    Args:
        registry: Prometheus ``CollectorRegistry``. Uses the global
            default registry when ``None`` (production). Pass a fresh
            registry in tests to avoid state leakage.
    """

    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or REGISTRY

        # ── Cluster-level gauges ──────────────
        self.nodes_total = Gauge(
            "cluster_nodes_total",
            "Total number of registered nodes",
            registry=self._registry,
        )
        self.gpus_total = Gauge(
            "cluster_gpus_total",
            "Total number of registered GPUs across all nodes",
            registry=self._registry,
        )
        self.gpus_by_vendor = Gauge(
            "cluster_gpus_by_vendor",
            "Number of GPUs broken down by vendor",
            ["vendor"],
            registry=self._registry,
        )
        self.vram_total = Gauge(
            "cluster_vram_total_mb",
            "Total VRAM across all GPUs in MB",
            registry=self._registry,
        )
        self.vram_free = Gauge(
            "cluster_vram_free_mb",
            "Total free VRAM across all GPUs in MB",
            registry=self._registry,
        )
        self.jobs_total = Gauge(
            "cluster_jobs_total",
            "Number of jobs by status",
            ["status"],
            registry=self._registry,
        )

        # ── Per-node gauges ───────────────────
        node_labels = ["node_id", "hostname"]

        self.node_cpu_util = Gauge(
            "node_cpu_utilization_percent",
            "CPU utilization of a node",
            node_labels,
            registry=self._registry,
        )
        self.node_ram_util = Gauge(
            "node_ram_utilization_percent",
            "RAM utilization of a node",
            node_labels,
            registry=self._registry,
        )
        self.node_gpu_count = Gauge(
            "node_gpu_count",
            "Number of GPUs on a node",
            node_labels,
            registry=self._registry,
        )
        self.node_heartbeat_age = Gauge(
            "node_last_heartbeat_age_seconds",
            "Seconds since the last heartbeat from a node",
            node_labels,
            registry=self._registry,
        )

    def refresh(self, db: Session) -> None:
        """Query the database and update all Prometheus gauges.

        Args:
            db: An active SQLAlchemy session.
        """
        now = datetime.now(timezone.utc)

        # ── Nodes ─────────────────────────────
        nodes = db.query(Node).all()
        self.nodes_total.set(len(nodes))

        for node in nodes:
            labels = {"node_id": node.node_id, "hostname": node.hostname}
            self.node_cpu_util.labels(**labels).set(
                node.cpu_utilization_percent
            )
            self.node_ram_util.labels(**labels).set(
                node.ram_utilization_percent
            )
            self.node_gpu_count.labels(**labels).set(len(node.gpus))

            # Heartbeat age
            if node.last_heartbeat:
                # Ensure the heartbeat is tz-aware
                hb = node.last_heartbeat
                if hb.tzinfo is None:
                    hb = hb.replace(tzinfo=timezone.utc)
                age = (now - hb).total_seconds()
            else:
                age = -1.0
            self.node_heartbeat_age.labels(**labels).set(age)

        # ── GPUs ──────────────────────────────
        gpus = db.query(Gpu).all()
        self.gpus_total.set(len(gpus))

        total_vram = sum(g.total_vram_mb for g in gpus)
        free_vram = sum(
            g.free_vram_mb for g in gpus if g.free_vram_mb >= 0
        )
        self.vram_total.set(total_vram)
        self.vram_free.set(free_vram)

        # GPUs by vendor
        vendor_counts: Counter = Counter(g.vendor for g in gpus)
        for vendor, count in vendor_counts.items():
            self.gpus_by_vendor.labels(vendor=vendor).set(count)

        # ── Jobs ──────────────────────────────
        jobs = db.query(Job).all()
        status_counts: Counter = Counter(j.status for j in jobs)
        for status in ["PENDING", "RUNNING", "COMPLETED", "FAILED"]:
            self.jobs_total.labels(status=status).set(
                status_counts.get(status, 0)
            )
