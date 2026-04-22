"""Tests for BusService dispatch carrying app_level_error_handler on InvokeHandler (WP04)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.listeners import Listener
from hassette.core.bus_service import BusService
from hassette.core.commands import InvokeHandler
from hassette.events.base import Event


def _make_bus_service(*, config_timeout: float = 600.0) -> BusService:
    """Create a BusService with mocked internals."""
    svc = BusService.__new__(BusService)
    svc.hassette = MagicMock()
    svc.hassette.config.event_handler_timeout_seconds = config_timeout
    svc.hassette.config.bus_excluded_domains = ()
    svc.hassette.config.bus_excluded_entities = ()
    svc.hassette.config.log_all_events = False
    svc.hassette.config.registration_await_timeout = 30
    svc.logger = MagicMock()

    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()

    svc.task_bucket = MagicMock()
    svc.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    svc.task_bucket.spawn = MagicMock(return_value=MagicMock(spec=["add_done_callback"]))

    svc._dispatch_pending = 0
    svc._dispatch_idle_event = asyncio.Event()
    svc._dispatch_idle_event.set()

    return svc


def _make_listener_with_resolver(
    *,
    resolver=None,
) -> Listener:
    """Create a Listener with a pre-set app_error_handler_resolver."""
    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    listener = Listener.create(
        task_bucket=task_bucket,
        owner_id="test_owner",
        topic="test.topic",
        handler=lambda: None,
    )
    listener._app_error_handler_resolver = resolver
    return listener


def _make_event() -> Event:
    return MagicMock(spec=Event)


class TestDispatchCarriesAppLevelHandler:
    @pytest.mark.asyncio
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When the listener's resolver returns a handler, it is set on InvokeHandler."""
        svc = _make_bus_service()
        event = _make_event()

        async def app_handler(ctx) -> None:
            pass

        listener = _make_listener_with_resolver(resolver=lambda: app_handler)

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is app_handler

    @pytest.mark.asyncio
    async def test_dispatch_no_handler_when_none_set(self) -> None:
        """When the listener has no resolver, app_level_error_handler is None."""
        svc = _make_bus_service()
        event = _make_event()

        # Listener without resolver (simulates framework listener or test harness listener)
        listener = _make_listener_with_resolver(resolver=None)

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    @pytest.mark.asyncio
    async def test_dispatch_no_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None (Bus._error_handler not set), field is None."""
        svc = _make_bus_service()
        event = _make_event()

        listener = _make_listener_with_resolver(resolver=lambda: None)

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    @pytest.mark.asyncio
    async def test_dispatch_resolves_handler_at_dispatch_time(self) -> None:
        """Resolver is called at dispatch time: updates to Bus._error_handler are reflected."""
        svc = _make_bus_service()
        event = _make_event()

        # Simulate a Bus._error_handler that can change
        current_handler = [None]

        async def handler_v2(ctx) -> None:
            pass

        listener = _make_listener_with_resolver(resolver=lambda: current_handler[0])

        # First dispatch: no handler
        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()
        cmd = svc._executor.execute.call_args[0][0]
        assert cmd.app_level_error_handler is None

        # Update the Bus's handler
        current_handler[0] = handler_v2

        # Second dispatch: handler is now set
        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()
        cmd = svc._executor.execute.call_args[0][0]
        assert cmd.app_level_error_handler is handler_v2
