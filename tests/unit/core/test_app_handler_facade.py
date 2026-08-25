"""Unit tests for AppHandler's per-instance facade delegate methods.

Covers the thin reload_instance/stop_instance/start_instance delegates that forward to
AppLifecycleService — analogous to start_app/stop_app/reload_app, which are already
exercised indirectly via lifecycle-level tests but not as direct AppHandler-facade calls.

Uses the shared `app_handler` fixture from conftest.py (also used by
test_app_handler_readiness.py).
"""

from unittest.mock import AsyncMock

from hassette.core.app_handler import AppHandler


class TestAppHandlerInstanceFacade:
    async def test_reload_instance_delegates_to_lifecycle(self, app_handler: AppHandler) -> None:
        """reload_instance() forwards app_key, index, and force_reload to the lifecycle service."""
        app_handler.lifecycle.reload_instance = AsyncMock()

        await app_handler.reload_instance("test_app", 1, force_reload=True)

        app_handler.lifecycle.reload_instance.assert_awaited_once_with("test_app", 1, force_reload=True)

    async def test_stop_instance_delegates_to_lifecycle(self, app_handler: AppHandler) -> None:
        """stop_instance() forwards app_key and index to the lifecycle service."""
        app_handler.lifecycle.stop_instance = AsyncMock()

        await app_handler.stop_instance("test_app", 2)

        app_handler.lifecycle.stop_instance.assert_awaited_once_with("test_app", 2)

    async def test_start_instance_delegates_to_lifecycle(self, app_handler: AppHandler) -> None:
        """start_instance() forwards app_key and index to the lifecycle service."""
        app_handler.lifecycle.start_instance = AsyncMock()

        await app_handler.start_instance("test_app", 0)

        app_handler.lifecycle.start_instance.assert_awaited_once_with("test_app", 0)
