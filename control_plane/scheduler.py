import asyncio
from typing import Optional


class FIFOScheduler:
    def __init__(self, maxsize: int = 0):
        self.queue = asyncio.Queue(maxsize=maxsize)

    async def submit_job(self, job_id: str) -> bool:
        """
        Submits a job to the FIFO queue.
        Returns True if successful, False if the queue is full.
        """
        try:
            self.queue.put_nowait(job_id)
            return True
        except asyncio.QueueFull:
            return False

    async def get_next_job(self) -> Optional[str]:
        """
        Pops the next job from the FIFO queue.
        Returns None if the queue is empty.
        """
        try:
            return self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def qsize(self) -> int:
        return self.queue.qsize()
