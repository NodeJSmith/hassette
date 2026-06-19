"""Tests for Bus.on() / _on_internal() split and synchronous registration.

Verify criteria:
- Bus.on() signature has no is_attribute_listener, hold_preds, entity_id, immediate, duration, priority
- No registration_task field on Subscription — db_id is the only identifier
- hold_preds list is not mutated after _subscribe()
- Bus.on(is_attribute_listener=True) raises TypeError
- sub.listener.db_id is a valid integer immediately after on() returns
- hold_preds list identity (id()) is unchanged after _subscribe()
"""

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
    """Bus.on() signature contains no internal parameters."""
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
async def test_bus_on_rejects_internal_keywords(bus: "Bus", forbidden_kwarg: str, value: object) -> None:
    """Bus.on() raises TypeError for internal-only parameters."""
    with mock_add_listener(bus), pytest.raises(TypeError):
        await bus.on(  # pyright: ignore[reportCallIssue]
            topic="test.topic",
            handler=handler,
            **{forbidden_kwarg: value},
        )


def test_subscription_has_no_registration_task_field() -> None:
    """Subscription dataclass has no registration_task field.

    Under synchronous registration, db_id is set before Subscription is returned.
    The registration_task completion signal is no longer needed.
    """
    fields = {f.name for f in Subscription.__dataclass_fields__.values()}  # pyright: ignore[reportAttributeAccessIssue]
    assert "registration_task" not in fields, "Subscription must not have registration_task field"


def test_subscription_default_construction() -> None:
    """Subscription can be constructed with listener and unsubscribe only."""
    listener_mock = MagicMock()
    sub = Subscription(listener=listener_mock, unsubscribe=lambda: None)
    assert sub.listener is listener_mock


async def test_hold_preds_not_mutated_in_subscribe(bus: "Bus") -> None:
    """The hold_preds list passed to _subscribe() is not modified in place."""
    original_pred = P.EntityMatches("light.test")
    original_hold_preds = [original_pred]
    original_id = id(original_hold_preds)
    original_len = len(original_hold_preds)

    with mock_add_listener(bus):
        await bus._subscribe(
            log_label="test",
            topic="event.state_changed.light.test",
            handler=handler,
            preds=[original_pred],
            where=P.StateDidChange(),
            hold_preds=original_hold_preds,
            name="hold_preds_mutation_test",
        )

    assert id(original_hold_preds) == original_id, "hold_preds list must not be replaced"
    assert len(original_hold_preds) == original_len, "hold_preds list must not be mutated (appended to)"


async def test_hold_preds_none_no_mutation(bus: "Bus") -> None:
    """When hold_preds is None, no mutation attempt occurs."""
    with mock_add_listener(bus):
        await bus._subscribe(
            log_label="test",
            topic="event.state_changed.light.test",
            handler=handler,
            preds=[P.EntityMatches("light.test")],
            where=P.StateDidChange(),
            hold_preds=None,
            name="hold_preds_none_test",
        )


async def test_listener_natural_key_uses_identity_fields(bus: "Bus") -> None:
    """_listener_natural_key returns (app_key, instance_index, name, topic) — canonical 4-tuple."""
    with mock_add_listener(bus):
        sub = await bus.on(topic="test.topic", handler=handler, name="key_test")
        key = bus._listener_natural_key(sub.listener)
        assert len(key) == 4
        assert key[0] == sub.listener.identity.app_key
        assert key[1] == sub.listener.identity.instance_index
        assert key[2] == sub.listener.identity.name
        assert key[3] == sub.listener.topic
