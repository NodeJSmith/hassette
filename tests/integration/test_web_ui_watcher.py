"""Integration tests for WebUiWatcherService broadcast pipeline.

Uses a mock ``awatch`` generator to yield synthetic file-change events,
avoiding real filesystem watcher timing issues.
"""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.web_ui_watcher import WebUiWatcherService


@pytest.fixture
def mock_hassette() -> MagicMock:
    hassette = MagicMock()
    hassette.config.web_ui_hot_reload = True
    hassette.data_sync_service = MagicMock()
    hassette.data_sync_service.broadcast = AsyncMock()
    return hassette


@pytest.fixture
def watcher(mock_hassette: MagicMock) -> WebUiWatcherService:
    svc = WebUiWatcherService.__new__(WebUiWatcherService)
    svc.hassette = mock_hassette
    svc.shutdown_event = asyncio.Event()
    svc.logger = MagicMock()
    svc.mark_ready = MagicMock()
    return svc


def _fake_awatch(*changes_batches: set[tuple[int, str]]):
    """Return an async generator factory that yields the given change batches."""

    async def _awatch(*_args: object, **_kwargs: object) -> AsyncIterator[set[tuple[int, str]]]:
        for batch in changes_batches:
            yield batch

    return _awatch


async def test_css_change_broadcasts_dev_reload(watcher: WebUiWatcherService) -> None:
    fake = _fake_awatch({(2, "/web/static/css/style.css")})

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    watcher.mark_ready.assert_called_once()
    watcher.hassette.data_sync_service.broadcast.assert_awaited_once_with(
        {"type": "dev_reload", "data": {"path": "/web/static/css/style.css", "kind": "css"}}
    )


async def test_js_change_broadcasts_dev_reload(watcher: WebUiWatcherService) -> None:
    fake = _fake_awatch({(2, "/web/static/js/app.js")})

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    watcher.hassette.data_sync_service.broadcast.assert_awaited_once_with(
        {"type": "dev_reload", "data": {"path": "/web/static/js/app.js", "kind": "js"}}
    )


async def test_template_change_broadcasts_dev_reload(watcher: WebUiWatcherService) -> None:
    fake = _fake_awatch({(2, "/web/templates/pages/dashboard.html")})

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    watcher.hassette.data_sync_service.broadcast.assert_awaited_once_with(
        {"type": "dev_reload", "data": {"path": "/web/templates/pages/dashboard.html", "kind": "template"}}
    )


async def test_multiple_changes_in_single_batch(watcher: WebUiWatcherService) -> None:
    fake = _fake_awatch(
        {
            (2, "/web/static/css/style.css"),
            (2, "/web/static/js/app.js"),
        }
    )

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    assert watcher.hassette.data_sync_service.broadcast.await_count == 2
    kinds = {call.args[0]["data"]["kind"] for call in watcher.hassette.data_sync_service.broadcast.await_args_list}
    assert kinds == {"css", "js"}


async def test_disabled_config_does_not_broadcast(watcher: WebUiWatcherService) -> None:
    watcher.hassette.config.web_ui_hot_reload = False
    watcher.shutdown_event.set()
    await watcher.serve()
    watcher.hassette.data_sync_service.broadcast.assert_not_awaited()
