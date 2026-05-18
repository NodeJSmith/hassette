"""T02: Tests for Bus.on() / _on_internal() split and Subscription.registration_task.

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
import typing
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest

from hassette.bus.listeners import Subscription
from hassette.event_handling import predicates as P

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
    """Function-scoped bus harness for isolation between tests."""
    async with hassette_harness(test_config).with_bus() as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus with a mock parent that has an app_key."""
    b = hassette_with_bus._bus  # pyright: ignore[reportReturnType]
    mock_parent = Mock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.unique_name = "test_app.0"
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestApp"
    b.parent = mock_parent
    return b  # pyright: ignore[reportReturnType]


async def _handler(event) -> None:
    pass


# ---------------------------------------------------------------------------
# FR#7 / AC#6: Bus.on() must NOT accept internal parameters
# ---------------------------------------------------------------------------


def test_bus_on_signature_has_no_internal_params() -> None:
    """FR#7: Bus.on() signature contains no internal parameters."""
    from hassette.bus.bus import Bus

    sig = inspect.signature(Bus.on)
    param_names = set(sig.parameters.keys())

    forbidden = {"is_attribute_listener", "hold_preds", "entity_id", "immediate", "duration", "priority"}
    present = forbidden & param_names
    assert not present, f"Bus.on() must not have internal params, but found: {present}"


def test_bus_on_rejects_is_attribute_listener_keyword(bus: "Bus") -> None:
    """AC#6: Calling Bus.on(is_attribute_listener=True) raises TypeError."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        with pytest.raises(TypeError):
            bus.on(  # pyright: ignore[reportCallIssue]
                topic="test.topic",
                handler=_handler,
                is_attribute_listener=True,
            )
    finally:
        bus.bus_service.add_listener = original_add


def test_bus_on_rejects_hold_preds_keyword(bus: "Bus") -> None:
    """AC#6: Calling Bus.on(hold_preds=...) raises TypeError."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        with pytest.raises(TypeError):
            bus.on(  # pyright: ignore[reportCallIssue]
                topic="test.topic",
                handler=_handler,
                hold_preds=[],
            )
    finally:
        bus.bus_service.add_listener = original_add


def test_bus_on_rejects_entity_id_keyword(bus: "Bus") -> None:
    """AC#6: Calling Bus.on(entity_id=...) raises TypeError."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        with pytest.raises(TypeError):
            bus.on(  # pyright: ignore[reportCallIssue]
                topic="test.topic",
                handler=_handler,
                entity_id="light.test",
            )
    finally:
        bus.bus_service.add_listener = original_add


def test_bus_on_rejects_duration_keyword(bus: "Bus") -> None:
    """FR#7: Calling Bus.on(duration=...) raises TypeError."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        with pytest.raises(TypeError):
            bus.on(  # pyright: ignore[reportCallIssue]
                topic="test.topic",
                handler=_handler,
                duration=5.0,
            )
    finally:
        bus.bus_service.add_listener = original_add


def test_bus_on_rejects_priority_keyword(bus: "Bus") -> None:
    """FR#7: Calling Bus.on(priority=...) raises TypeError."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        with pytest.raises(TypeError):
            bus.on(  # pyright: ignore[reportCallIssue]
                topic="test.topic",
                handler=_handler,
                priority=10,
            )
    finally:
        bus.bus_service.add_listener = original_add


# ---------------------------------------------------------------------------
# FR#8 / AC#7: subscription.registration_task is an asyncio.Future
# ---------------------------------------------------------------------------


def test_subscription_has_registration_task_field() -> None:
    """Subscription dataclass has registration_task field."""
    fields = {f.name for f in Subscription.__dataclass_fields__.values()}  # pyright: ignore[reportAttributeAccessIssue]
    assert "registration_task" in fields, "Subscription must have registration_task field"


async def test_subscription_registration_task_is_future(bus: "Bus") -> None:
    """FR#8: subscription.registration_task is an asyncio.Future after Bus.on()."""
    add_listener_mock = Mock(return_value=asyncio.get_running_loop().create_future())
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        sub = bus.on(topic="test.topic", handler=_handler, name="reg_task_test")
        assert sub.registration_task is not None
        assert isinstance(sub.registration_task, asyncio.Future)
    finally:
        bus.bus_service.add_listener = original_add


@pytest.mark.asyncio
async def test_subscription_registration_task_resolves_with_none(bus: "Bus") -> None:
    """AC#7: await subscription.registration_task resolves with None."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()
    future.set_result(None)

    add_listener_mock = Mock(return_value=future)
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        sub = bus.on(topic="test.topic", handler=_handler, name="reg_task_resolves")
        result = await sub.registration_task
        assert result is None
    finally:
        bus.bus_service.add_listener = original_add


def test_subscription_default_none_registration_task() -> None:
    """Subscription can be constructed without registration_task (backward compat)."""
    listener_mock = MagicMock()
    sub = Subscription(listener=listener_mock, unsubscribe=lambda: None)
    assert sub.registration_task is None


# ---------------------------------------------------------------------------
# FR#11 / AC#11: hold_preds list is not mutated
# ---------------------------------------------------------------------------


async def test_hold_preds_not_mutated_in_subscribe(bus: "Bus") -> None:
    """FR#11 / AC#11: The hold_preds list passed to _subscribe() is not modified in place."""
    from hassette.event_handling import predicates as P

    original_pred = P.EntityMatches("light.test")
    original_hold_preds = [original_pred]
    original_id = id(original_hold_preds)
    original_len = len(original_hold_preds)

    add_listener_mock = Mock(return_value=asyncio.get_running_loop().create_future())
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        # _subscribe with a where= clause and hold_preds — this is the mutation-prone path
        bus._subscribe(
            method_name="test",
            topic="event.state_changed.light.test",
            handler=_handler,
            preds=[original_pred],
            where=P.StateDidChange(),  # this triggers the hold_preds.append path
            hold_preds=original_hold_preds,
        )
    finally:
        bus.bus_service.add_listener = original_add

    # list identity must be unchanged
    assert id(original_hold_preds) == original_id, "hold_preds list must not be replaced"
    # list length must be unchanged — no in-place append
    assert len(original_hold_preds) == original_len, "hold_preds list must not be mutated (appended to)"


async def test_hold_preds_none_no_mutation(bus: "Bus") -> None:
    """When hold_preds is None, no mutation attempt occurs."""
    add_listener_mock = Mock(return_value=asyncio.get_running_loop().create_future())
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        # Should not raise even with where= and hold_preds=None
        bus._subscribe(
            method_name="test",
            topic="event.state_changed.light.test",
            handler=_handler,
            preds=[P.EntityMatches("light.test")],
            where=P.StateDidChange(),
            hold_preds=None,
        )
    finally:
        bus.bus_service.add_listener = original_add


# ---------------------------------------------------------------------------
# Bus consumer paths: _listener_natural_key uses sub-struct paths
# ---------------------------------------------------------------------------


async def test_listener_natural_key_uses_identity_fields(bus: "Bus") -> None:
    """_listener_natural_key reads from listener.identity.* sub-struct paths."""
    add_listener_mock = Mock(return_value=asyncio.get_running_loop().create_future())
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        sub = bus.on(topic="test.topic", handler=_handler, name="key_test")
        key = bus._listener_natural_key(sub.listener)
        # Key should be (app_key, instance_index, handler_name, topic, name)
        assert key[0] == sub.listener.identity.app_key
        assert key[1] == sub.listener.identity.instance_index
        assert key[2] == sub.listener.identity.handler_name
        assert key[4] == sub.listener.identity.name
    finally:
        bus.bus_service.add_listener = original_add
