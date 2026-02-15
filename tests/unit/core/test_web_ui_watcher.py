"""Unit tests for WebUiWatcherService."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.web_ui_watcher import _WATCH_DIRS, _WEB_DIR, WebUiWatcherService, _change_kind

# --- _change_kind classification ---


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/static/css/style.css", "css"),
        ("/a/b/c/theme.css", "css"),
        ("/static/js/app.js", "js"),
        ("/static/js/ws-handler.js", "js"),
        ("/templates/base.html", "template"),
        ("/templates/macros/ui.html", "template"),
        ("/static/img/logo.png", "template"),
        ("/path/to/file", "template"),
        ("/path/to/component.jsx", "template"),
        ("/path/to/notcss", "template"),
    ],
)
def test_change_kind(path: str, expected: str) -> None:
    assert _change_kind(path) == expected


# --- Module-level constants ---


def test_web_dir_points_to_web_package() -> None:
    assert _WEB_DIR.name == "web"
    assert (_WEB_DIR / "static").exists()
    assert (_WEB_DIR / "templates").exists()


def test_watch_dirs_contains_static_and_templates() -> None:
    assert len(_WATCH_DIRS) == 2
    assert _WEB_DIR / "static" in _WATCH_DIRS
    assert _WEB_DIR / "templates" in _WATCH_DIRS


# --- Service lifecycle ---


@pytest.fixture
def mock_hassette() -> MagicMock:
    hassette = MagicMock()
    hassette.config.web_ui_hot_reload = False
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


async def test_on_initialize_marks_ready_when_disabled(watcher: WebUiWatcherService) -> None:
    watcher.hassette.config.web_ui_hot_reload = False
    await watcher.on_initialize()
    watcher.mark_ready.assert_called_once()
    assert "disabled" in watcher.mark_ready.call_args.kwargs.get("reason", "").lower()


async def test_on_initialize_does_not_mark_ready_when_enabled(watcher: WebUiWatcherService) -> None:
    watcher.hassette.config.web_ui_hot_reload = True
    await watcher.on_initialize()
    watcher.mark_ready.assert_not_called()


async def test_serve_waits_on_shutdown_when_disabled(watcher: WebUiWatcherService) -> None:
    """When disabled, serve() blocks on shutdown_event and never broadcasts."""
    watcher.hassette.config.web_ui_hot_reload = False
    # Set shutdown immediately so serve() returns
    watcher.shutdown_event.set()
    await watcher.serve()
    watcher.hassette.data_sync_service.broadcast.assert_not_called()


async def test_serve_returns_early_when_no_watch_dirs(watcher: WebUiWatcherService) -> None:
    """When enabled but watch dirs don't exist, serve() logs warning and returns."""
    watcher.hassette.config.web_ui_hot_reload = True
    with patch(
        "hassette.core.web_ui_watcher._WATCH_DIRS",
        [Path("/nonexistent/static"), Path("/nonexistent/templates")],
    ):
        await watcher.serve()
    watcher.logger.warning.assert_called_once()
    watcher.hassette.data_sync_service.broadcast.assert_not_called()
