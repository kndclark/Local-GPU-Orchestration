import pytest
from control_plane.scheduler import FIFOScheduler


@pytest.mark.asyncio
async def test_scheduler_nominal():
    scheduler = FIFOScheduler(maxsize=10)

    # Submit jobs
    await scheduler.submit_job("job-1")
    await scheduler.submit_job("job-2")

    assert scheduler.qsize() == 2

    # Get jobs
    job1 = await scheduler.get_next_job()
    job2 = await scheduler.get_next_job()

    assert job1 == "job-1"
    assert job2 == "job-2"
    assert scheduler.qsize() == 0


@pytest.mark.asyncio
async def test_scheduler_empty_queue():
    scheduler = FIFOScheduler()

    job = await scheduler.get_next_job()
    assert job is None


@pytest.mark.asyncio
async def test_scheduler_full_queue():
    scheduler = FIFOScheduler(maxsize=2)

    assert await scheduler.submit_job("job-1") is True
    assert await scheduler.submit_job("job-2") is True

    # Third job should fail to submit (queue full)
    assert await scheduler.submit_job("job-3") is False
    assert scheduler.qsize() == 2
