"""Unit tests for AppHandler readiness and bootstrap scheduling semantics.

Uses the shared `app_handler`/`app_handler_mock_hassette` fixtures from conftest.py (also
used by test_app_handler_facade.py).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
from hassette.core.app_handler import AppHandler
from hassette.core.app_lifecycle_service import AppAdmissionMode


class TestAppHandlerReadiness:
    def test_depends_on_bootstrap_coordinator_only(self) -> None:
        assert AppHandler.depends_on == [AppBootstrapCoordinator]

    async def test_not_ready_after_on_initialize(self, app_handler: AppHandler) -> None:
        """on_initialize must NOT mark AppHandler ready — readiness deferred to after_initialize."""
        await app_handler.on_initialize()

        assert not app_handler.is_ready()

    async def test_ready_after_bootstrap_completes(self, app_handler: AppHandler) -> None:
        """after_initialize schedules bootstrap and marks AppHandler ready immediately."""
        app_handler.lifecycle.bootstrap_apps = AsyncMock()

        await app_handler.after_initialize()
        await asyncio.wait_for(app_handler._bootstrap_task, timeout=1.0)

        assert app_handler.is_ready()
        assert app_handler.has_bootstrapped() is True
        app_handler.lifecycle.bootstrap_apps.assert_awaited_once_with(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

    async def test_ready_while_bootstrap_in_progress(self, app_handler: AppHandler) -> None:
        """AppHandler becomes ready even while bootstrap is still waiting on release."""
        gate = asyncio.Event()
        started = asyncio.Event()

        async def gated_bootstrap(*, admission_mode: AppAdmissionMode) -> None:
            assert admission_mode is AppAdmissionMode.WAIT_FOR_RELEASE
            started.set()
            await gate.wait()

        app_handler.lifecycle.bootstrap_apps = gated_bootstrap

        await app_handler.after_initialize()
        await started.wait()

        assert app_handler.is_ready(), "Should be ready while bootstrap is gated"
        assert app_handler.has_bootstrapped() is False

        gate.set()
        await asyncio.wait_for(app_handler._bootstrap_task, timeout=1.0)

        assert app_handler.has_bootstrapped() is True, "Should report bootstrapped after bootstrap completes"

    async def test_bootstrap_error_is_confined_to_background_task(self, app_handler: AppHandler) -> None:
        """Bootstrap failures happen on the background task, not the startup wave."""

        async def failing_bootstrap(*, admission_mode: AppAdmissionMode) -> None:
            assert admission_mode is AppAdmissionMode.WAIT_FOR_RELEASE
            raise RuntimeError("app init exploded")

        app_handler.lifecycle.bootstrap_apps = failing_bootstrap

        await app_handler.after_initialize()

        assert app_handler.is_ready()
        with pytest.raises(RuntimeError, match="app init exploded"):
            await app_handler._bootstrap_task
        assert app_handler.has_bootstrapped() is False


class TestAppBootstrapCoordinator:
    async def test_becomes_ready_before_release_and_cancels_wait_on_shutdown(
        self, app_handler_mock_hassette: AsyncMock
    ) -> None:
        gate = asyncio.Event()
        entered = asyncio.Event()

        async def blocked_wait(*, timeout: float | None = None) -> bool:
            del timeout
            entered.set()
            await gate.wait()
            return True

        app_handler_mock_hassette.state_proxy = MagicMock()
        app_handler_mock_hassette.state_proxy.wait_initial_state_capability = AsyncMock(side_effect=blocked_wait)
        coordinator = AppBootstrapCoordinator(app_handler_mock_hassette)

        await coordinator.on_initialize()
        await asyncio.wait_for(entered.wait(), timeout=1.0)

        assert coordinator.is_ready()
        assert coordinator.is_released() is False

        await coordinator.shutdown()

        assert coordinator.shutdown_completed is True

    async def test_releases_after_initial_state_capability(self, app_handler_mock_hassette: AsyncMock) -> None:
        app_handler_mock_hassette.state_proxy = MagicMock()
        app_handler_mock_hassette.state_proxy.wait_initial_state_capability = AsyncMock(return_value=True)
        coordinator = AppBootstrapCoordinator(app_handler_mock_hassette)

        await coordinator.on_initialize()

        released = await coordinator.wait_released(timeout=1.0)

        assert released is True
        assert coordinator.is_released() is True
        await coordinator.shutdown()
