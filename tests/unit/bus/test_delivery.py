"""Unit tests for ``Delivery`` in hassette.bus.delivery.

Tests cover:
- Timeout resolution: disabled → None, per-listener → value, config default → config_resolver() return value
- InvokeHandler construction with correct fields (listener_id read lazily from listener.db_id)
- executor.execute is called with the constructed command
- is_synthetic flag propagation
- ``drop`` reporting through the listener's reporter as bound at drop time
"""

from unittest.mock import MagicMock

from hassette.bus.delivery import Delivery
from hassette.bus.error_context import BusErrorContext
from hassette.bus.listeners import Listener
from hassette.commands import InvokeHandler
from hassette.testing.config import TEST_CONFIG_TIMEOUT_SECONDS
from tests.support.factories import make_mock_event, make_mock_executor
from tests.support.helpers import create_listener


async def invoke_and_get_cmd(
    *,
    listener: Listener | None = None,
    config_resolver: MagicMock | None = None,
    executor: MagicMock | None = None,
    event: MagicMock | None = None,
    topic: str = "test.topic",
    is_synthetic: bool = False,
) -> InvokeHandler:
    """Build a ``Delivery`` and invoke it, returning the resulting command.

    Fills in sane defaults for any argument not overridden. Callers that need to inspect
    ``executor``/``config_resolver`` afterward (e.g. ``config_resolver.assert_not_called()``)
    should pass their own mock in and keep the reference.
    """
    executor = executor if executor is not None else make_mock_executor()
    config_resolver = config_resolver if config_resolver is not None else MagicMock(return_value=10.0)
    listener = listener if listener is not None else create_listener(topic=topic)
    event = event if event is not None else make_mock_event()

    # dup-ignore-start: Bus-layer helper's fire-and-extract-cmd tail mirrors the BusService-level
    # dispatch tests in tests/unit/core/test_bus_service_error_handler.py and
    # test_bus_service_timeout.py — same Delivery.invoke behavior verified at two
    # integration points (Bus vs BusService) by design, not copy-paste.
    await Delivery(listener, event, topic, is_synthetic=is_synthetic).invoke(executor, config_resolver)

    cmd = executor.execute.call_args[0][0]
    assert isinstance(cmd, InvokeHandler)
    # dup-ignore-end
    return cmd


class TestTimeoutResolution:
    async def test_timeout_disabled_returns_none(self) -> None:
        """listener.timeout_disabled=True → effective_timeout=None, config_resolver not called."""
        config_resolver = MagicMock(return_value=TEST_CONFIG_TIMEOUT_SECONDS)
        listener = create_listener(topic="test.topic", timeout_disabled=True)

        cmd = await invoke_and_get_cmd(listener=listener, config_resolver=config_resolver)

        assert cmd.effective_timeout is None
        config_resolver.assert_not_called()

    async def test_per_listener_timeout_used_when_set(self) -> None:
        """listener.timeout=5 → effective_timeout=5.0, config_resolver not called."""
        config_resolver = MagicMock(return_value=TEST_CONFIG_TIMEOUT_SECONDS)
        listener = create_listener(topic="test.topic", timeout=5.0)

        cmd = await invoke_and_get_cmd(listener=listener, config_resolver=config_resolver)

        assert cmd.effective_timeout == 5.0
        config_resolver.assert_not_called()

    async def test_config_default_used_when_no_listener_timeout(self) -> None:
        """listener.timeout=None → effective_timeout from config_resolver()."""
        config_resolver = MagicMock(return_value=30.0)
        listener = create_listener(topic="test.topic")  # no timeout set

        cmd = await invoke_and_get_cmd(listener=listener, config_resolver=config_resolver)

        assert cmd.effective_timeout == 30.0
        config_resolver.assert_called_once()

    async def test_config_resolver_called_lazily_at_fire_time(self) -> None:
        """config_resolver is called when the delivery is invoked, not when it is created."""
        executor = make_mock_executor()
        call_count = []
        config_resolver = MagicMock(side_effect=lambda: call_count.append(1) or 10.0)
        listener = create_listener(topic="test.topic")

        delivery = Delivery(listener, make_mock_event(), "test.topic")

        # config_resolver not called yet
        assert len(call_count) == 0

        await delivery.invoke(executor, config_resolver)

        # config_resolver called exactly once at fire time
        assert len(call_count) == 1


class TestInvokeHandlerConstruction:
    async def test_invoke_handler_fields_are_correct(self) -> None:
        """InvokeHandler is constructed with correct listener, event, topic, source_tier."""
        listener = create_listener(topic="test.topic", source_tier="app")
        event = make_mock_event()
        topic = "test.topic"

        cmd = await invoke_and_get_cmd(listener=listener, event=event, topic=topic)

        assert cmd.listener is listener
        assert cmd.event is event
        assert cmd.topic == topic
        assert cmd.source_tier == "app"

    async def test_listener_id_read_from_db_id_at_fire_time(self) -> None:
        """listener_id on InvokeHandler reads listener.db_id lazily at fire time."""
        executor = make_mock_executor()
        config_resolver = MagicMock(return_value=10.0)
        listener = create_listener(topic="test.topic")

        # Built and invoked inline rather than via invoke_and_get_cmd: db_id must change between
        # creating the delivery and invoking it, and the helper does both in one call.
        # db_id is None at creation time
        assert listener.db_id is None

        delivery = Delivery(listener, make_mock_event(), "test.topic")

        # Set db_id after creating the delivery (simulates async registration completing)
        listener.db_id = 42

        await delivery.invoke(executor, config_resolver)

        cmd = executor.execute.call_args[0][0]
        assert isinstance(cmd, InvokeHandler)
        assert cmd.listener_id == 42

    async def test_executor_execute_called_with_command(self) -> None:
        """executor.execute is called exactly once with the InvokeHandler command."""
        executor = make_mock_executor()

        await invoke_and_get_cmd(executor=executor)

        executor.execute.assert_called_once()


class TestIsSyntheticFlag:
    async def test_is_synthetic_defaults_to_false(self) -> None:
        """is_synthetic defaults to False when not specified."""
        cmd = await invoke_and_get_cmd()

        assert cmd.is_synthetic is False

    async def test_is_synthetic_true_propagates_to_command(self) -> None:
        """is_synthetic=True is forwarded to InvokeHandler.is_synthetic."""
        cmd = await invoke_and_get_cmd(is_synthetic=True)

        assert cmd.is_synthetic is True


class TestErrorHandlerResolution:
    async def test_error_handler_from_resolver_propagates(self) -> None:
        """When listener's app_error_handler_resolver returns a handler, it is set on InvokeHandler."""

        async def app_handler(ctx: BusErrorContext) -> None:
            pass

        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: app_handler)

        cmd = await invoke_and_get_cmd(listener=listener)

        assert cmd.app_level_error_handler is app_handler

    async def test_no_error_handler_when_resolver_is_none(self) -> None:
        """When listener has no resolver, app_level_error_handler is None."""
        listener = create_listener(topic="test.topic")

        # No resolver set → app_error_handler_resolver is None by default
        cmd = await invoke_and_get_cmd(listener=listener)

        assert cmd.app_level_error_handler is None

    async def test_no_error_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None, app_level_error_handler is None."""
        listener = create_listener(topic="test.topic", app_error_handler_resolver=lambda: None)

        cmd = await invoke_and_get_cmd(listener=listener)

        assert cmd.app_level_error_handler is None


class TestDrop:
    def test_reports_the_event_and_its_synthetic_flag(self) -> None:
        listener = create_listener()
        report = MagicMock()
        listener.invoker.report_drop = report
        event = make_mock_event()

        Delivery(listener, event, "test.topic", is_synthetic=True).drop("filter", filter_index=2)

        report.assert_called_once_with("filter", event, filter_index=2, is_synthetic=True)

    def test_reads_the_reporter_at_drop_time(self) -> None:
        """A delivery made before its listener was removed records nothing once the reporter is unbound."""
        listener = create_listener()
        report = MagicMock()
        listener.invoker.report_drop = report
        delivery = Delivery(listener, make_mock_event(), "test.topic")

        listener.cancel()
        delivery.drop("busy")

        report.assert_not_called()

    def test_no_reporter_is_a_no_op(self) -> None:
        Delivery(create_listener(), make_mock_event(), "test.topic").drop("throttled")
