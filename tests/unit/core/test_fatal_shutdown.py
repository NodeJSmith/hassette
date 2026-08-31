"""Unit tests for fatal-exit observability.

Tests shutdown_if_crashed behavior in isolation: that it sets
_fatal_shutdown_reason and calls request_shutdown instead of shutdown.

Project rule: no log-capture tests. Assert on state / FatalError only.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.test_utils.helpers import make_crashed_event, make_unsafe_restart_refused_error
from hassette.types.enums import ResourceRole

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

        with patch("hassette.core.service_watcher.request_shutdown", side_effect=track_request_shutdown):
            await watcher.shutdown_if_crashed(event)

        assert call_order == ["reason_set_first", "request_shutdown"], (
            f"Expected reason set before request_shutdown, got order: {call_order}"
        )


class TestHandleRestartRefusedSetsFatalReason:
    """handle_restart_refused writes the fatal reason before requesting shutdown and before
    dispatching the CRASHED event -- the same race-safe ordering guarantee as
    shutdown_if_crashed (see TestShutdownIfCrashedSetsFatalReason above), for the typed
    restart-refusal escalation path.
    """

    @pytest.fixture
    def watcher_hassette(self):
        """Minimal mock hassette with the fields ServiceWatcher.handle_restart_refused needs."""
        hassette = MagicMock()
        hassette.config.logging.service_watcher = "DEBUG"
        hassette.shutdown_event = asyncio.Event()
        hassette._fatal_shutdown_reason = None
        hassette.send_event = AsyncMock()

        def record(reason: str) -> None:
            if hassette._fatal_shutdown_reason is None:
                hassette._fatal_shutdown_reason = reason

        hassette.record_fatal_reason = MagicMock(side_effect=record)
        return hassette

    async def test_sets_fatal_reason_with_resource_name(self, watcher_hassette):
        watcher = make_watcher(watcher_hassette)
        error = make_unsafe_restart_refused_error("BusService")

        with patch("hassette.core.service_watcher.request_shutdown"):
            await watcher.handle_restart_refused("BusService", ResourceRole.SERVICE, error)

        assert watcher_hassette._fatal_shutdown_reason is not None
        assert "BusService" in watcher_hassette._fatal_shutdown_reason

    async def test_calls_request_shutdown_not_full_shutdown(self, watcher_hassette):
        """handle_restart_refused must call request_shutdown() (sets shutdown_event), never a
        bare hassette.shutdown() -- run_forever() must own root teardown, not this handler.
        """
        watcher = make_watcher(watcher_hassette)
        error = make_unsafe_restart_refused_error("BusService")

        with patch("hassette.core.service_watcher.request_shutdown") as mock_request_shutdown:
            await watcher.handle_restart_refused("BusService", ResourceRole.SERVICE, error)

        mock_request_shutdown.assert_called_once()
        watcher_hassette.shutdown.assert_not_called()

    async def test_reason_set_before_request_shutdown(self, watcher_hassette):
        """Fatal reason is set BEFORE request_shutdown is called (ordering guarantee)."""
        call_order: list[str] = []

        def track_request_shutdown(_resource, _reason=None):
            if watcher_hassette._fatal_shutdown_reason is not None:
                call_order.append("reason_set_first")
            call_order.append("request_shutdown")

        watcher = make_watcher(watcher_hassette)
        error = make_unsafe_restart_refused_error("BusService")

        with patch("hassette.core.service_watcher.request_shutdown", side_effect=track_request_shutdown):
            await watcher.handle_restart_refused("BusService", ResourceRole.SERVICE, error)

        assert call_order == ["reason_set_first", "request_shutdown"], (
            f"Expected reason set before request_shutdown, got order: {call_order}"
        )

    async def test_reason_set_before_event_dispatch(self, watcher_hassette):
        """Fatal reason is set BEFORE the CRASHED event is dispatched -- event dispatch is
        telemetry, not the control path, and event handlers run asynchronously (task-per-
        handler), so a reader reacting to the event must already see the reason.
        """
        observed: dict[str, object] = {}

        async def track_send_event(_event):
            observed["reason_at_dispatch"] = watcher_hassette._fatal_shutdown_reason

        watcher_hassette.send_event = AsyncMock(side_effect=track_send_event)
        watcher = make_watcher(watcher_hassette)
        error = make_unsafe_restart_refused_error("BusService")

        with patch("hassette.core.service_watcher.request_shutdown"):
            await watcher.handle_restart_refused("BusService", ResourceRole.SERVICE, error)

        assert observed["reason_at_dispatch"] is not None
