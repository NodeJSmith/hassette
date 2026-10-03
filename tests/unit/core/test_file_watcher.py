"""Unit tests for FileWatcherService."""

import asyncio
from unittest.mock import MagicMock

import pytest

from hassette.core.file_watcher import FileWatcherService
from tests.support.factories import make_bypassed_service
from tests.support.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette() -> MagicMock:
    return make_mock_hassette(sealed=False)


@pytest.fixture
def watcher(mock_hassette: MagicMock) -> FileWatcherService:
    return make_bypassed_service(FileWatcherService, mock_hassette)


async def test_on_initialize_marks_ready_when_disabled(watcher: FileWatcherService) -> None:
    watcher.hassette.config.file_watcher.watch_files = False
    await watcher.on_initialize()
    assert watcher.is_ready()
    assert "disabled" in (watcher._ready_reason or "").lower()


async def test_on_initialize_does_not_mark_ready_when_enabled(watcher: FileWatcherService) -> None:
    watcher.hassette.config.file_watcher.watch_files = True
    await watcher.on_initialize()
    assert not watcher.is_ready()


async def test_serve_blocks_on_shutdown_event_when_disabled(watcher: FileWatcherService) -> None:
    """When disabled, serve() parks on shutdown_event instead of returning immediately.

    A serve() that returns goes through handle_stop(), which calls mark_not_ready() --
    see .claude/rules/resource-lifecycle.md. If serve() returned right away here, the
    disabled-but-ready service would immediately be marked not-ready again.
    """
    watcher.hassette.config.file_watcher.watch_files = False
    task = asyncio.create_task(watcher.serve())
    await asyncio.sleep(0)
    assert not task.done(), "serve() returned immediately instead of blocking on shutdown_event"

    watcher.shutdown_event.set()
    await asyncio.wait_for(task, timeout=1)
