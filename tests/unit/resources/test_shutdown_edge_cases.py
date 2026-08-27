"""Tests for Resource shutdown/init edge-case branches not covered elsewhere.

Verifies:
- A concurrent initialize() call while one is already in flight joins that same attempt
  instead of running a second independent initialization
- shutdown() skips the STOPPING transition when status is already terminal
- _shutdown_body() swallows an exception raised by handle_stop()
- _emit_readiness_event() swallows an exception raised while building/sending the event
"""

import asyncio
from unittest.mock import AsyncMock, patch

from hassette.resources.lifecycle import mark_ready
from hassette.resources.teardown import RestartSafety, TeardownCause
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus

from .conftest import ConcreteResource


class TestInitializeJoinsInFlightAttempt:
    async def test_second_initialize_joins_in_flight_attempt(self) -> None:
        """A concurrent initialize() call while one is already in flight joins that same
        attempt instead of running a second independent initialization.

        Superseded by the coordinator design: initialize() is no longer a same-instance
        no-op when already initializing — every concurrent caller shields and awaits the one
        resource-owned ``_init_task`` attempt. See ``tests/unit/resources/lifecycle/test_init.py``
        for the dedicated concurrency/re-entry coverage this scenario belongs to.
        """
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)

        calls: list[str] = []
        entered = asyncio.Event()
        release = asyncio.Event()

        async def _gated_on_initialize() -> None:
            calls.append("called")
            entered.set()
            await release.wait()

        resource.on_initialize = _gated_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

        first = asyncio.create_task(resource.initialize())
        await asyncio.wait_for(entered.wait(), timeout=1)

        second = asyncio.create_task(resource.initialize())

        release.set()
        await first
        await second

        assert calls == ["called"], "on_initialize must run exactly once — both calls share one attempt"
        assert resource.status == ResourceStatus.RUNNING

        await resource.shutdown()


class TestShutdownSkipsStoppingWhenTerminal:
    async def test_shutdown_does_not_transition_through_stopping_when_already_terminal(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        # Force an already-terminal status without going through the normal shutdown path
        # (no teardown report exists yet, so shutdown() does not early-return).
        resource._status = ResourceStatus.STOPPED

        status_during_hook: list[ResourceStatus] = []

        async def _spy_on_shutdown() -> None:
            status_during_hook.append(resource.status)

        resource.on_shutdown = _spy_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        await resource.shutdown()

        assert status_during_hook == [ResourceStatus.STOPPED], (
            f"status must stay STOPPED (STOPPING transition skipped for a terminal state), got {status_during_hook}"
        )
        assert resource.shutdown_completed is True


class TestShutdownBodySwallowsHandleStopException:
    async def test_handle_stop_exception_does_not_propagate(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()

        # handle_stop() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (base.py) rather than reassigning an instance
        # attribute, since _shutdown_body()'s post-hook stage calls the free function directly.
        with patch("hassette.resources.base.handle_stop", side_effect=RuntimeError("handle_stop boom")):
            # Must not raise despite handle_stop() blowing up.
            report = await resource._shutdown_body()

        assert report is not None, "the body must complete and return a report rather than raise"

    async def test_cleanup_exception_does_not_propagate(self) -> None:
        """A non-timeout exception from cleanup() is logged, swallowed, and recorded as evidence."""
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()

        async def _raising_cleanup(_timeout: int | None = None) -> None:
            raise RuntimeError("cleanup boom")

        resource.cleanup = _raising_cleanup  # pyright: ignore[reportAttributeAccessIssue]

        # Must not raise despite cleanup() blowing up, and the body must still complete.
        report = await resource._shutdown_body()

        assert TeardownCause.CLEANUP_FAILED in report.causes
        assert report.restart_safety is RestartSafety.UNSAFE
        assert "cleanup" in report.failed_operations

    async def test_skips_handle_stop_when_event_streams_already_closed(self) -> None:
        """When event streams are already closed, the shutdown body skips handle_stop()."""
        hassette = make_mock_hassette(sealed=False)
        hassette.event_streams_closed = True
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()
        resource._status = ResourceStatus.RUNNING  # handle_stop() would otherwise flip this to STOPPED

        # handle_stop() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (base.py) rather than reassigning an instance
        # attribute, since _shutdown_body()'s post-hook stage calls the free function directly.
        with patch("hassette.resources.base.handle_stop") as mock_handle_stop:
            await resource._shutdown_body()

            mock_handle_stop.assert_not_called()
        assert resource.status == ResourceStatus.RUNNING, "status must be untouched by the skipped STOPPED event"


class TestEmitReadinessEventSwallowsException:
    async def test_send_event_exception_does_not_propagate(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        resource._status = ResourceStatus.RUNNING
        mark_ready(resource, "test reason")

        hassette.send_event = AsyncMock(side_effect=RuntimeError("send boom"))

        # Must not raise despite send_event() blowing up.
        await resource._emit_readiness_event()
