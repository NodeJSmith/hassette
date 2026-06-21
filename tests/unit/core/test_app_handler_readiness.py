"""Unit tests for AppHandler readiness semantics.

Verifies that AppHandler does not mark itself ready until bootstrap_apps()
completes — the core fix for #621.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.app_handler import AppHandler
from hassette.test_utils.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette() -> AsyncMock:
    hassette = make_mock_hassette(
        sealed=False,
        dev_mode=False,
        logging={"log_level": "DEBUG"},
        lifecycle={"app_startup_timeout_seconds": 30},
    )
    hassette.send_event = AsyncMock()
    hassette.bus_service.router = MagicMock()
    hassette.session_id = 1
    return hassette


@pytest.fixture
def app_handler(mock_hassette: MagicMock) -> AppHandler:
    with (
        patch("hassette.core.app_lifecycle_service.AppFactory"),
        patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
    ):
        handler = AppHandler(mock_hassette)
    return handler


class TestAppHandlerReadiness:
    async def test_not_ready_after_on_initialize(self, app_handler: AppHandler) -> None:
        """on_initialize must NOT mark AppHandler ready — readiness deferred to after_initialize."""
        await app_handler.on_initialize()

        assert not app_handler.is_ready()

    async def test_ready_after_bootstrap_completes(self, app_handler: AppHandler) -> None:
        """after_initialize must await bootstrap_apps and then mark ready."""
        app_handler.lifecycle.bootstrap_apps = AsyncMock()

        await app_handler.after_initialize()

        assert app_handler.is_ready()

    async def test_not_ready_while_bootstrap_in_progress(self, app_handler: AppHandler) -> None:
        """AppHandler stays not-ready while bootstrap_apps is still running."""
        gate = asyncio.Event()
        started = asyncio.Event()

        async def gated_bootstrap() -> None:
            started.set()
            await gate.wait()

        app_handler.lifecycle.bootstrap_apps = gated_bootstrap

        task = asyncio.create_task(app_handler.after_initialize())
        await started.wait()

        assert not app_handler.is_ready(), "Should not be ready while bootstrap is gated"

        gate.set()
        await task

        assert app_handler.is_ready(), "Should be ready after bootstrap completes"

    async def test_propagates_bootstrap_error(self, app_handler: AppHandler) -> None:
        """If bootstrap_apps raises, after_initialize propagates and AppHandler is not ready."""

        async def failing_bootstrap() -> None:
            raise RuntimeError("app init exploded")

        app_handler.lifecycle.bootstrap_apps = failing_bootstrap

        with pytest.raises(RuntimeError, match="app init exploded"):
            await app_handler.after_initialize()

        assert not app_handler.is_ready()
