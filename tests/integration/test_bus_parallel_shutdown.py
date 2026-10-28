"""Integration test: an app's ``parallel``-mode handler invocation ends when the app stops.

A ``parallel`` listener has no overlap guard tracking its invocation, so cancelling the listener alone
can't stop it. The invocation must still belong to the app, so the app's teardown cancels it like any
other app task.
"""

import asyncio

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS


class _ParallelHandlerApp(App[AppConfig]):
    """Subscribes one ``parallel`` handler that runs until cancelled."""

    started: asyncio.Event
    cancelled: asyncio.Event

    async def on_initialize(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        await self.bus.on_state_change("light.kitchen", handler=self.long_handler, name="long_handler", mode="parallel")

    async def long_handler(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def test_a_running_parallel_handler_is_cancelled_when_its_app_stops() -> None:
    async with AppTestHarness(_ParallelHandlerApp, config={"instance_name": "parallel_handler_app"}) as harness:
        app = harness.app
        simulate = asyncio.create_task(harness.simulate_state_change("light.kitchen", old_value="off", new_value="on"))
        await asyncio.wait_for(app.started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        report = await asyncio.wait_for(app.shutdown(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        assert app.cancelled.is_set(), "the parallel invocation outlived its app's teardown"
        assert report.is_restart_safe
        await asyncio.wait_for(simulate, timeout=HANG_GUARD_TIMEOUT_SECONDS)
