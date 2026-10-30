"""Drive scheduled job dispatch directly from ``AppTestHarness`` tests.

Dispatching by hand, rather than through ``trigger_due_jobs()``, lets a test hold one occurrence
open and fire the next while it is still running. These helpers are separate steps so each test
keeps its own synchronization (event clears, wait gates, executor wrapping) visible between them.
"""

import asyncio

from hassette.core.scheduler_service import SchedulerService
from hassette.scheduler.classes import Job
from hassette.testing import AppTestHarness
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS


def scheduler_service_for(harness: AppTestHarness) -> SchedulerService:
    """Return the harness's scheduler service, for tests that need more than the helpers below."""
    inner = harness._harness
    assert inner is not None, "Harness is not running; use it inside its async with block"
    service = inner.hassette._scheduler_service
    assert service is not None, "Harness has no scheduler service"
    return service


async def get_job_by_name(harness: AppTestHarness, name: str) -> Job:
    """Return the live job called ``name``, failing the test if there is none."""
    jobs = await scheduler_service_for(harness).get_all_jobs()
    job = next((j for j in jobs if j.name == name), None)
    assert job is not None, f"No live job named {name!r}"
    return job


async def freeze_and_dispatch(harness: AppTestHarness, job: Job) -> asyncio.Task[None]:
    """Freeze time just past the job's next run and dispatch it as a task.

    Nothing here yields to the event loop, so the task has not started when this returns. The
    caller decides how to wait for it to reach a given point.
    """
    assert job.next_run is not None, f"Job {job.name!r} has no next run to dispatch"
    harness.freeze_time(job.next_run.add(seconds=1))
    return asyncio.create_task(scheduler_service_for(harness).dispatch_and_log(job))


async def start_overrun(
    harness: AppTestHarness, name: str, started: asyncio.Event
) -> tuple[Job, asyncio.Task[None], Job]:
    """Fire the job called ``name``, wait until it is running, then look up its next occurrence.

    ``started`` is the event the job's handler sets on entry. Returns the job, the task still
    dispatching it, and the next occurrence. The test then does its own setup before firing that
    occurrence with ``freeze_and_dispatch()``.
    """
    job = await get_job_by_name(harness, name)
    dispatch = await freeze_and_dispatch(harness, job)
    await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)
    await asyncio.sleep(0)
    return job, dispatch, await get_job_by_name(harness, name)
