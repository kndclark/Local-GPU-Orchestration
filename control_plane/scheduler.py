import os
from typing import Optional
from collections import deque
from sqlalchemy.orm import Session
from control_plane.database.models import Job, Node


class HardwareAwareScheduler:
    def __init__(self):
        self.pending_jobs: deque[str] = deque()
        self.max_gpu_temp = float(os.environ.get("MAX_GPU_TEMP_C", "80.0"))
        self._initialized = False

    def initialize(self, db: Session):
        """Loads existing PENDING jobs from the database on startup."""
        if not self._initialized:
            pending_jobs = (
                db.query(Job)
                .filter(Job.status == "PENDING")
                .order_by(Job.created_at)
                .all()
            )
            for job in pending_jobs:
                self.pending_jobs.append(job.job_id)
            self._initialized = True

    async def submit_job(self, job_id: str) -> bool:
        """
        Submits a job to the in-memory pending queue.
        Returns True if successful.
        """
        self.pending_jobs.append(job_id)
        return True

    async def get_next_job_for_node(self, node_id: str, db: Session) -> Optional[str]:
        """
        Finds the next suitable job for the given node.
        Returns the job_id if found, otherwise None.
        """
        if not self._initialized:
            self.initialize(db)

        node = db.query(Node).filter(Node.node_id == node_id).first()
        if not node:
            return None

        # Thermal check
        for gpu in node.gpus:
            temp = max(gpu.temperature_c, gpu.temperature_hotspot_c)
            if temp >= self.max_gpu_temp:
                return None

        # Capability check
        has_nvidia = any(gpu.vendor.upper() == "NVIDIA" for gpu in node.gpus)

        # Find first matching job
        for job_id in list(self.pending_jobs):
            job = db.query(Job).filter(Job.job_id == job_id).first()

            # Clean up missing or non-pending jobs (e.g. if modified elsewhere)
            if not job or job.status != "PENDING":
                self.pending_jobs.remove(job_id)
                continue

            # Respect node pinning: gang worker/controller jobs are pre-assigned
            # to a specific node and must only dispatch there.
            if job.assigned_node_id and job.assigned_node_id != node_id:
                continue

            if job.requires_cuda and not has_nvidia:
                continue

            # Match found! Remove from queue and return
            self.pending_jobs.remove(job_id)
            return job_id

        return None
