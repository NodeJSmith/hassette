"""Unit tests for build_tracked_invoke_fn in hassette.bus.invocation.

Tests cover:
- Timeout resolution: disabled → None, per-listener → value, config default → config_resolver() return value
- InvokeHandler construction with correct fields (listener_id read lazily from listener.db_id)
- executor.execute is called with the constructed command
- is_synthetic flag propagation
"""

from unittest.mock import MagicMock

from hassette.bus.invocation import build_tracked_invoke_fn
from hassette.commands import InvokeHandler
from hassette.test_utils.factories import make_mock_event, make_mock_executor
from hassette.test_utils.helpers import create_listener


class TestTimeoutResolution:
    async def test_timeout_disabled_returns_none(self) -> None:
        """listener.timeout_disabled=True → effective_timeout=None."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=600.0)
        listener = create_listener(topic="test.topic", timeout_disabled=True)
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout is None

    async def test_per_listener_timeout_used_when_set(self) -> None:
        """listener.timeout=5 → effective_timeout=5.0, config_resolver not called."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=600.0)
        listener = create_listener(topic="test.topic", timeout=5.0)
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout == 5.0
        config_resolver.assert_not_called()

    async def test_config_default_used_when_no_listener_timeout(self) -> None:
        """listener.timeout=None → effective_timeout from config_resolver()."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=30.0)
        listener = create_listener(topic="test.topic")  # no timeout set
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.effective_timeout == 30.0
        config_resolver.assert_called_once()

    async def test_config_resolver_called_lazily_at_fire_time(self) -> None:
        """config_resolver is called when invoke_fn fires, not when build_tracked_invoke_fn is called."""
        executor = make_mock_executor()
        call_count = []
        config_resolver = MagicMock(side_effect=lambda: call_count.append(1) or 10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )

        # config_resolver not called yet
        assert len(call_count) == 0

        await invoke_fn()

        # config_resolver called exactly once at fire time
        assert len(call_count) == 1


class TestInvokeHandlerConstruction:
    async def test_invoke_handler_fields_are_correct(self) -> None:
        """InvokeHandler is constructed with correct listener, event, topic, source_tier."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic", source_tier="app")
        event = make_mock_event()
        topic = "test.topic"

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic=topic,
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.listener is listener
        assert cmd.event is event
        assert cmd.topic == topic
        assert cmd.source_tier == "app"

    async def test_listener_id_read_from_db_id_at_fire_time(self) -> None:
        """listener_id on InvokeHandler reads listener.db_id lazily at fire time."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        # db_id is None at build time
        assert listener.db_id is None

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )

        # Set db_id after building the invoke_fn (simulates async registration completing)
        listener.db_id = 42

        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.listener_id == 42

    async def test_executor_execute_called_with_command(self) -> None:
        """executor.execute is called exactly once with the InvokeHandler command."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        executor.execute.assert_called_once()
        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)


class TestIsSyntheticFlag:
    async def test_is_synthetic_defaults_to_false(self) -> None:
        """is_synthetic defaults to False when not specified."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert cmd.is_synthetic is False

    async def test_is_synthetic_true_propagates_to_command(self) -> None:
        """is_synthetic=True is forwarded to InvokeHandler.is_synthetic."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
            is_synthetic=True,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert cmd.is_synthetic is True


class TestErrorHandlerResolution:
    async def test_error_handler_from_resolver_propagates(self) -> None:
        """When listener's app_error_handler_resolver returns a handler, it is set on InvokeHandler."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        async def app_handler(ctx) -> None:
            pass

        listener.invoker.set_app_error_handler_resolver(lambda: app_handler)

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is app_handler

    async def test_no_error_handler_when_resolver_is_none(self) -> None:
        """When listener has no resolver, app_level_error_handler is None."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        # No resolver set → app_error_handler_resolver is None by default
        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None

    async def test_no_error_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None, app_level_error_handler is None."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")
        event = make_mock_event()

        listener.invoker.set_app_error_handler_resolver(lambda: None)

        invoke_fn = build_tracked_invoke_fn(
            listener=listener,
            event=event,
            topic="test.topic",
            executor=executor,
            config_resolver=config_resolver,
        )
        await invoke_fn()

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.app_level_error_handler is None
