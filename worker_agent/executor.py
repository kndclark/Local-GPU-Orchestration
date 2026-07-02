import asyncio
import logging
import os
import shutil
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


class JobExecutor:
    async def execute_job(
        self, job_id: str, executable: str, args: list[str], env_vars: dict[str, str]
    ) -> tuple[bool, str]:
        """
        Executes a local command via subprocess.
        Returns (success: bool, error_message: str)
        """
        env = os.environ.copy()
        env.update(env_vars)

        if not os.path.isabs(executable) and shutil.which(executable) is None:
            msg = f"Executable not found on PATH: '{executable}'"
            logger.error(f"Job {job_id} failed: {msg}")
            return False, msg

        logger.info(f"Executing job {job_id}: {executable} {' '.join(args)}")

        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"Job {job_id} completed successfully.")
                return True, ""
            else:
                err_msg = stderr.decode("utf-8").strip()
                logger.error(
                    f"Job {job_id} failed with code {process.returncode}: {err_msg}"
                )
                return False, err_msg
        except Exception as e:
            logger.exception(f"Job {job_id} encountered exception: {e}")
            return False, str(e)

    async def execute_server_job(
        self,
        job_id: str,
        executable: str,
        args: list[str],
        env_vars: dict[str, str],
        ready_signal: str,
        on_ready: Callable[[], Awaitable[None]],
    ) -> tuple[bool, str]:
        """Run a long-lived server process, awaiting on_ready once a line
        containing ready_signal appears, then wait for exit.

        Returns (success, error_message). Workload-agnostic: ready_signal and
        the process it runs are supplied by the caller.
        """
        env = os.environ.copy()
        env.update(env_vars)

        if not os.path.isabs(executable) and shutil.which(executable) is None:
            msg = f"Executable not found on PATH: '{executable}'"
            logger.error(f"Job {job_id} failed: {msg}")
            return False, msg

        logger.info(f"Starting server job {job_id}: {executable} {' '.join(args)}")

        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except Exception as e:
            logger.exception(f"Server job {job_id} failed to start: {e}")
            return False, str(e)

        ready_fired = False
        output_lines: list[str] = []
        async for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            output_lines.append(line)
            if not ready_fired and ready_signal and ready_signal in line:
                ready_fired = True
                logger.info(f"Server job {job_id} is ready.")
                try:
                    await on_ready()
                except Exception as e:
                    logger.error(f"Server job {job_id} on_ready callback failed: {e}")

        await process.wait()

        if process.returncode == 0:
            logger.info(f"Server job {job_id} exited cleanly.")
            return True, ""
        err_msg = "\n".join(output_lines[-20:])
        logger.error(
            f"Server job {job_id} exited with code {process.returncode}: {err_msg}"
        )
        return False, err_msg
