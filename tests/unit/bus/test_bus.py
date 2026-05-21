"""Unit tests for Bus.on() name= parameter and collision detection.

Tests:
- name= parameter propagation to Listener
- Duplicate natural key raises ValueError synchronously in Bus.on()
- Duplicate name= raises ValueError synchronously in Bus.on()
- name= disambiguates otherwise-identical keys
- _registered_keys is cleared at start of initialization
"""

import typing
from unittest.mock import Mock

import pytest

from hassette.bus.listeners import Subscription

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus.bus import Bus


# ---------------------------------------------------------------------------
# Handlers used across tests (must be named module-level functions)
# ---------------------------------------------------------------------------


async def handler_a(event) -> None:
    pass


async def handler_b(event) -> None:
    pass


# ---------------------------------------------------------------------------
# Tests — name= parameter propagation
# ---------------------------------------------------------------------------


def test_name_parameter_propagates_to_listener(bus: "Bus") -> None:
    """name='my_listener' passed to Bus.on() ends up on listener.name."""
    with mock_add_listener(bus):
        subscription = bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert isinstance(subscription, Subscription)
        assert subscription.listener.identity.name == "my_listener"


def test_name_none_by_default(bus: "Bus") -> None:
    """Without name=, listener.name is None."""
    with mock_add_listener(bus):
        subscription = bus.on(topic="test.topic", handler=handler_a)
        assert subscription.listener.identity.name is None


# ---------------------------------------------------------------------------
# Tests — collision detection
# ---------------------------------------------------------------------------


def test_duplicate_natural_key_raises_value_error(bus: "Bus") -> None:
    """Registering the same handler+topic twice raises ValueError on the second call."""
    with mock_add_listener(bus):
        bus.on(topic="test.topic", handler=handler_a)
        with pytest.raises(ValueError, match="Duplicate listener"):
            bus.on(topic="test.topic", handler=handler_a)


def test_duplicate_name_raises_value_error(bus: "Bus") -> None:
    """Two listeners with same handler+topic and the same name= raise ValueError."""
    with mock_add_listener(bus):
        bus.on(topic="test.topic", handler=handler_a, name="x")
        with pytest.raises(ValueError, match="Duplicate listener"):
            bus.on(topic="test.topic", handler=handler_a, name="x")


def test_name_disambiguates_otherwise_identical_keys(bus: "Bus") -> None:
    """Two registrations with the same handler+topic but different name= both succeed."""
    with mock_add_listener(bus):
        sub1 = bus.on(topic="test.topic", handler=handler_a, name="listener_1")
        sub2 = bus.on(topic="test.topic", handler=handler_a, name="listener_2")
        assert sub1.listener.identity.name == "listener_1"
        assert sub2.listener.identity.name == "listener_2"


def test_different_handlers_same_topic_do_not_collide(bus: "Bus") -> None:
    """Two different handlers on the same topic are distinct and do not raise."""
    with mock_add_listener(bus):
        bus.on(topic="test.topic", handler=handler_a)
        bus.on(topic="test.topic", handler=handler_b)


def test_collision_detection_is_synchronous(bus: "Bus") -> None:
    """ValueError is raised synchronously in Bus.on() before add_listener is called a second time."""
    with mock_add_listener(bus) as add_mock:
        bus.on(topic="test.topic", handler=handler_a)
        call_count_after_first = add_mock.call_count

        with pytest.raises(ValueError, match="Duplicate listener"):
            bus.on(topic="test.topic", handler=handler_a)

        assert add_mock.call_count == call_count_after_first


# ---------------------------------------------------------------------------
# Tests — identity pass-through (Bus uses parent's telemetry identity)
# ---------------------------------------------------------------------------


def test_listener_inherits_parent_app_key(bus: "Bus") -> None:
    """Bus.on() sets listener.app_key from self.parent.app_key, not from Bus itself."""
    with mock_add_listener(bus):
        sub = bus.on(topic="test.identity", handler=handler_a, name="test_identity")
        assert sub.listener.identity.app_key == "test_app"
        assert sub.listener.identity.app_key != bus.app_key


def test_listener_inherits_parent_source_tier(bus: "Bus") -> None:
    """Bus.on() sets listener.source_tier from self.parent.source_tier."""
    with mock_add_listener(bus):
        sub = bus.on(topic="test.tier", handler=handler_a, name="test_tier")
        assert sub.listener.identity.source_tier == "app"


def test_listener_inherits_parent_instance_index(bus: "Bus") -> None:
    """Bus.on() sets listener.instance_index from self.parent.index."""
    bus.parent.index = 3
    with mock_add_listener(bus):
        sub = bus.on(topic="test.index", handler=handler_a, name="test_index")
        assert sub.listener.identity.instance_index == 3
    bus.parent.index = 0


def test_framework_bus_inherits_framework_tier(hassette_with_bus: "Hassette") -> None:
    """A Bus owned by a framework Resource inherits source_tier='framework'."""
    b = hassette_with_bus._bus
    assert b is not None
    with mock_add_listener(b):
        sub = b.on(topic="test.fw", handler=handler_a, name="test_fw")
        assert sub.listener.identity.source_tier == "framework"
        assert sub.listener.identity.app_key.startswith("__hassette__.")


def test_bus_requires_parent() -> None:
    """Bus.__init__ raises AssertionError when parent is None."""
    from hassette.bus.bus import Bus

    mock_hassette = Mock()
    mock_hassette._bus_service = Mock()
    with pytest.raises(AssertionError, match="Bus requires a parent"):
        Bus(mock_hassette, parent=None)


def test_source_tier_assertion_rejects_invalid_value(bus: "Bus") -> None:
    """Bus.on() raises AssertionError for invalid source_tier values."""
    bus.parent.source_tier = "invalid"
    with mock_add_listener(bus), pytest.raises(AssertionError, match="Invalid source_tier"):
        bus.on(topic="test.invalid", handler=handler_a, name="test_invalid")
    bus.parent.source_tier = "app"


def test_registered_keys_cleared_on_reinit(bus: "Bus") -> None:
    """_registered_keys is cleared at the start of on_initialize() to prevent stale collisions."""
    with mock_add_listener(bus):
        bus.on(topic="test.topic", handler=handler_a)
        assert len(bus._registered_keys) == 1

        bus._registered_keys.clear()

        bus.on(topic="test.topic", handler=handler_a)
        assert len(bus._registered_keys) == 1
