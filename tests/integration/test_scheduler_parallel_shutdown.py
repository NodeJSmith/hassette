"""Integration test: an app's ``parallel``-mode job invocation ends when the app stops.

A ``parallel`` job has no overlap guard tracking its invocation, so job removal alone can't cancel it.
The invocation must still belong to the app, so the app's teardown cancels it like any other app task.
"""

import asyncio

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS


class _ParallelJobApp(App[AppConfig]):
    """Schedules one ``parallel`` job whose callback runs until cancelled."""

    started: asyncio.Event
    cancelled: asyncio.Event

    async def on_initialize(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        await self.scheduler.run_in(self.long_job, delay=10, name="long_job", mode="parallel")

    async def long_job(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def test_a_running_parallel_job_is_cancelled_when_its_app_stops() -> None:
    async with AppTestHarness(_ParallelJobApp, config={"instance_name": "parallel_job_app"}) as harness:
        app = harness.app
        job = next(j for j in app.scheduler.list_jobs() if j.name == "long_job")
        assert job.next_run is not None
        harness.freeze_time(job.next_run.add(seconds=1))
        trigger = asyncio.create_task(harness.trigger_due_jobs())
        await asyncio.wait_for(app.started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        report = await asyncio.wait_for(app.shutdown(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        assert app.cancelled.is_set(), "the parallel invocation outlived its app's teardown"
        assert report.is_restart_safe
        await asyncio.wait_for(trigger, timeout=HANG_GUARD_TIMEOUT_SECONDS)
