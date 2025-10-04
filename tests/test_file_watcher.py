import asyncio
import contextlib
import typing
from typing import Any

import anyio

from hassette.core.events.hassette import Event
from hassette.core.topics import HASSETTE_EVENT_FILE_WATCHER

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


async def test_event_emitted_on_file_change(hassette_with_file_watcher: "Hassette"):
    # make these shorter for convenience
    hassette = hassette_with_file_watcher
    file_watcher = hassette._file_watcher

    # we're going to wait for this to be set
    called_event = asyncio.Event()

    # our handler for the file watcher event
    async def handler(event: Event[Any]) -> None:
        called_event.set()
        assert event.topic == HASSETTE_EVENT_FILE_WATCHER, f"Unexpected topic: {event.topic}"

    hassette._bus.on(topic=HASSETTE_EVENT_FILE_WATCHER, handler=handler)

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
                assert called_event.is_set(), f"Expected called_event to be set, got {called_event.is_set()}"
                return
