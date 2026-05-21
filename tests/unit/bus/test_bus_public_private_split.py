"""Tests for Bus.on() / _on_internal() split and Subscription.registration_task.

Verify criteria:
- FR#7: Bus.on() signature has no is_attribute_listener, hold_preds, entity_id, immediate, duration, priority
- FR#8: subscription.registration_task is an asyncio.Future[None] that resolves after add_listener
- FR#11: hold_preds list is not mutated after _subscribe()
- AC#6: Bus.on(is_attribute_listener=True) raises TypeError
- AC#7: await subscription.registration_task resolves with None
- AC#11: hold_preds list identity (id()) is unchanged after _subscribe()
"""

import asyncio
import inspect
from unittest.mock import MagicMock

import pytest

from hassette.bus.bus import Bus
from hassette.bus.listeners import Subscription
from hassette.event_handling import predicates as P

from .conftest import mock_add_listener


async def handler(event) -> None:
    pass


def test_bus_on_signature_has_no_internal_params() -> None:
    """FR#7: Bus.on() signature contains no internal parameters."""
    sig = inspect.signature(Bus.on)
    param_names = set(sig.parameters.keys())

    forbidden = {"is_attribute_listener", "hold_preds", "entity_id", "immediate", "duration", "priority"}
    present = forbidden & param_names
    assert not present, f"Bus.on() must not have internal params, but found: {present}"


@pytest.mark.parametrize(
    ("forbidden_kwarg", "value"),
    [
        ("is_attribute_listener", True),
        ("hold_preds", []),
        ("entity_id", "light.test"),
        ("duration", 5.0),
        ("priority", 10),
    ],
)
def test_bus_on_rejects_internal_keywords(bus: "Bus", forbidden_kwarg: str, value: object) -> None:
    """AC#6 / FR#7: Bus.on() raises TypeError for internal-only parameters."""
    with mock_add_listener(bus), pytest.raises(TypeError):
        bus.on(  # pyright: ignore[reportCallIssue]
            topic="test.topic",
            handler=handler,
            **{forbidden_kwarg: value},
        )


def test_subscription_has_registration_task_field() -> None:
    """Subscription dataclass has registration_task field."""
    fields = {f.name for f in Subscription.__dataclass_fields__.values()}  # pyright: ignore[reportAttributeAccessIssue]
    assert "registration_task" in fields, "Subscription must have registration_task field"


async def test_subscription_registration_task_is_future(bus: "Bus") -> None:
    """FR#8: subscription.registration_task is an asyncio.Future after Bus.on()."""
    future = asyncio.get_running_loop().create_future()
    with mock_add_listener(bus) as add_mock:
        add_mock.return_value = future
        sub = bus.on(topic="test.topic", handler=handler, name="reg_task_test")
        assert sub.registration_task is not None
        assert isinstance(sub.registration_task, asyncio.Future)


async def test_subscription_registration_task_resolves_with_none(bus: "Bus") -> None:
    """AC#7: await subscription.registration_task resolves with None."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()
    future.set_result(None)

    with mock_add_listener(bus) as add_mock:
        add_mock.return_value = future
        sub = bus.on(topic="test.topic", handler=handler, name="reg_task_resolves")
        result = await sub.registration_task
        assert result is None


def test_subscription_default_none_registration_task() -> None:
    """Subscription can be constructed without registration_task (backward compat)."""
    listener_mock = MagicMock()
    sub = Subscription(listener=listener_mock, unsubscribe=lambda: None)
    assert sub.registration_task is None


async def test_hold_preds_not_mutated_in_subscribe(bus: "Bus") -> None:
    """FR#11 / AC#11: The hold_preds list passed to _subscribe() is not modified in place."""
    original_pred = P.EntityMatches("light.test")
    original_hold_preds = [original_pred]
    original_id = id(original_hold_preds)
    original_len = len(original_hold_preds)

    future = asyncio.get_running_loop().create_future()
    with mock_add_listener(bus) as add_mock:
        add_mock.return_value = future
        bus._subscribe(
            method_name="test",
            topic="event.state_changed.light.test",
            handler=handler,
            preds=[original_pred],
            where=P.StateDidChange(),
            hold_preds=original_hold_preds,
        )

    assert id(original_hold_preds) == original_id, "hold_preds list must not be replaced"
    assert len(original_hold_preds) == original_len, "hold_preds list must not be mutated (appended to)"


async def test_hold_preds_none_no_mutation(bus: "Bus") -> None:
    """When hold_preds is None, no mutation attempt occurs."""
    future = asyncio.get_running_loop().create_future()
    with mock_add_listener(bus) as add_mock:
        add_mock.return_value = future
        bus._subscribe(
            method_name="test",
            topic="event.state_changed.light.test",
            handler=handler,
            preds=[P.EntityMatches("light.test")],
            where=P.StateDidChange(),
            hold_preds=None,
        )


async def test_listener_natural_key_uses_identity_fields(bus: "Bus") -> None:
    """_listener_natural_key reads from listener.identity.* sub-struct paths."""
    future = asyncio.get_running_loop().create_future()
    with mock_add_listener(bus) as add_mock:
        add_mock.return_value = future
        sub = bus.on(topic="test.topic", handler=handler, name="key_test")
        key = bus._listener_natural_key(sub.listener)
        assert key[0] == sub.listener.identity.app_key
        assert key[1] == sub.listener.identity.instance_index
        assert key[2] == sub.listener.identity.handler_name
        assert key[4] == sub.listener.identity.name
