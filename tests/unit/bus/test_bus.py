"""Unit tests for Bus.on() name= parameter and collision detection.

Tests:
- name= parameter propagation to Listener
- Duplicate natural key raises DuplicateListenerError in Bus.on()
- name= disambiguates otherwise-identical keys
- _registered_listeners is cleared at start of initialization
"""

import typing
from unittest.mock import Mock

import pytest

from hassette.bus.bus import Bus
from hassette.bus.listeners import Subscription
from hassette.exceptions import DuplicateListenerError, ListenerNameRequiredError

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette import Hassette


async def handler_a(event) -> None:
    pass


async def handler_b(event) -> None:
    pass


async def test_name_parameter_propagates_to_listener(bus: "Bus") -> None:
    """name='my_listener' passed to Bus.on() ends up on listener.name."""
    with mock_add_listener(bus):
        subscription = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert isinstance(subscription, Subscription)
        assert subscription.listener.identity.name == "my_listener"


async def test_name_none_raises_error(bus: "Bus") -> None:
    """Without name=, Bus.on() raises ListenerNameRequiredError."""
    with mock_add_listener(bus), pytest.raises(ListenerNameRequiredError):
        await bus.on(topic="test.topic", handler=handler_a)


async def test_duplicate_natural_key_raises_duplicate_error(bus: "Bus") -> None:
    """Registering the same name+topic twice raises DuplicateListenerError on the second call."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_a, name="my_listener")


async def test_duplicate_name_raises_value_error(bus: "Bus") -> None:
    """Two listeners with same name+topic raise DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="x")
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_a, name="x")


async def test_name_disambiguates_otherwise_identical_keys(bus: "Bus") -> None:
    """Two registrations with the same handler+topic but different name= both succeed."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="listener_1")
        sub2 = await bus.on(topic="test.topic", handler=handler_a, name="listener_2")
        assert sub1.listener.identity.name == "listener_1"
        assert sub2.listener.identity.name == "listener_2"


async def test_different_handlers_same_topic_do_not_collide(bus: "Bus") -> None:
    """Two different handlers with different names on the same topic do not raise."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="handler_a_listener")
        await bus.on(topic="test.topic", handler=handler_b, name="handler_b_listener")


async def test_collision_detection_is_synchronous(bus: "Bus") -> None:
    """DuplicateListenerError is raised before add_listener is called a second time."""
    with mock_add_listener(bus) as add_mock:
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        call_count_after_first = add_mock.await_count

        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_a, name="my_listener")

        assert add_mock.await_count == call_count_after_first


async def test_listener_inherits_parent_app_key(bus: "Bus") -> None:
    """Bus.on() sets listener.app_key from self.parent.app_key, not from Bus itself."""
    with mock_add_listener(bus):
        sub = await bus.on(topic="test.identity", handler=handler_a, name="test_identity")
        assert sub.listener.identity.app_key == "test_app"
        assert sub.listener.identity.app_key != bus.app_key


async def test_listener_inherits_parent_source_tier(bus: "Bus") -> None:
    """Bus.on() sets listener.source_tier from self.parent.source_tier."""
    with mock_add_listener(bus):
        sub = await bus.on(topic="test.tier", handler=handler_a, name="test_tier")
        assert sub.listener.identity.source_tier == "app"


async def test_listener_inherits_parent_instance_index(bus: "Bus") -> None:
    """Bus.on() sets listener.instance_index from self.parent.index."""
    bus.parent.index = 3
    with mock_add_listener(bus):
        sub = await bus.on(topic="test.index", handler=handler_a, name="test_index")
        assert sub.listener.identity.instance_index == 3
    bus.parent.index = 0


async def test_framework_bus_inherits_framework_tier(hassette_with_bus: "Hassette") -> None:
    """A Bus owned by a framework Resource inherits source_tier='framework'."""
    b = hassette_with_bus._bus
    assert b is not None
    with mock_add_listener(b):
        sub = await b.on(topic="test.fw", handler=handler_a, name="test_fw")
        assert sub.listener.identity.source_tier == "framework"
        assert sub.listener.identity.app_key.startswith("__hassette__.")


def test_bus_requires_parent() -> None:
    """Bus.__init__ raises AssertionError when parent is None."""
    mock_hassette = Mock()
    mock_hassette.bus_service = Mock()
    with pytest.raises(AssertionError, match="Bus requires a parent"):
        Bus(mock_hassette, parent=None)


async def test_source_tier_assertion_rejects_invalid_value(bus: "Bus") -> None:
    """Bus.on() raises AssertionError for invalid source_tier values."""
    bus.parent.source_tier = "invalid"
    with mock_add_listener(bus), pytest.raises(AssertionError, match="Invalid source_tier"):
        await bus.on(topic="test.invalid", handler=handler_a, name="test_invalid")
    bus.parent.source_tier = "app"


async def test_registered_listeners_cleared_on_reinit(bus: "Bus") -> None:
    """_registered_listeners is cleared at the start of on_initialize() to prevent stale collisions."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert len(bus._registered_listeners) == 1

        await bus.on_initialize()
        assert len(bus._registered_listeners) == 0

        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert len(bus._registered_listeners) == 1
