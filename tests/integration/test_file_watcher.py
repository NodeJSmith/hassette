import asyncio
import typing
from typing import Any

import anyio
import pytest

from hassette.events.hassette import Event
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import HassetteConfig
    from hassette.testing import HassetteHarness


async def test_harness_starts_with_file_watcher_disabled(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config_class: "type[HassetteConfig]",
    unused_tcp_port_factory,
) -> None:
    """Regression test for #2500.

    FileWatcherService.serve()'s disabled branch used to return without ever calling
    mark_ready(), so the startup coordinator waited the full startup timeout for a
    service that would never become ready, then failed startup entirely.
    """
    config = test_config_class(
        web_api={"port": unused_tcp_port_factory()},
        file_watcher={"watch_files": False},
    )

    async with hassette_harness(config).with_bus().with_file_watcher().with_api_mock() as harness:
        assert harness.file_watcher.is_ready()


async def test_event_emitted_on_file_change(hassette_with_file_watcher: "HassetteHarness"):
    """File watcher emits an event when a tracked file changes."""
    hassette_instance = hassette_with_file_watcher
    file_watcher_service = hassette_instance.file_watcher

    file_event_received = asyncio.Event()

    async def handler(event: Event[Any]) -> None:
        hassette_with_file_watcher.task_bucket.post_to_loop(file_event_received.set)
        assert event.topic == Topic.HASSETTE_EVENT_FILE_WATCHER, f"Unexpected topic: {event.topic}"

    await hassette_instance.bus.on(topic=Topic.HASSETTE_EVENT_FILE_WATCHER, handler=handler, name="file_watcher_test")

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
    for attempt in range(2):
        try:
            with anyio.fail_after(2):
                await file_event_received.wait()
                assert file_event_received.is_set(), (
                    f"Expected file_event_received to be set, got {file_event_received.is_set()}"
                )
                return
        except TimeoutError:
            if attempt == 1:
                pytest.fail("file_event_received was never set after 2 attempts")
