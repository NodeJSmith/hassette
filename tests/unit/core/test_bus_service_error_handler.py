"""Tests for build_tracked_invoke_fn() carrying app_level_error_handler on InvokeHandler."""

from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.commands import InvokeHandler
from hassette.test_utils.factories import make_mock_event, make_mock_executor
from hassette.test_utils.helpers import create_listener


class TestDispatchCarriesAppLevelHandler:
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When the listener's resolver returns a handler, it is set on InvokeHandler."""
        executor = make_mock_executor()
        event = make_mock_event()

        async def app_handler(ctx) -> None:
            pass

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: app_handler)

        invoke_fn = build_tracked_invoke_fn(listener, event, "test.topic", executor, lambda: 600.0)
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is app_handler

    async def test_dispatch_no_handler_when_none_set(self) -> None:
        """When the listener has no resolver, app_level_error_handler is None."""
        executor = make_mock_executor()
        event = make_mock_event()

        listener = create_listener(topic="test.topic")

        invoke_fn = build_tracked_invoke_fn(listener, event, "test.topic", executor, lambda: 600.0)
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    async def test_dispatch_no_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None (Bus._error_handler not set), field is None."""
        executor = make_mock_executor()
        event = make_mock_event()

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: None)

        invoke_fn = build_tracked_invoke_fn(listener, event, "test.topic", executor, lambda: 600.0)
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    async def test_dispatch_resolves_handler_at_dispatch_time(self) -> None:
        """Resolver is called at dispatch time: updates to Bus._error_handler are reflected."""
        executor = make_mock_executor()
        event = make_mock_event()

        current_handler = [None]

        async def handler_v2(ctx) -> None:
            pass

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: current_handler[0])

        invoke_fn = build_tracked_invoke_fn(listener, event, "test.topic", executor, lambda: 600.0)
        await invoke_fn()
        cmd = executor.execute.call_args[0][0]
        assert cmd.app_level_error_handler is None

        current_handler[0] = handler_v2

        invoke_fn = build_tracked_invoke_fn(listener, event, "test.topic", executor, lambda: 600.0)
        await invoke_fn()
        cmd = executor.execute.call_args[0][0]
        assert cmd.app_level_error_handler is handler_v2
