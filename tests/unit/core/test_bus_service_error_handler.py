"""Tests for build_tracked_invoke_fn() carrying app_level_error_handler on InvokeHandler."""

from tests.support.factories import make_mock_executor
from tests.support.helpers import create_listener

from .test_bus_service_timeout import dispatch_and_get_cmd


class TestDispatchCarriesAppLevelHandler:
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When the listener's resolver returns a handler, it is set on InvokeHandler."""

        async def app_handler(ctx) -> None:
            pass

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: app_handler)

        cmd = await dispatch_and_get_cmd(listener)

        assert cmd.app_level_error_handler is app_handler

    async def test_dispatch_no_handler_when_none_set(self) -> None:
        """When the listener has no resolver, app_level_error_handler is None."""
        listener = create_listener(topic="test.topic")

        cmd = await dispatch_and_get_cmd(listener)

        assert cmd.app_level_error_handler is None

    async def test_dispatch_no_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None (Bus._error_handler not set), field is None."""
        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: None)

        cmd = await dispatch_and_get_cmd(listener)

        assert cmd.app_level_error_handler is None

    async def test_dispatch_resolves_handler_at_dispatch_time(self) -> None:
        """Resolver is called at dispatch time: updates to Bus._error_handler are reflected."""
        executor = make_mock_executor()

        # Rebinding this local is visible to the resolver lambda below, which closes over the
        # variable rather than its value — no mutable cell needed to swap the handler mid-test.
        current_handler = None

        async def handler_v2(ctx) -> None:
            pass

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: current_handler)

        cmd = await dispatch_and_get_cmd(listener, executor=executor)
        assert cmd.app_level_error_handler is None

        current_handler = handler_v2

        cmd = await dispatch_and_get_cmd(listener, executor=executor)
        assert cmd.app_level_error_handler is handler_v2
