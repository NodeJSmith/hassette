"""Tests for Bus.on() timeout threading to Listener."""

from unittest.mock import MagicMock

from hassette.bus.bus import Bus, Options


def _make_bus() -> Bus:
    """Create a Bus with mocked internals, bypassing Resource.__init__."""
    bus = Bus.__new__(Bus)
    bus.hassette = MagicMock()
    bus.bus_service = MagicMock()
    bus.bus_service.add_listener = MagicMock(return_value=MagicMock(spec=["add_done_callback"]))
    bus.priority = 0
    bus.logger = MagicMock()
    bus.task_bucket = MagicMock()
    bus.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    bus._parent = None
    bus._registered_keys = set()
    bus._unique_name = "test_bus"
    bus.unique_id = "test_bus_id"
    bus._owner_id = "test_owner"
    return bus


class TestBusOnPassesTimeout:
    def test_bus_on_passes_timeout_to_listener(self) -> None:
        """bus.on(topic=..., handler=..., timeout=5.0) creates listener with timeout=5.0."""
        bus = _make_bus()
        sub = bus.on(topic="test.topic", handler=lambda: None, timeout=5.0)
        assert sub.listener.timeout == 5.0

    def test_bus_on_passes_timeout_disabled(self) -> None:
        """timeout_disabled=True threads through to listener."""
        bus = _make_bus()
        sub = bus.on(topic="test.topic", handler=lambda: None, timeout_disabled=True)
        assert sub.listener.timeout_disabled is True

    def test_bus_on_default_timeout(self) -> None:
        """Default timeout is None when not specified."""
        bus = _make_bus()
        sub = bus.on(topic="test.topic", handler=lambda: None)
        assert sub.listener.timeout is None
        assert sub.listener.timeout_disabled is False


class TestConvenienceMethodPassesTimeout:
    def test_on_state_change_passes_timeout_via_options(self) -> None:
        """Convenience method forwards timeout through _subscribe -> on()."""
        bus = _make_bus()
        sub = bus.on_state_change("light.test", handler=lambda: None, timeout=10.0)
        assert sub.listener.timeout == 10.0

    def test_on_state_change_passes_timeout_disabled_via_options(self) -> None:
        """Convenience method forwards timeout_disabled through _subscribe -> on()."""
        bus = _make_bus()
        sub = bus.on_state_change("light.test", handler=lambda: None, timeout_disabled=True)
        assert sub.listener.timeout_disabled is True


class TestOptionsTypedDict:
    def test_timeout_in_options(self) -> None:
        """Options TypedDict includes timeout field."""
        assert "timeout" in Options.__annotations__

    def test_timeout_disabled_in_options(self) -> None:
        """Options TypedDict includes timeout_disabled field."""
        assert "timeout_disabled" in Options.__annotations__
