"""Integration tests for WebUiWatcherService broadcast pipeline.

Uses a mock ``awatch`` generator to yield synthetic file-change events,
avoiding real filesystem watcher timing issues.
"""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from hassette.core.web_ui_watcher import _WEB_DIR, WebUiWatcherService
from tests.support.factories import make_bypassed_service
from tests.support.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette() -> MagicMock:
    hassette = make_mock_hassette(
        sealed=False,
        web_api={"ui_hot_reload": True},
    )
    hassette.runtime_query_service = MagicMock()
    hassette.runtime_query_service.put_to_clients = MagicMock()
    return hassette


@pytest.fixture
def watcher(mock_hassette: MagicMock) -> WebUiWatcherService:
    return make_bypassed_service(WebUiWatcherService, mock_hassette)


@pytest.fixture
def put_to_clients(mock_hassette: MagicMock) -> MagicMock:
    return mock_hassette.runtime_query_service.put_to_clients


def fake_awatch(*changes_batches: set[tuple[int, str]]):
    """Return an async generator factory that yields the given change batches."""

    async def _awatch(*_args: object, **_kwargs: object) -> AsyncIterator[set[tuple[int, str]]]:
        for batch in changes_batches:
            yield batch

    return _awatch


async def test_css_change_broadcasts_dev_reload(watcher: WebUiWatcherService, put_to_clients: MagicMock) -> None:
    css_path = str(_WEB_DIR / "static/css/style.css")
    fake = fake_awatch({(2, css_path)})

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    assert watcher.is_ready()
    put_to_clients.assert_called_once_with(
        {"type": "dev_reload", "data": {"path": "static/css/style.css", "kind": "css"}}
    )


async def test_js_change_broadcasts_dev_reload(watcher: WebUiWatcherService, put_to_clients: MagicMock) -> None:
    js_path = str(_WEB_DIR / "static/js/app.js")
    fake = fake_awatch({(2, js_path)})

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    put_to_clients.assert_called_once_with({"type": "dev_reload", "data": {"path": "static/js/app.js", "kind": "js"}})


async def test_template_change_broadcasts_dev_reload(watcher: WebUiWatcherService, put_to_clients: MagicMock) -> None:
    tmpl_path = str(_WEB_DIR / "templates/pages/dashboard.html")
    fake = fake_awatch({(2, tmpl_path)})

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    put_to_clients.assert_called_once_with(
        {"type": "dev_reload", "data": {"path": "templates/pages/dashboard.html", "kind": "template"}}
    )


async def test_multiple_changes_in_single_batch(watcher: WebUiWatcherService, put_to_clients: MagicMock) -> None:
    fake = fake_awatch(
        {
            (2, str(_WEB_DIR / "static/css/style.css")),
            (2, str(_WEB_DIR / "static/js/app.js")),
        }
    )

    with patch("hassette.core.web_ui_watcher.awatch", side_effect=fake):
        await watcher.serve()

    assert put_to_clients.call_count == 2
    kinds = {call.args[0]["data"]["kind"] for call in put_to_clients.call_args_list}
    assert kinds == {"css", "js"}


async def test_disabled_config_does_not_broadcast(watcher: WebUiWatcherService, put_to_clients: MagicMock) -> None:
    watcher.hassette.config.web_api.ui_hot_reload = False
    watcher.shutdown_event.set()
    await watcher.serve()
    put_to_clients.assert_not_called()
