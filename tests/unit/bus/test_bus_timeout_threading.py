"""Tests for Bus.on() timeout threading to Listener."""

from unittest.mock import AsyncMock, MagicMock

from hassette.bus.bus import Bus, Options


def make_bus() -> Bus:
    """Create a Bus with mocked internals, bypassing Resource.__init__."""
    bus = Bus.__new__(Bus)
    bus.hassette = MagicMock()
    bus.bus_service = MagicMock()
    bus.bus_service.add_listener = AsyncMock(return_value=1)
    bus.priority = 0
    bus.logger = MagicMock()
    bus.task_bucket = MagicMock()
    bus.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    mock_parent = MagicMock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestParent"
    bus.parent = mock_parent
    bus._registered_handler_names = {}
    bus._unique_name = "test_bus"
    bus.unique_id = "test_bus_id"
    bus._owner_id = "test_owner"
    return bus


class TestBusOnPassesTimeout:
    async def test_bus_on_passes_timeout_to_listener(self) -> None:
        """bus.on(topic=..., handler=..., timeout=5.0) creates listener with timeout=5.0."""
        bus = make_bus()
        sub = await bus.on(topic="test.topic", handler=lambda: None, timeout=5.0, name="timeout_test")
        assert sub.listener.options.timeout == 5.0

    async def test_bus_on_passes_timeout_disabled(self) -> None:
        """timeout_disabled=True threads through to listener."""
        bus = make_bus()
        sub = await bus.on(topic="test.topic", handler=lambda: None, timeout_disabled=True, name="td_test")
        assert sub.listener.options.timeout_disabled is True

    async def test_bus_on_default_timeout(self) -> None:
        """Default timeout is None when not specified."""
        bus = make_bus()
        sub = await bus.on(topic="test.topic", handler=lambda: None, name="default_timeout_test")
        assert sub.listener.options.timeout is None
        assert sub.listener.options.timeout_disabled is False


class TestConvenienceMethodPassesTimeout:
    async def test_on_state_change_passes_timeout_via_options(self) -> None:
        """Convenience method forwards timeout through _subscribe -> on()."""
        bus = make_bus()
        sub = await bus.on_state_change("light.test", handler=lambda: None, timeout=10.0, name="sc_timeout")
        assert sub.listener.options.timeout == 10.0

    async def test_on_state_change_passes_timeout_disabled_via_options(self) -> None:
        """Convenience method forwards timeout_disabled through _subscribe -> on()."""
        bus = make_bus()
        sub = await bus.on_state_change("light.test", handler=lambda: None, timeout_disabled=True, name="sc_td")
        assert sub.listener.options.timeout_disabled is True


class TestOptionsTypedDict:
    def test_timeout_in_options(self) -> None:
        """Options TypedDict includes timeout field."""
        assert "timeout" in Options.__annotations__

    def test_timeout_disabled_in_options(self) -> None:
        """Options TypedDict includes timeout_disabled field."""
        assert "timeout_disabled" in Options.__annotations__
