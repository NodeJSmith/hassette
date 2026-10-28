"""Integration tests: an app's running invocations end when the app stops.

A ``parallel`` handler or job has no overlap guard tracking its invocation, so cancelling the listener
or removing the job alone can't stop it. The invocation must still belong to the app, so the app's
teardown cancels it like any other app task. Guarded (non-parallel) job invocations belong to the app
too, so one that is slow to handle cancellation can't keep the rest running past the job-removal hook's
timeout.
"""

import asyncio
import contextlib

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS

SHUTDOWN_HOOK_TIMEOUT_SECONDS = 0.2
"""Shutdown-hook bound for the slow-to-cancel test, so the job-removal hook times out quickly."""
SLOW_CANCEL_SECONDS = 1.0
"""How long the slow job takes to finish once cancelled: longer than the hook bound."""


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


class _SlowCancelJobsApp(App[AppConfig]):
    """Registers two ``single`` jobs: the first takes a while to finish once cancelled, the second doesn't."""

    slow_started: asyncio.Event
    started: asyncio.Event
    cancelled: asyncio.Event

    async def on_initialize(self) -> None:
        self.slow_started = asyncio.Event()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        await self.scheduler.run_in(self.finish_slowly_when_cancelled, delay=10, name="slow")
        await self.scheduler.run_in(self.run_until_cancelled, delay=10, name="long")

    async def finish_slowly_when_cancelled(self) -> None:
        self.slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            loop = asyncio.get_running_loop()
            finish_at = loop.time() + SLOW_CANCEL_SECONDS
            while loop.time() < finish_at:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(finish_at - loop.time())
            raise

    async def run_until_cancelled(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def test_a_job_slow_to_cancel_does_not_keep_other_jobs_running() -> None:
    async with AppTestHarness(_SlowCancelJobsApp, config={"instance_name": "slow_cancel_jobs_app"}) as harness:
        app = harness.app
        app.hassette.config.lifecycle.shutdown_timeout_seconds = SHUTDOWN_HOOK_TIMEOUT_SECONDS
        # trigger_due_jobs dispatches one job at a time, so dispatch each job in its own task instead.
        dispatches = [
            asyncio.create_task(harness.require_harness().scheduler_service.run_job_with_guard(job))
            for job in app.scheduler.list_jobs()
        ]
        try:
            await asyncio.wait_for(app.slow_started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)
            await asyncio.wait_for(app.started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

            await asyncio.wait_for(app.shutdown(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

            assert app.cancelled.is_set(), "a job slow to cancel kept another job's invocation running"
        finally:
            for dispatch in dispatches:
                dispatch.cancel()
            await asyncio.wait_for(
                asyncio.gather(*dispatches, return_exceptions=True), timeout=HANG_GUARD_TIMEOUT_SECONDS
            )
