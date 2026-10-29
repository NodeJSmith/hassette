"""Shutdown while a resource's initializer is still running: the pending initializer is named in the outcome."""

import asyncio
import contextlib

from hassette.resources.base import Resource
from hassette.resources.lifecycle import start
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette


class StubbornInitializer(Resource):
    """Resource whose ``on_initialize()`` ignores every cancellation until ``release`` is set."""

    entered: asyncio.Event
    release: asyncio.Event

    async def on_initialize(self) -> None:
        self.entered.set()
        while not self.release.is_set():
            with contextlib.suppress(asyncio.CancelledError):
                await self.release.wait()


async def test_a_pending_initializer_is_named_by_its_task_name():
    """An initializer still running after its bounded wait is named in ``still_running`` by its task name,
    so the outcome is restart-unsafe and the needs-restart record names it.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    resource = StubbornInitializer(hassette)
    resource.entered = asyncio.Event()
    resource.release = asyncio.Event()
    start(resource)
    await asyncio.wait_for(resource.entered.wait(), timeout=1)

    try:
        outcome = await resource.shutdown()
    finally:
        resource.release.set()

    assert outcome.still_running == (f"resource:initialize:{resource.unique_name}",)
    assert outcome.is_restart_safe is False
