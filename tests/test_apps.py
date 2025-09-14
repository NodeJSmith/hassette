import asyncio
from unittest.mock import AsyncMock, Mock

from hassette import ResourceStatus
from hassette.config import HassetteConfig
from hassette.core.apps.app_handler import _AppHandler


async def test_apps_are_working(test_config) -> None:
    """Test actual WebSocket calls against running HA instance."""
    tc = HassetteConfig(
        websocket_timeout_seconds=1,
        run_sync_timeout_seconds=2,
        run_health_service=False,
        apps={
            "my_app": {"enabled": True, "filename": "my_app.py", "class_name": "MyApp"},
            "my_app_sync": {"enabled": True, "filename": "my_app.py", "class_name": "MyAppSync"},  # type: ignore
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

    await asyncio.sleep(0.3)
    assert app_handler is not None, "App handler should be initialized"
    assert app_handler.apps, "There should be at least one app group"
    assert "my_app" in app_handler.apps, "my_app should be one of the app groups"
    assert "my_app_sync" in app_handler.apps, "my_app_sync should be one of the app groups"
