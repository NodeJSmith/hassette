import asyncio
import contextlib
import typing
from collections.abc import Coroutine
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from anyio import create_memory_object_stream

from hassette.core.bus import Bus
from hassette.core.bus.bus import _Bus
from hassette.core.events.hassette import Event
from hassette.core.file_watcher import _FileWatcher
from hassette.core.topics import HASSETTE_EVENT_FILE_WATCHER
from hassette.utils import wait_for_resources_running_or_raise

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


@pytest.fixture
async def hassette_with_file_watcher(test_config_with_apps):
    class MockHassette:
        task: asyncio.Task

        def __init__(self):
            self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, Event]](1000)
            self._bus = _Bus(cast("Hassette", self), self._receive_stream.clone())
            self.bus = Bus(cast("Hassette", self), self._bus)
            self.ready_event = asyncio.Event()
            self.ready_event.set()

            self._shutdown_event = asyncio.Event()
            self.logger = Mock()
            self.config = test_config_with_apps
            self.wait_for_resources_running = AsyncMock(return_value=True)
            self._file_watcher = _FileWatcher(cast("Hassette", self))

        async def send_event(self, topic: str, event: Event[typing.Any]) -> None:
            """Mock method to send an event to the bus."""
            await self._send_stream.send((topic, event))

        def create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
            return asyncio.create_task(coro)

    hassette = MockHassette()

    hassette.wait_for_resources_running = AsyncMock(return_value=True)

    hassette.config.file_watcher_debounce_milliseconds = 1
    hassette.config.file_watcher_step_milliseconds = 5

    bus_task = asyncio.create_task(hassette._bus.run_forever())
    file_watcher_task = asyncio.create_task(hassette._file_watcher.run_forever())

    await wait_for_resources_running_or_raise([hassette._file_watcher, hassette._bus], timeout=5)
    yield hassette

    for t in [bus_task, file_watcher_task]:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t


async def test_event_emitted_on_file_change(hassette_with_file_watcher: "Hassette"):
    # make these shorter for convenience
    hassette = hassette_with_file_watcher
    file_watcher = hassette._file_watcher

    # we're going to wait for this to be set
    called_event = asyncio.Event()

    # our handler for the file watcher event
    async def handler(event: Event[Any]) -> None:
        called_event.set()
        assert event.topic == HASSETTE_EVENT_FILE_WATCHER

    hassette.bus.on(topic=HASSETTE_EVENT_FILE_WATCHER, handler=handler)

    # wait a moment to ensure everything is settled
    await asyncio.sleep(0.2)

    touched_files = []
    for f in file_watcher.hassette.config.get_watchable_files():
        if f.is_file():
            f.write_text(f.read_text())
            touched_files.append(f)
            break

    assert touched_files, "No toml files found to touch in test_event_emitted_on_file_change"
    await asyncio.sleep(0.2)

    # can be flaky, try a couple of times
    for _ in range(2):
        with contextlib.suppress(asyncio.TimeoutError):
            with anyio.fail_after(1):
                await called_event.wait()
                assert called_event.is_set()
                return
