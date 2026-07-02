import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from control_plane.database.models import GangJob, GangJobParticipant, Job, Node
from control_plane.metrics import STALE_NODE_SECONDS


@dataclass
class GangFormationResult:
    """Outcome of a gang-formation attempt.

    outcome is one of:
      - "OK": a viable gang was formed (worker_nodes + controller_node set)
      - "NO_NODES": no eligible nodes are available
      - "SINGLE_NODE_SUFFICIENT": exactly one eligible node and it meets min alone
      - "INSUFFICIENT_VRAM": eligible nodes' combined VRAM is below min
      - "CONTROLLER_NOT_ELIGIBLE": requested controller_node_id is not eligible
    """

    outcome: str
    worker_nodes: list[Node] = field(default_factory=list)
    controller_node: Optional[Node] = None
    detail: str = ""


class GangScheduler:
    """Selects a set of nodes whose combined free VRAM meets a requirement.

    Selection is workload-agnostic. It reuses the same thermal and CUDA-capability
    filters as the single-node HardwareAwareScheduler, plus a heartbeat-staleness
    filter so dead nodes are never chosen for a gang.
    """

    def __init__(self):
        self.max_gpu_temp = float(os.environ.get("MAX_GPU_TEMP_C", "80.0"))
        self.staleness_seconds = float(STALE_NODE_SECONDS)

    def _node_free_vram(self, node: Node) -> int:
        """Sum of usable free VRAM across a node's GPUs (ignores -1 sentinels)."""
        return sum(g.free_vram_mb for g in node.gpus if g.free_vram_mb > 0)

    def _is_eligible(self, node: Node, requires_cuda: bool, cutoff: datetime) -> bool:
        # Staleness: last_heartbeat may be naive (SQLite) — treat as UTC.
        hb = node.last_heartbeat
        if hb is not None:
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            if hb < cutoff:
                return False

        if not node.gpus:
            return False

        # Thermal: exclude if any GPU is at/over the limit.
        for gpu in node.gpus:
            if max(gpu.temperature_c, gpu.temperature_hotspot_c) >= self.max_gpu_temp:
                return False

        # Capability: CUDA jobs require at least one NVIDIA GPU.
        if requires_cuda:
            if not any(g.vendor.upper() == "NVIDIA" for g in node.gpus):
                return False

        # Must contribute usable VRAM.
        return self._node_free_vram(node) > 0

    def find_gang(
        self,
        min_vram_mb: int,
        requires_cuda: bool,
        db: Session,
        controller_node_id: Optional[str] = None,
    ) -> GangFormationResult:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.staleness_seconds)

        candidates = [
            n
            for n in db.query(Node).all()
            if self._is_eligible(n, requires_cuda, cutoff)
        ]

        if not candidates:
            return GangFormationResult(
                outcome="NO_NODES",
                detail="No healthy, eligible nodes are available.",
            )

        # A gang needs at least two nodes. With one eligible node, either it can
        # run the workload solo (submit as a single-node job) or it simply lacks
        # the VRAM.
        if len(candidates) == 1:
            only = candidates[0]
            only_vram = self._node_free_vram(only)
            if only_vram >= min_vram_mb:
                return GangFormationResult(
                    outcome="SINGLE_NODE_SUFFICIENT",
                    detail=(
                        f"Only node '{only.node_id}' is eligible and it has "
                        f"{only_vram} MB free VRAM (>= {min_vram_mb} MB requested). "
                        f"Submit this as a single-node job via POST /api/v1/jobs."
                    ),
                )
            return GangFormationResult(
                outcome="INSUFFICIENT_VRAM",
                detail=(
                    f"Only node '{only.node_id}' is eligible with {only_vram} MB "
                    f"free VRAM; {min_vram_mb} MB requested."
                ),
            )

        # Choose controller.
        if controller_node_id is not None:
            controller = next(
                (n for n in candidates if n.node_id == controller_node_id), None
            )
            if controller is None:
                return GangFormationResult(
                    outcome="CONTROLLER_NOT_ELIGIBLE",
                    detail=(
                        f"Requested controller '{controller_node_id}' is not among "
                        f"the eligible nodes (offline, too hot, wrong vendor, or no "
                        f"free VRAM)."
                    ),
                )
        else:
            controller = max(candidates, key=self._node_free_vram)

        # Greedily add the highest-VRAM workers until the pool meets the minimum,
        # always including at least one worker so the gang has >= 2 nodes.
        worker_pool = sorted(
            (n for n in candidates if n.node_id != controller.node_id),
            key=self._node_free_vram,
            reverse=True,
        )

        total = self._node_free_vram(controller)
        selected_workers: list[Node] = []
        for worker in worker_pool:
            if total >= min_vram_mb and selected_workers:
                break
            selected_workers.append(worker)
            total += self._node_free_vram(worker)

        if total < min_vram_mb:
            return GangFormationResult(
                outcome="INSUFFICIENT_VRAM",
                detail=(
                    f"Combined free VRAM across eligible nodes is {total} MB; "
                    f"{min_vram_mb} MB requested."
                ),
            )

        return GangFormationResult(
            outcome="OK",
            worker_nodes=selected_workers,
            controller_node=controller,
        )


def _worker_participants(gang: GangJob) -> list[GangJobParticipant]:
    return [p for p in gang.participants if p.role == "worker"]


def _controller_participant(gang: GangJob) -> Optional[GangJobParticipant]:
    return next((p for p in gang.participants if p.role == "controller"), None)


async def run_gang_dispatch_cycle(db: Session, scheduler) -> None:
    """Advance every gang job by one step.

    FORMING gangs whose workers have all reported an endpoint get their
    controller job created and dispatched; a failed worker fails the gang.
    RUNNING gangs adopt their controller job's terminal status.
    """
    for gang in db.query(GangJob).filter(GangJob.status == "FORMING").all():
        workers = _worker_participants(gang)
        worker_jobs = [
            db.query(Job).filter(Job.job_id == p.job_id).first() for p in workers
        ]

        if any(j is not None and j.status == "FAILED" for j in worker_jobs):
            gang.status = "FAILED"
            db.commit()
            continue

        if not workers or not all(p.endpoint for p in workers):
            continue

        endpoints = ",".join(p.endpoint for p in workers)
        controller_args = json.loads(gang.controller_args) + [
            gang.controller_endpoints_flag,
            endpoints,
        ]
        controller = _controller_participant(gang)

        controller_job_id = str(uuid.uuid4())
        db.add(
            Job(
                job_id=controller_job_id,
                workload_type=gang.controller_workload_type,
                args=json.dumps(controller_args),
                env_vars="{}",
                requires_cuda=gang.requires_cuda,
                status="PENDING",
                assigned_node_id=controller.node_id,
            )
        )
        controller.job_id = controller_job_id
        gang.status = "RUNNING"
        db.commit()
        await scheduler.submit_job(controller_job_id)

    for gang in db.query(GangJob).filter(GangJob.status == "RUNNING").all():
        controller = _controller_participant(gang)
        if controller is None or not controller.job_id:
            continue
        controller_job = db.query(Job).filter(Job.job_id == controller.job_id).first()
        if controller_job is None:
            continue
        if controller_job.status in ("COMPLETED", "FAILED"):
            gang.status = controller_job.status
            db.commit()
