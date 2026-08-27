"""Tests for build_tracked_invoke_fn() carrying app_level_error_handler on InvokeHandler."""

from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.commands import InvokeHandler
from hassette.test_utils.config import TEST_CONFIG_TIMEOUT_SECONDS
from hassette.test_utils.factories import make_mock_event, make_mock_executor
from hassette.test_utils.helpers import create_listener


class TestDispatchCarriesAppLevelHandler:
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When the listener's resolver returns a handler, it is set on InvokeHandler."""
        executor = make_mock_executor()
        event = make_mock_event()

        async def app_handler(ctx) -> None:
            pass

        # dup-ignore-start: BusService-level dispatch test mirrors tests/unit/bus/test_invocation.py's
        # Bus-layer coverage of build_tracked_invoke_fn's app_level_error_handler resolution — same
        # behavior verified at two integration points (Bus vs BusService) by design, not copy-paste.
        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: app_handler)

        invoke_fn = build_tracked_invoke_fn(
            listener, event, "test.topic", executor, lambda: TEST_CONFIG_TIMEOUT_SECONDS
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is app_handler
        # dup-ignore-end

    async def test_dispatch_no_handler_when_none_set(self) -> None:
        """When the listener has no resolver, app_level_error_handler is None."""
        executor = make_mock_executor()
        event = make_mock_event()

        # dup-ignore-start: build-and-fire tail mirroring the Bus-layer coverage — see the matching
        # comment in test_dispatch_carries_app_level_handler above.
        listener = create_listener(topic="test.topic")

        invoke_fn = build_tracked_invoke_fn(
            listener, event, "test.topic", executor, lambda: TEST_CONFIG_TIMEOUT_SECONDS
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None
        # dup-ignore-end

    async def test_dispatch_no_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None (Bus._error_handler not set), field is None."""
        executor = make_mock_executor()
        event = make_mock_event()

        # dup-ignore-start: build-and-fire tail mirroring the Bus-layer coverage — see the matching
        # comment in test_dispatch_carries_app_level_handler above.
        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: None)

        invoke_fn = build_tracked_invoke_fn(
            listener, event, "test.topic", executor, lambda: TEST_CONFIG_TIMEOUT_SECONDS
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None
        # dup-ignore-end

    async def test_dispatch_resolves_handler_at_dispatch_time(self) -> None:
        """Resolver is called at dispatch time: updates to Bus._error_handler are reflected."""
        executor = make_mock_executor()
        event = make_mock_event()

        # Rebinding this local is visible to the resolver lambda below, which closes over the
        # variable rather than its value — no mutable cell needed to swap the handler mid-test.
        current_handler = None

        async def handler_v2(ctx) -> None:
            pass

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: current_handler)

        invoke_fn = build_tracked_invoke_fn(
            listener, event, "test.topic", executor, lambda: TEST_CONFIG_TIMEOUT_SECONDS
        )
        await invoke_fn()
        cmd = executor.execute.call_args[0][0]
        assert cmd.app_level_error_handler is None

        current_handler = handler_v2

        invoke_fn = build_tracked_invoke_fn(
            listener, event, "test.topic", executor, lambda: TEST_CONFIG_TIMEOUT_SECONDS
        )
        await invoke_fn()
        cmd = executor.execute.call_args[0][0]
        assert cmd.app_level_error_handler is handler_v2
