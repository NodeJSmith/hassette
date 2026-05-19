"""Tests for BusService._make_tracked_invoke_fn() effective timeout resolution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hassette.core.bus_service import BusService
from hassette.core.commands import InvokeHandler
from hassette.events.base import Event
from hassette.test_utils.helpers import create_listener


def _make_bus_service(*, config_timeout: float | None = 600.0) -> BusService:
    """Create a BusService with mocked internals, bypassing Resource.__init__."""
    svc = BusService.__new__(BusService)
    svc.hassette = MagicMock()
    svc.hassette.config.event_handler_timeout_seconds = config_timeout
    svc.hassette.config.bus_excluded_domains = ()
    svc.hassette.config.bus_excluded_entities = ()
    svc.hassette.config.log_all_events = False
    svc.hassette.config.registration_await_timeout = 30
    svc.logger = MagicMock()

    # Mock the executor
    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()

    # Mock task bucket
    svc.task_bucket = MagicMock()
    svc.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    svc.task_bucket.spawn = MagicMock(return_value=MagicMock(spec=["add_done_callback"]))

    # Dispatch tracking
    svc._dispatch_pending = 0
    svc._dispatch_idle_event = asyncio.Event()
    svc._dispatch_idle_event.set()
    svc._duration_timers_active = 0

    return svc


def _make_event() -> Event:
    """Create a minimal Event for testing."""
    return MagicMock(spec=Event)


class TestDispatchResolvesEffectiveTimeout:
    async def test_dispatch_resolves_effective_timeout_from_listener(self) -> None:
        """listener.timeout=5 -> effective_timeout=5."""
        svc = _make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic", timeout=5.0)
        event = _make_event()

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout == 5.0

    async def test_dispatch_resolves_effective_timeout_from_config(self) -> None:
        """listener.timeout=None -> uses config default."""
        svc = _make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic")
        event = _make_event()

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout == 600.0

    async def test_dispatch_resolves_timeout_disabled(self) -> None:
        """listener.timeout_disabled=True -> effective_timeout=None."""
        svc = _make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic", timeout_disabled=True)
        event = _make_event()

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout is None

    async def test_once_listener_removed_after_dispatch(self) -> None:
        """once=True handler is removed from the bus after dispatch regardless of execution outcome."""
        svc = _make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic", timeout=0.001, once=True)
        event = _make_event()

        # After dispatch, listener.once should cause removal
        # We test that _dispatch calls remove_listener after once handler fires
        svc.remove_listener = MagicMock(return_value=None)

        await svc._dispatch("test.topic", event, listener)

        # Verify remove_listener was called for the once listener
        svc.remove_listener.assert_called_once_with(listener)
