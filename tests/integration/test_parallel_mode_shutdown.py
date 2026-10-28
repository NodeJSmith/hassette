"""Integration tests: an app's running ``parallel``-mode invocations end when the app stops.

A ``parallel`` handler or job has no overlap guard tracking its invocation, so cancelling the listener
or removing the job alone can't stop it. The invocation must still belong to the app, so the app's
teardown cancels it like any other app task.
"""

import asyncio

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS


class _ParallelWorkApp(App[AppConfig]):
    """Registers one ``parallel`` handler and one ``parallel`` job, each running until cancelled."""

    started: asyncio.Event
    cancelled: asyncio.Event

    async def on_initialize(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        await self.bus.on_state_change("light.kitchen", handler=self.run_until_cancelled, name="long", mode="parallel")
        await self.scheduler.run_in(self.run_until_cancelled, delay=10, name="long", mode="parallel")

    async def run_until_cancelled(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def assert_stopping_the_app_cancels_the_invocation(app: _ParallelWorkApp, trigger: asyncio.Task[object]) -> None:
    await asyncio.wait_for(app.started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

    report = await asyncio.wait_for(app.shutdown(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

    assert app.cancelled.is_set(), "the parallel invocation outlived its app's teardown"
    assert report.is_restart_safe
    await asyncio.wait_for(trigger, timeout=HANG_GUARD_TIMEOUT_SECONDS)


async def test_a_running_parallel_handler_is_cancelled_when_its_app_stops() -> None:
    async with AppTestHarness(_ParallelWorkApp, config={"instance_name": "parallel_handler_app"}) as harness:
        simulate = harness.simulate_state_change("light.kitchen", old_value="off", new_value="on")
        await assert_stopping_the_app_cancels_the_invocation(harness.app, asyncio.create_task(simulate))


async def test_a_running_parallel_job_is_cancelled_when_its_app_stops() -> None:
    async with AppTestHarness(_ParallelWorkApp, config={"instance_name": "parallel_job_app"}) as harness:
        job = next(j for j in harness.app.scheduler.list_jobs() if j.name == "long")
        assert job.next_run is not None
        harness.freeze_time(job.next_run.add(seconds=1))
        trigger = asyncio.create_task(harness.trigger_due_jobs())
        await assert_stopping_the_app_cancels_the_invocation(harness.app, trigger)
