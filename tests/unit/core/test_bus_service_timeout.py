"""Tests for BusService._make_tracked_invoke_fn() effective timeout resolution."""

from unittest.mock import MagicMock

from hassette.core.commands import InvokeHandler
from hassette.events.base import Event
from hassette.test_utils.helpers import create_listener

from .conftest import make_bus_service


def make_event() -> Event:
    """Create a minimal Event for testing."""
    return MagicMock(spec=Event)


class TestDispatchResolvesEffectiveTimeout:
    async def test_dispatch_resolves_effective_timeout_from_listener(self) -> None:
        """listener.timeout=5 -> effective_timeout=5."""
        svc = make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic", timeout=5.0)
        event = make_event()

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout == 5.0

    async def test_dispatch_resolves_effective_timeout_from_config(self) -> None:
        """listener.timeout=None -> uses config default."""
        svc = make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic")
        event = make_event()

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout == 600.0

    async def test_dispatch_resolves_timeout_disabled(self) -> None:
        """listener.timeout_disabled=True -> effective_timeout=None."""
        svc = make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic", timeout_disabled=True)
        event = make_event()

        invoke_fn = svc._make_tracked_invoke_fn("test.topic", event, listener)
        await invoke_fn()

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout is None

    async def test_once_listener_removed_after_dispatch(self) -> None:
        """once=True handler is removed from the bus after dispatch regardless of execution outcome."""
        svc = make_bus_service(config_timeout=600.0)
        listener = create_listener(topic="test.topic", timeout=0.001, once=True)
        event = make_event()

        # After dispatch, listener.once should cause removal
        # We test that _dispatch calls remove_listener after once handler fires
        svc.remove_listener = MagicMock(return_value=None)

        await svc._dispatch("test.topic", event, listener)

        # Verify remove_listener was called for the once listener
        svc.remove_listener.assert_called_once_with(listener)
