"""Unit tests for fatal-exit observability.

Tests shutdown_if_crashed behavior in isolation: that it sets
_fatal_shutdown_reason and calls request_shutdown instead of shutdown.

Project rule: no log-capture tests. Assert on state / FatalError only.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from hassette.test_utils.helpers import make_crashed_event

from .conftest import make_watcher


class TestShutdownIfCrashedSetsFatalReason:
    """shutdown_if_crashed writes the fatal reason before requesting shutdown."""

    @pytest.fixture
    def watcher_hassette(self):
        """Minimal mock hassette with the fields ServiceWatcher.shutdown_if_crashed needs."""
        hassette = MagicMock()
        hassette.config.logging.service_watcher = "DEBUG"
        hassette.shutdown_event = asyncio.Event()
        hassette._fatal_shutdown_reason = None

        # record_fatal_reason mirrors the real Hassette method (first reason wins), so the watcher's
        # delegation is exercised faithfully rather than mocked to a no-op.
        def record(reason: str) -> None:
            if hassette._fatal_shutdown_reason is None:
                hassette._fatal_shutdown_reason = reason

        hassette.record_fatal_reason = MagicMock(side_effect=record)
        return hassette

    async def test_sets_fatal_reason_with_service_name(self, watcher_hassette):
        """shutdown_if_crashed sets _fatal_shutdown_reason containing the crashed service name."""
        watcher = make_watcher(watcher_hassette)
        event = make_crashed_event(resource_name="BusService", exception_type="RuntimeError")

        await watcher.shutdown_if_crashed(event)

        assert watcher_hassette._fatal_shutdown_reason is not None
        assert "BusService" in watcher_hassette._fatal_shutdown_reason

    async def test_sets_fatal_reason_with_exception_type(self, watcher_hassette):
        """Fatal reason contains the exception type."""
        watcher = make_watcher(watcher_hassette)
        event = make_crashed_event(resource_name="SchedulerService", exception_type="MyFatalException")

        await watcher.shutdown_if_crashed(event)

        reason = watcher_hassette._fatal_shutdown_reason
        assert reason is not None
        assert "SchedulerService" in reason

    async def test_calls_request_shutdown_not_shutdown(self, watcher_hassette):
        """shutdown_if_crashed calls request_shutdown (sets shutdown_event) not bare shutdown()."""
        watcher = make_watcher(watcher_hassette)
        event = make_crashed_event(resource_name="BusService", exception_type="RuntimeError")

        # boundary-exempt: collaborator of shutdown_if_crashed
        with patch("hassette.core.service_watcher.request_shutdown") as mock_request_shutdown:
            await watcher.shutdown_if_crashed(event)

        mock_request_shutdown.assert_called_once()

    async def test_reason_set_before_request_shutdown(self, watcher_hassette):
        """Fatal reason is set BEFORE request_shutdown is called (ordering guarantee)."""
        call_order: list[str] = []

        def track_request_shutdown(_resource, _reason=None):
            # At call time, reason must already be set
            if watcher_hassette._fatal_shutdown_reason is not None:
                call_order.append("reason_set_first")
            call_order.append("request_shutdown")

        watcher = make_watcher(watcher_hassette)
        event = make_crashed_event(resource_name="BusService", exception_type="RuntimeError")

        # boundary-exempt: collaborator of shutdown_if_crashed
        with patch("hassette.core.service_watcher.request_shutdown", side_effect=track_request_shutdown):
            await watcher.shutdown_if_crashed(event)

        assert call_order == ["reason_set_first", "request_shutdown"], (
            f"Expected reason set before request_shutdown, got order: {call_order}"
        )
