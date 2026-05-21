"""Tests for BusService dispatch carrying app_level_error_handler on InvokeHandler (WP04)."""

from unittest.mock import MagicMock

from hassette.bus.listeners import Listener
from hassette.core.commands import InvokeHandler
from hassette.events.base import Event
from hassette.test_utils.helpers import create_listener

from .conftest import make_bus_service


def make_listener_with_resolver(
    *,
    resolver=None,
) -> Listener:
    """Create a Listener with a pre-set app_error_handler_resolver."""
    listener = create_listener(topic="test.topic")
    listener.invoker.set_app_error_handler_resolver(resolver)
    return listener


def make_event() -> Event:
    return MagicMock(spec=Event)


class TestDispatchCarriesAppLevelHandler:
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When the listener's resolver returns a handler, it is set on InvokeHandler."""
        svc = make_bus_service()
        event = make_event()

        async def app_handler(ctx) -> None:
            pass

        listener = make_listener_with_resolver(resolver=lambda: app_handler)

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is app_handler

    async def test_dispatch_no_handler_when_none_set(self) -> None:
        """When the listener has no resolver, app_level_error_handler is None."""
        svc = make_bus_service()
        event = make_event()

        # Listener without resolver (simulates framework listener or test harness listener)
        listener = make_listener_with_resolver(resolver=None)

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    async def test_dispatch_no_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None (Bus._error_handler not set), field is None."""
        svc = make_bus_service()
        event = make_event()

        listener = make_listener_with_resolver(resolver=lambda: None)

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    async def test_dispatch_resolves_handler_at_dispatch_time(self) -> None:
        """Resolver is called at dispatch time: updates to Bus._error_handler are reflected."""
        svc = make_bus_service()
        event = make_event()

        # Simulate a Bus._error_handler that can change
        current_handler = [None]

        async def handler_v2(ctx) -> None:
            pass

        listener = make_listener_with_resolver(resolver=lambda: current_handler[0])

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
