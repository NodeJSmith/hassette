import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from hassette import ResourceStatus
from hassette.config import HassetteConfig
from hassette.core.apps.app_handler import _AppHandler, load_app_class


@pytest.fixture
async def app_handler(test_config):
    tc = HassetteConfig(
        websocket_timeout_seconds=1,
        run_sync_timeout_seconds=2,
        run_health_service=False,
        apps={
            "my_app": {"enabled": True, "filename": "my_app.py", "class_name": "MyApp"},
            "my_app_sync": {"enabled": True, "filename": "my_app_sync.py", "class_name": "MyAppSync"},  # type: ignore
        },
        token=test_config.token.get_secret_value(),
        app_dir=test_config.app_dir,
    )

    hassette = Mock()
    hassette.send_event = AsyncMock()
    hassette.api.entity_exists = AsyncMock(return_value=True)
    hassette.config = tc
    hassette._websocket = Mock()
    hassette._websocket.connected = True
    hassette._websocket.status = ResourceStatus.RUNNING

    app_handler = _AppHandler(hassette)
    await app_handler.initialize()

    yield app_handler

    await app_handler.shutdown()


async def test_apps_are_working(app_handler: _AppHandler) -> None:
    """Test actual WebSocket calls against running HA instance."""

    await asyncio.sleep(0.3)
    assert app_handler is not None, "App handler should be initialized"
    assert app_handler.apps, "There should be at least one app group"
    assert "my_app" in app_handler.apps, "my_app should be one of the app groups"
    assert "my_app_sync" in app_handler.apps, "my_app_sync should be one of the app groups"

    # test that an app that only has config values but no class_name/filename is ignored
    assert "myfakeapp" not in app_handler.apps, "myfakeapp should not be one of the app groups"


def test_get_app_instance(app_handler: _AppHandler) -> None:
    """Test getting a specific app instance."""
    app = app_handler.get("my_app", 0)
    assert app is not None, "App instance should be found"

    my_app_class = load_app_class(app.app_manifest)

    assert isinstance(app, my_app_class), "App instance should be of type MyApp"


def test_all_apps(app_handler: _AppHandler) -> None:
    """Test getting all running app instances."""
    all_apps = app_handler.all()
    assert isinstance(all_apps, list), "All apps should return a list"
    assert len(all_apps) == 2, "There should be at least two running app instances"
    class_names = [app.class_name for app in all_apps]
    assert "MyApp" in class_names, "MyApp should be in the list of running apps"
    assert "MyAppSync" in class_names, "MyAppSync should be in the list of running apps"
