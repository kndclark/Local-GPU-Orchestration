import asyncio
import logging
import os

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
