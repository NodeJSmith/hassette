"""Tests for Resource shutdown/init edge-case branches not covered elsewhere.

Verifies:
- initialize() early-returns as a no-op when already initializing
- shutdown() skips the STOPPING transition when status is already terminal
- _finalize_shutdown() swallows an exception raised by handle_stop()
- _emit_readiness_event() swallows an exception raised while building/sending the event
- cleanup() closes a present cache, and swallows an exception if close() raises
"""

from unittest.mock import AsyncMock, patch

from hassette.resources.lifecycle import mark_ready
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus

from .conftest import ConcreteResource


class _FakeCacheOk:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeCacheRaises:
    def close(self) -> None:
        raise RuntimeError("cache close boom")


class TestInitializeAlreadyInitializing:
    async def test_initialize_is_noop_when_already_initializing(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        resource.initializing = True  # simulate a concurrent initialize() already in flight

        calls: list[str] = []

        async def _spy_on_initialize() -> None:
            calls.append("called")

        resource.on_initialize = _spy_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

        await resource.initialize()

        assert calls == [], "on_initialize must not run — the second call is a no-op"
        assert resource.status == ResourceStatus.NOT_STARTED, "handle_starting() must not run either"


class TestShutdownSkipsStoppingWhenTerminal:
    async def test_shutdown_does_not_transition_through_stopping_when_already_terminal(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        # Force an already-terminal status without going through the normal shutdown path
        # (shutdown_completed/shutting_down remain False, so shutdown() does not early-return).
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


class TestFinalizeShutdownSwallowsHandleStopException:
    async def test_handle_stop_exception_does_not_propagate(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()

        # handle_stop() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (base.py) rather than reassigning an instance
        # attribute, since _finalize_shutdown() calls the free function directly.
        with patch("hassette.resources.base.handle_stop", side_effect=RuntimeError("handle_stop boom")):
            # Must not raise despite handle_stop() blowing up.
            await resource._finalize_shutdown()

        assert resource.shutdown_completed is True

    async def test_cleanup_exception_does_not_propagate(self) -> None:
        """A non-timeout exception from cleanup() is logged and swallowed, not re-raised."""
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()

        async def _raising_cleanup(_timeout: int | None = None) -> None:
            raise RuntimeError("cleanup boom")

        resource.cleanup = _raising_cleanup  # pyright: ignore[reportAttributeAccessIssue]

        # Must not raise despite cleanup() blowing up, and shutdown must still complete.
        await resource._finalize_shutdown()

        assert resource.shutdown_completed is True

    async def test_skips_handle_stop_when_event_streams_already_closed(self) -> None:
        """When event streams are already closed, _finalize_shutdown() skips handle_stop()."""
        hassette = make_mock_hassette(sealed=False)
        hassette.event_streams_closed = True
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()
        resource._status = ResourceStatus.RUNNING  # handle_stop() would otherwise flip this to STOPPED

        # handle_stop() is a module-level function (hassette.resources.lifecycle), not a
        # method — patch it at the call site (base.py) rather than reassigning an instance
        # attribute, since _finalize_shutdown() calls the free function directly.
        with patch("hassette.resources.base.handle_stop") as mock_handle_stop:
            await resource._finalize_shutdown()

            mock_handle_stop.assert_not_called()
        assert resource.status == ResourceStatus.RUNNING, "status must be untouched by the skipped STOPPED event"
        assert resource.shutdown_completed is True


class TestEmitReadinessEventSwallowsException:
    async def test_send_event_exception_does_not_propagate(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        resource._status = ResourceStatus.RUNNING
        mark_ready(resource, "test reason")

        hassette.send_event = AsyncMock(side_effect=RuntimeError("send boom"))

        # Must not raise despite send_event() blowing up.
        await resource._emit_readiness_event()


class TestCleanupCache:
    async def test_cleanup_closes_present_cache(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()

        fake_cache = _FakeCacheOk()
        resource._cache = fake_cache

        await resource.cleanup()

        assert fake_cache.closed is True

    async def test_cleanup_swallows_cache_close_exception(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        resource = ConcreteResource(hassette=hassette)
        await resource.initialize()

        resource._cache = _FakeCacheRaises()

        # Must not raise despite cache.close() blowing up.
        await resource.cleanup()
