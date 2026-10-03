"""Unit tests for FileWatcherService."""

import asyncio
from unittest.mock import MagicMock

import pytest

from hassette.core.file_watcher import FileWatcherService
from tests.support.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette() -> MagicMock:
    return make_mock_hassette(sealed=False)


@pytest.fixture
def watcher(mock_hassette: MagicMock) -> FileWatcherService:
    svc = FileWatcherService.__new__(FileWatcherService)
    svc.hassette = mock_hassette
    svc.shutdown_event = asyncio.Event()
    svc.logger = MagicMock()
    svc._unique_name = "FileWatcherService.test"
    # Real Event so the module-level mark_ready() (called by on_initialize()/serve())
    # can operate on this bypassed instance.
    svc.ready_event = asyncio.Event()
    svc._ready_reason = None
    return svc


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
