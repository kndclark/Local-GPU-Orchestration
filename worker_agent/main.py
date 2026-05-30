import asyncio
import logging
import platform
import sys

from worker_agent.config import WorkerSettings
from worker_agent.client import WorkerClient
from worker_agent.hal.manager import HardwareManager
from worker_agent.executor import JobExecutor

logger = logging.getLogger(__name__)


class AgentDaemon:
    """Main lifecycle manager for the worker agent."""

    def __init__(self, settings: WorkerSettings | None = None):
        self.settings = settings or WorkerSettings()
        self.client = WorkerClient(
            node_id=self.settings.node_id,
            server_address=self.settings.orchestrator_url,
        )
        self.hw_manager = HardwareManager()
        self.executor = JobExecutor()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self.active_jobs: list[str] = []

    async def start(self):
        """Start the daemon and block until stopped."""
        logger.info(f"Starting Worker Agent (Node ID: {self.settings.node_id})")
        self._running = True

        # 1. Initialize hardware
        self.hw_manager.detect()
        gpus = self.hw_manager.get_gpu_devices()

        # 2. Connect to control plane
        self.client.connect()

        # 3. Register node
        success = await self.client.register_node(
            hostname=platform.node(),
            gpus=gpus,
            supported_workloads=self.settings.supported_workloads,
            os_name=platform.system().lower(),
            os_version=platform.release(),
            cpu_count=0,  # Could grab from psutil if needed at registration time
            cpu_model=platform.processor(),
            total_ram_mb=0,  # Handled in heartbeats via hw_manager
        )
        if not success:
            logger.error("Failed to register with orchestrator. Exiting.")
            return

        logger.info("Successfully registered with orchestrator.")

        # 4. Spawn background loops
        self._tasks = [
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._job_poll_loop()),
        ]

        # 5. Wait for shutdown
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self):
        """Gracefully stop the daemon."""
        logger.info("Stopping Worker Agent...")
        self._running = False
        for task in self._tasks:
            task.cancel()

        await self.client.close()
        self.hw_manager.shutdown()
        logger.info("Worker Agent stopped.")

    async def _heartbeat_loop(self):
        """Periodically send system and GPU telemetry."""
        while self._running:
            try:
                telem = self.hw_manager.get_system_telemetry()
                await self.client.send_heartbeat(
                    telemetry=telem, active_jobs=self.active_jobs
                )
                logger.info(
                    f"Sent heartbeat: {len(telem.gpus)} GPUs, {telem.cpu_utilization_percent:.1f}% CPU, {len(self.active_jobs)} jobs"
                )
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")

            await asyncio.sleep(self.settings.heartbeat_interval_seconds)

    async def _job_poll_loop(self):
        """Periodically poll for new jobs and execute them."""
        while self._running:
            try:
                job = await self.client.request_job()
                if job:
                    logger.info(f"Received job: {job['job_id']}")
                    # For Phase 2, we execute jobs sequentially (blocking this loop).
                    # A true production agent would dispatch to a background worker pool.

                    # Ensure we're using the right executable context
                    executable = sys.executable
                    if job["workload_type"] != "python":
                        # If not python, the workload_type might be the executable itself
                        # e.g., 'ffmpeg'
                        executable = job["workload_type"]

                    self.active_jobs.append(job["job_id"])
                    try:
                        success, error_msg = await self.executor.execute_job(
                            job_id=job["job_id"],
                            executable=executable,
                            args=job["args"],
                            env_vars=job["env_vars"],
                        )
                    finally:
                        self.active_jobs.remove(job["job_id"])

                    status = "COMPLETED" if success else "FAILED"
                    await self.client.update_job_status(
                        job_id=job["job_id"],
                        status=status,
                        error_message=error_msg,
                    )
                    logger.info(f"Job {job['job_id']} finished with status {status}")
            except Exception as e:
                logger.error(f"Error in job poll loop: {e}")

            await asyncio.sleep(self.settings.job_poll_interval_seconds)


async def _main():
    logging.basicConfig(level=logging.INFO)
    daemon = AgentDaemon()
    try:
        await daemon.start()
    except KeyboardInterrupt:
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(_main())
