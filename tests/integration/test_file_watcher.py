import asyncio
import contextlib
import typing
from typing import Any

import anyio

from hassette.events.hassette import Event
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


async def test_event_emitted_on_file_change(hassette_with_file_watcher: "HassetteHarness"):
    """File watcher emits an event when a tracked file changes."""
    hassette_instance = hassette_with_file_watcher
    file_watcher_service = hassette_instance.file_watcher

    file_event_received = asyncio.Event()

    async def handler(event: Event[Any]) -> None:
        hassette_with_file_watcher.task_bucket.post_to_loop(file_event_received.set)
        assert event.topic == Topic.HASSETTE_EVENT_FILE_WATCHER, f"Unexpected topic: {event.topic}"

    hassette_instance.bus.on(topic=Topic.HASSETTE_EVENT_FILE_WATCHER, handler=handler)

    # timing: watcher bootstrap needs real time to settle inotify state
    await asyncio.sleep(0.2)

    updated_files: list[Any] = []
    for candidate_path in file_watcher_service.hassette.config.get_watchable_files():
        if candidate_path.is_file():
            candidate_path.write_text(candidate_path.read_text())
            updated_files.append(candidate_path)
            break

    assert updated_files, "No watchable files found to touch in test_event_emitted_on_file_change"

    # Event emission can be racy, so retry briefly.
    for _ in range(2):
        with contextlib.suppress(asyncio.TimeoutError):
            with anyio.fail_after(1):
                await file_event_received.wait()
                assert file_event_received.is_set(), (
                    f"Expected file_event_received to be set, got {file_event_received.is_set()}"
                )
                return
