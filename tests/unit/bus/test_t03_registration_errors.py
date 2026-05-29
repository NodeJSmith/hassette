"""Tests for T03: name= required validation and DuplicateListenerError detection.

Verify criteria:
- FR#3: Registering without name= raises ListenerNameRequiredError
- FR#20: Two handlers with same name+topic raises DuplicateListenerError
- AC#6: Error message includes the handler method name and topic
- AC#14: Error message names both the duplicate name and the topic
"""

import typing

import pytest

from hassette.exceptions import DuplicateListenerError, ListenerNameRequiredError

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus


async def handler_a(event) -> None:
    pass


async def handler_b(event) -> None:
    pass


# ---------------------------------------------------------------------------
# FR#3 / AC#6 — ListenerNameRequiredError
# ---------------------------------------------------------------------------


async def test_registering_without_name_raises(bus: "Bus") -> None:
    """FR#3: Bus.on() without name= raises ListenerNameRequiredError."""
    with mock_add_listener(bus), pytest.raises(ListenerNameRequiredError):
        await bus.on(topic="test.topic", handler=handler_a)


async def test_name_required_error_has_handler_and_topic_attrs(bus: "Bus") -> None:
    """AC#6: ListenerNameRequiredError carries handler_method and topic as instance attrs."""
    with mock_add_listener(bus), pytest.raises(ListenerNameRequiredError) as exc_info:
        await bus.on(topic="test.topic.entity", handler=handler_a)

    err = exc_info.value
    assert hasattr(err, "handler_method"), "ListenerNameRequiredError must have handler_method attr"
    assert hasattr(err, "topic"), "ListenerNameRequiredError must have topic attr"
    assert err.topic == "test.topic.entity"
    # handler_method includes the fully-qualified name
    assert "handler_a" in err.handler_method


async def test_name_required_error_message_includes_handler_and_topic(bus: "Bus") -> None:
    """AC#6: Error message text includes handler name and topic for clear diagnosis."""
    with mock_add_listener(bus), pytest.raises(ListenerNameRequiredError) as exc_info:
        await bus.on(topic="light.kitchen", handler=handler_a)

    msg = str(exc_info.value)
    assert "light.kitchen" in msg
    assert "handler_a" in msg


async def test_on_state_change_without_name_raises(bus: "Bus") -> None:
    """FR#3: on_state_change() without name= also raises ListenerNameRequiredError."""
    with mock_add_listener(bus), pytest.raises(ListenerNameRequiredError):
        await bus.on_state_change("light.kitchen", handler=handler_a)


async def test_providing_name_does_not_raise(bus: "Bus") -> None:
    """FR#3 negative: providing name= succeeds without error."""
    with mock_add_listener(bus):
        # Should not raise
        sub = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert sub is not None


# ---------------------------------------------------------------------------
# FR#20 / AC#14 — DuplicateListenerError
# ---------------------------------------------------------------------------


async def test_duplicate_name_and_topic_raises(bus: "Bus") -> None:
    """FR#20: Registering two handlers with the same name+topic raises DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="kitchen_light")
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_b, name="kitchen_light")


async def test_duplicate_error_has_correct_attrs(bus: "Bus") -> None:
    """AC#14: DuplicateListenerError carries name, topic, existing_handler, duplicate_handler."""
    with mock_add_listener(bus):
        await bus.on(topic="light.kitchen", handler=handler_a, name="kitchen_light")
        with pytest.raises(DuplicateListenerError) as exc_info:
            await bus.on(topic="light.kitchen", handler=handler_b, name="kitchen_light")

    err = exc_info.value
    assert err.name == "kitchen_light"
    assert err.topic == "light.kitchen"
    assert "handler_a" in err.existing_handler
    assert "handler_b" in err.duplicate_handler


async def test_duplicate_error_message_names_both_name_and_topic(bus: "Bus") -> None:
    """AC#14: Error message includes both the duplicate name and the topic."""
    with mock_add_listener(bus):
        await bus.on(topic="light.kitchen", handler=handler_a, name="kitchen_light")
        with pytest.raises(DuplicateListenerError) as exc_info:
            await bus.on(topic="light.kitchen", handler=handler_b, name="kitchen_light")

    msg = str(exc_info.value)
    assert "kitchen_light" in msg
    assert "light.kitchen" in msg


async def test_same_name_different_topics_no_error(bus: "Bus") -> None:
    """Same name with different topics is not a collision — topic is part of the key."""
    with mock_add_listener(bus):
        await bus.on(topic="light.kitchen", handler=handler_a, name="my_listener")
        # Different topic — must not raise
        await bus.on(topic="light.bedroom", handler=handler_b, name="my_listener")


async def test_once_listeners_exempt_from_duplicate_error(bus: "Bus") -> None:
    """Once-listeners with duplicate name+topic are exempt from DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)
        # Second once-listener with same name+topic must not raise
        await bus.on(topic="test.topic", handler=handler_b, name="once_listener", once=True)


# ---------------------------------------------------------------------------
# _listener_natural_key canonical shape
# ---------------------------------------------------------------------------


async def test_listener_natural_key_is_canonical_4_tuple(bus: "Bus") -> None:
    """_listener_natural_key returns exactly (app_key, instance_index, name, topic)."""
    with mock_add_listener(bus):
        sub = await bus.on(topic="hass.state_changed.light.kitchen", handler=handler_a, name="kitchen")
        key = bus._listener_natural_key(sub.listener)

    assert len(key) == 4, f"Natural key must be a 4-tuple, got {len(key)}-tuple: {key}"

    app_key, instance_index, name, topic = key
    assert app_key == sub.listener.identity.app_key
    assert instance_index == sub.listener.identity.instance_index
    assert name == "kitchen"
    assert topic == "hass.state_changed.light.kitchen"
