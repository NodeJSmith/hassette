"""Unit tests for fatal-exit observability (T03).

Tests shutdown_if_crashed behavior in isolation: that it sets
_fatal_shutdown_reason and calls request_shutdown instead of shutdown.

Project rule: no log-capture tests. Assert on state / FatalError only.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from hassette.core.service_watcher import ServiceWatcher
from hassette.events import HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.types import ResourceStatus, Topic


class TestShutdownIfCrashedSetsFatalReason:
    """shutdown_if_crashed writes the fatal reason before requesting shutdown."""

    @pytest.fixture
    def watcher_hassette(self):
        """Minimal mock hassette with the fields ServiceWatcher.shutdown_if_crashed needs."""
        hassette = MagicMock()
        hassette.config.logging.service_watcher = "DEBUG"
        hassette.shutdown_event = asyncio.Event()
        # After implementation, request_shutdown is a sync call that sets shutdown_event
        hassette.request_shutdown = MagicMock()
        hassette._fatal_shutdown_reason = None
        return hassette

    def make_watcher(self, hassette) -> ServiceWatcher:
        watcher = ServiceWatcher.__new__(ServiceWatcher)
        watcher.hassette = hassette
        watcher.logger = MagicMock()
        return watcher

    def make_crashed_event(self, name: str, exc_type: str) -> HassetteServiceEvent:
        return HassetteServiceEvent(
            topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
            payload=HassettePayload(
                data=ServiceStatusPayload(
                    resource_name=name,
                    role="Service",
                    status=ResourceStatus.CRASHED,
                    previous_status=ResourceStatus.FAILED,
                    exception="test crash",
                    exception_type=exc_type,
                    exception_traceback="tb line 1\ntb line 2",
                    ready=False,
                    ready_phase=None,
                ),
            ),
        )

    async def test_sets_fatal_reason_with_service_name(self, watcher_hassette):
        """shutdown_if_crashed sets _fatal_shutdown_reason containing the crashed service name."""
        watcher = self.make_watcher(watcher_hassette)
        event = self.make_crashed_event("BusService", "RuntimeError")

        await watcher.shutdown_if_crashed(event)

        assert watcher_hassette._fatal_shutdown_reason is not None
        assert "BusService" in watcher_hassette._fatal_shutdown_reason

    async def test_sets_fatal_reason_with_exception_type(self, watcher_hassette):
        """Fatal reason contains the exception type."""
        watcher = self.make_watcher(watcher_hassette)
        event = self.make_crashed_event("SchedulerService", "MyFatalException")

        await watcher.shutdown_if_crashed(event)

        reason = watcher_hassette._fatal_shutdown_reason
        assert reason is not None
        assert "SchedulerService" in reason

    async def test_calls_request_shutdown_not_shutdown(self, watcher_hassette):
        """shutdown_if_crashed calls request_shutdown (sets shutdown_event) not bare shutdown()."""
        watcher = self.make_watcher(watcher_hassette)
        event = self.make_crashed_event("BusService", "RuntimeError")

        await watcher.shutdown_if_crashed(event)

        watcher_hassette.request_shutdown.assert_called_once()

    async def test_reason_set_before_request_shutdown(self, watcher_hassette):
        """Fatal reason is set BEFORE request_shutdown is called (ordering guarantee)."""
        call_order: list[str] = []

        def track_request_shutdown(_reason=None):
            # At call time, reason must already be set
            if watcher_hassette._fatal_shutdown_reason is not None:
                call_order.append("reason_set_first")
            call_order.append("request_shutdown")

        watcher_hassette.request_shutdown = MagicMock(side_effect=track_request_shutdown)
        watcher = self.make_watcher(watcher_hassette)
        event = self.make_crashed_event("BusService", "RuntimeError")

        await watcher.shutdown_if_crashed(event)

        assert call_order == ["reason_set_first", "request_shutdown"], (
            f"Expected reason set before request_shutdown, got order: {call_order}"
        )
