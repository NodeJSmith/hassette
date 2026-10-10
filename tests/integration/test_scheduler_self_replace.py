"""Integration tests for a scheduler job replacing itself from inside its own callback.

A job re-arming under its own name via ``if_exists="replace"`` removes the very registration whose
invocation is running. That invocation must finish rather than deadlock (async callback awaiting its
own cancellation) or be cancelled mid-run (sync callback in a worker thread).
"""

import asyncio
import time

import pytest

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness


class _SelfReplaceConfig(AppConfig):
    """Config for the self-replace app: the execution mode under test."""

    mode: str = "single"


class _SelfReplaceApp(App[_SelfReplaceConfig]):
    """One-shot hold timer that re-arms itself via ``if_exists="replace"`` on its first firing."""

    fire_count: int
    callback_finished: bool
    refired: asyncio.Event

    async def on_initialize(self) -> None:
        self.fire_count = 0
        self.callback_finished = False
        self.refired = asyncio.Event()
        await self.arm()

    async def arm(self) -> None:
        await self.scheduler.run_in(self.hold, delay=10, name="hold", if_exists="replace", mode=self.app_config.mode)

    async def hold(self) -> None:
        self.fire_count += 1
        if self.fire_count == 1:
            await self.arm()
        else:
            self.refired.set()
        self.callback_finished = True


@pytest.mark.parametrize("mode", ["single", "queued", "restart", "parallel"])
async def test_job_replaces_itself_from_own_callback(mode: str) -> None:
    """``run_in(..., if_exists="replace")`` from a job's own callback re-arms it instead of hanging.

    The replace path removes the running job, whose guard tracks the very task executing the
    callback; that invocation must run to completion rather than being cancelled or awaited.
    """
    async with AppTestHarness(_SelfReplaceApp, config={"mode": mode}) as harness:
        app = harness.app
        scheduler_service = harness._harness.hassette._scheduler_service
        original = next(j for j in app.scheduler.list_jobs() if j.name == "hold")

        harness.freeze_time(original.next_run.add(seconds=1))
        count = await asyncio.wait_for(harness.trigger_due_jobs(), timeout=2.0)

        assert count == 1
        assert app.callback_finished, "the self-replacing invocation must run to completion"
        replacement = next(j for j in app.scheduler.list_jobs() if j.name == "hold")
        assert replacement is not original, "the job should have been replaced by a fresh registration"
        assert original._dequeued, "the old registration should be removed"
        assert replacement in await scheduler_service.get_all_jobs(), "the replacement should be on the heap"

        # Enqueuing the replacement woke the harness's serve() loop, which can pop the second
        # firing before trigger_due_jobs does — so wait for the firing, not for this call's count.
        harness.freeze_time(replacement.next_run.add(seconds=1))
        await asyncio.wait_for(harness.trigger_due_jobs(), timeout=2.0)
        await asyncio.wait_for(app.refired.wait(), timeout=2.0)
        assert app.fire_count == 2, "the replacement should fire on its own schedule"


class _SyncSelfReplaceApp(App[_SelfReplaceConfig]):
    """Sync-callback variant: the callback runs in a worker thread and re-arms via ``scheduler.sync``."""

    fire_count: int
    callback_finished: bool

    async def on_initialize(self) -> None:
        self.fire_count = 0
        self.callback_finished = False
        await self.scheduler.run_in(self.hold, delay=10, name="hold", if_exists="replace", mode=self.app_config.mode)

    def hold(self) -> None:
        self.fire_count += 1
        if self.fire_count == 1:
            self.scheduler.sync.run_in(self.hold, delay=10, name="hold", if_exists="replace", mode=self.app_config.mode)
            # Give a cancelled dispatch time to return before the callback finishes, so a
            # dispatch that stopped waiting on the worker thread is observable.
            time.sleep(0.2)
        self.callback_finished = True


# parallel is omitted: its guard tracks no invocation, so removal never cancels it either way.
@pytest.mark.parametrize("mode", ["single", "queued", "restart"])
async def test_sync_job_replaces_itself_from_own_callback(mode: str) -> None:
    """A sync callback re-arming itself is not cancelled; the dispatch waits for the worker thread.

    The sync facade runs the replace in a separate event-loop task, not the tracked invocation
    task, so self-release detection must recognize it through the invocation's context.
    """
    async with AppTestHarness(_SyncSelfReplaceApp, config={"mode": mode}) as harness:
        app = harness.app
        original = next(j for j in app.scheduler.list_jobs() if j.name == "hold")

        harness.freeze_time(original.next_run.add(seconds=1))
        count = await asyncio.wait_for(harness.trigger_due_jobs(), timeout=2.0)

        assert count == 1
        assert app.callback_finished, "the dispatch must wait for the sync callback to finish"
        replacement = next(j for j in app.scheduler.list_jobs() if j.name == "hold")
        assert replacement is not original
        assert original._dequeued
