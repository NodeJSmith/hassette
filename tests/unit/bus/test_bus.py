"""Unit tests for Bus.on() name= parameter and collision detection.

Tests:
- name= parameter propagation to Listener
- Duplicate natural key raises ValueError synchronously in Bus.on()
- Duplicate name= raises ValueError synchronously in Bus.on()
- name= disambiguates otherwise-identical keys
- _registered_keys is cleared at start of initialization
"""

import typing
from typing import cast
from unittest.mock import Mock

import pytest

from hassette.bus.listeners import Subscription

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig
    from hassette.bus.bus import Bus
    from hassette.test_utils.harness import HassetteHarness


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def hassette_with_bus(
    hassette_harness: "typing.Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "typing.AsyncIterator[Hassette]":
    """Function-scoped bus harness for isolation between collision tests."""
    async with hassette_harness(test_config).with_bus() as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource with a mock parent that has an app_key.

    Collision detection is only active for buses owned by an App (app_key != "").
    We set a mock parent so the natural key is populated.
    """
    b = hassette_with_bus._bus  # pyright: ignore[reportReturnType]
    mock_parent = Mock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.unique_name = "test_app.0"
    b.parent = mock_parent
    return b  # pyright: ignore[reportReturnType]


# ---------------------------------------------------------------------------
# Handlers used across tests (must be named module-level functions)
# ---------------------------------------------------------------------------


async def _handler_a(event) -> None:
    pass


async def _handler_b(event) -> None:
    pass


# ---------------------------------------------------------------------------
# Tests — name= parameter propagation
# ---------------------------------------------------------------------------


def test_name_parameter_propagates_to_listener(bus: "Bus") -> None:
    """name='my_listener' passed to Bus.on() ends up on listener.name."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        subscription = bus.on(
            topic="test.topic",
            handler=_handler_a,
            name="my_listener",
        )
        assert isinstance(subscription, Subscription)
        assert subscription.listener.name == "my_listener"
    finally:
        bus.bus_service.add_listener = original_add


def test_name_none_by_default(bus: "Bus") -> None:
    """Without name=, listener.name is None."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        subscription = bus.on(
            topic="test.topic",
            handler=_handler_a,
        )
        assert subscription.listener.name is None
    finally:
        bus.bus_service.add_listener = original_add


# ---------------------------------------------------------------------------
# Tests — collision detection
# ---------------------------------------------------------------------------


def test_duplicate_natural_key_raises_value_error(bus: "Bus") -> None:
    """Registering the same handler+topic twice raises ValueError on the second call."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        bus.on(topic="test.topic", handler=_handler_a)
        with pytest.raises(ValueError, match="Duplicate listener"):
            bus.on(topic="test.topic", handler=_handler_a)
    finally:
        bus.bus_service.add_listener = original_add


def test_duplicate_name_raises_value_error(bus: "Bus") -> None:
    """Two listeners with same handler+topic and the same name= raise ValueError."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        bus.on(topic="test.topic", handler=_handler_a, name="x")
        with pytest.raises(ValueError, match="Duplicate listener"):
            bus.on(topic="test.topic", handler=_handler_a, name="x")
    finally:
        bus.bus_service.add_listener = original_add


def test_name_disambiguates_otherwise_identical_keys(bus: "Bus") -> None:
    """Two registrations with the same handler+topic but different name= both succeed."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        sub1 = bus.on(topic="test.topic", handler=_handler_a, name="listener_1")
        sub2 = bus.on(topic="test.topic", handler=_handler_a, name="listener_2")
        assert sub1.listener.name == "listener_1"
        assert sub2.listener.name == "listener_2"
    finally:
        bus.bus_service.add_listener = original_add


def test_different_handlers_same_topic_do_not_collide(bus: "Bus") -> None:
    """Two different handlers on the same topic are distinct and do not raise."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        bus.on(topic="test.topic", handler=_handler_a)
        bus.on(topic="test.topic", handler=_handler_b)  # must not raise
    finally:
        bus.bus_service.add_listener = original_add


def test_collision_detection_is_synchronous(bus: "Bus") -> None:
    """ValueError is raised synchronously in Bus.on() before add_listener is called a second time.

    Verifies that the error occurs at the Bus.on() call site (synchronous),
    not inside an async task spawned by bus_service.add_listener.
    """
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        bus.on(topic="test.topic", handler=_handler_a)
        call_count_after_first = add_listener_mock.call_count  # should be 1

        with pytest.raises(ValueError, match="Duplicate listener"):
            bus.on(topic="test.topic", handler=_handler_a)

        # add_listener must NOT have been called again
        assert add_listener_mock.call_count == call_count_after_first
    finally:
        bus.bus_service.add_listener = original_add


def test_registered_keys_cleared_on_reinit(bus: "Bus") -> None:
    """_registered_keys is cleared at the start of on_initialize() to prevent stale collisions.

    Simulates a partial init failure: after registering a listener, we manually clear the
    _registered_keys set (as on_initialize() would), and verify the same handler+topic
    can be registered again without raising.
    """
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        bus.on(topic="test.topic", handler=_handler_a)
        assert len(bus._registered_keys) == 1

        # Simulate on_initialize() clearing the set
        bus._registered_keys.clear()

        # Same registration must succeed after the clear
        bus.on(topic="test.topic", handler=_handler_a)
        assert len(bus._registered_keys) == 1
    finally:
        bus.bus_service.add_listener = original_add
