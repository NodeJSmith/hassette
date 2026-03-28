# pyright: reportInvalidTypeArguments=none, reportArgumentType=none


import asyncio
import contextlib
import typing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hassette import RawStateChangeEvent
from hassette.bus.listeners import Subscription
from hassette.event_handling.conditions import IsOrContains
from hassette.event_handling.predicates import (
    AllOf,
    AttrDidChange,
    EntityMatches,
    Guard,
    ServiceDataWhere,
    StateDidChange,
)
from hassette.events.base import Event
from hassette.test_utils import create_call_service_event, create_state_change_event, wait_for
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource for the running Hassette harness."""
    return hassette_with_bus._bus


@pytest.mark.parametrize(
    ("once", "debounce", "throttle"),
    [
        (False, 0.1, None),
        (False, None, 0.1),
        (True, None, None),
        (False, None, None),
    ],
)
async def test_on_registers_listener_and_supports_unsubscribe(
    bus: "Bus", once: bool, debounce: float | None, throttle: float | None
) -> None:
    """Bus.on wraps handlers, normalises predicates, and wires subscription cleanup."""

    async def handler(event):  # noqa
        await asyncio.sleep(0)

    add_listener_mock = Mock()
    remove_listener_mock = Mock()
    original_service = bus.bus_service
    original_remove = bus.remove_listener
    bus.bus_service = Mock(add_listener=add_listener_mock)
    bus.remove_listener = remove_listener_mock

    try:
        subscription = bus.on(
            topic="demo.topic",
            handler=handler,
            where=[lambda _: True],
            kwargs={"suffix": "!"},
            once=once,
            debounce=debounce,
            throttle=throttle,
        )

        assert isinstance(subscription, Subscription)
        add_listener_mock.assert_called_once()
        listener = add_listener_mock.call_args.args[0]

        assert listener.topic == "demo.topic"
        assert listener.orig_handler is handler
        assert asyncio.iscoroutinefunction(listener._async_handler)
        assert listener.kwargs == {"suffix": "!"}
        assert listener.once is once
        assert isinstance(listener.predicate, AllOf)

        subscription.unsubscribe()
        remove_listener_mock.assert_called_once_with(listener)
    finally:
        bus.bus_service = original_service
        bus.remove_listener = original_remove


async def test_on_state_change_builds_predicates(bus: "Bus") -> None:
    """on_state_change composes entity, state, and extra predicates."""

    def handler(event: Event) -> None:
        pass

    subscription = bus.on_state_change(
        "sensor.kitchen",
        handler=handler,
        changed_from="off",
        changed_to="on",
        kwargs=None,
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)
    preds = listener.predicate.predicates
    assert any(isinstance(pred, EntityMatches) for pred in preds)
    assert any(isinstance(pred, StateDidChange) for pred in preds)

    matching_event = create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on")
    assert listener.predicate(matching_event) is True

    non_matching_event = create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="off")
    assert listener.predicate(non_matching_event) is False


async def test_on_attribute_change_targets_attribute(bus: "Bus") -> None:
    """on_attribute_change adds AttrDidChange predicate for the supplied attribute."""

    def handler(event: Event) -> None:
        pass

    subscription = bus.on_attribute_change(
        "light.office",
        "brightness",
        handler=handler,
        changed_from=100,
        changed_to=200,
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)
    attr_predicates = [pred for pred in listener.predicate.predicates if isinstance(pred, AttrDidChange)]
    assert attr_predicates, "Expected AttrDidChange predicate to be included"
    attr_pred = attr_predicates[0]
    assert attr_pred.attr_name == "brightness"

    matching_event = create_state_change_event(
        entity_id="light.office",
        old_value=0,
        new_value=0,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )
    assert listener.predicate(matching_event) is True

    non_matching_event = create_state_change_event(
        entity_id="light.office",
        old_value=0,
        new_value=0,
        old_attrs={"brightness": 90},
        new_attrs={"brightness": 200},
    )
    assert listener.predicate(non_matching_event) is False


async def test_on_call_service_handles_mapping_predicates(bus: "Bus") -> None:
    """on_call_service composes domain/service guards with ServiceDataWhere and extra predicates."""

    def handler(event: Event) -> None:
        pass

    extra_guard = Guard(lambda event: event.payload.data.service_data.get("brightness", 0) > 150)
    subscription = bus.on_call_service(
        domain="light",
        service="turn_on",
        handler=handler,
        where=[{"entity_id": IsOrContains("light.kitchen")}, extra_guard],
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)

    assert any(isinstance(pred, ServiceDataWhere) for pred in listener.predicate.predicates)

    matching_event = create_call_service_event(
        domain="light",
        service="turn_on",
        service_data={"entity_id": ["light.kitchen"], "brightness": 255},
    )
    assert listener.predicate(matching_event) is True

    wrong_entity_event = create_call_service_event(
        domain="light",
        service="turn_on",
        service_data={"entity_id": ["light.other"], "brightness": 255},
    )
    assert listener.predicate(wrong_entity_event) is False

    wrong_service_event = create_call_service_event(
        domain="light",
        service="turn_off",
        service_data={"entity_id": ["light.kitchen"], "brightness": 255},
    )
    assert listener.predicate(wrong_service_event) is False


async def test_once_listener_removed(hassette_with_bus: "Hassette") -> None:
    """Listeners registered with once=True are removed after the first invocation."""
    hassette = hassette_with_bus

    received_payloads: list[int] = []
    first_invocation = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:
        received_payloads.append(event.payload.value)
        hassette_with_bus.task_bucket.post_to_loop(first_invocation.set)

    hassette._bus.on(topic="custom.once", handler=handler, once=True)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=1)))

    await asyncio.wait_for(first_invocation.wait(), timeout=1)
    await wait_for(lambda: len(received_payloads) == 1, desc="once handler fired")

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=2)))

    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks cleaned up")

    assert received_payloads == [1], f"Expected handler to fire once with payload 1, got {received_payloads}"


async def test_once_listener_fires_exactly_once_under_rapid_dispatch(hassette_with_bus: "Hassette") -> None:
    """Two rapid events must not cause a once=True handler to fire twice.

    Regression test for the double-fire race: dispatch spawns tasks per listener,
    and without a _fired guard, both tasks invoke the handler before either removes it.
    """
    hassette = hassette_with_bus

    call_count = 0

    async def handler(_event: Event[SimpleNamespace]) -> None:
        nonlocal call_count
        call_count += 1
        # Yield to let the second dispatch task run concurrently
        await asyncio.sleep(0)

    hassette._bus.on(topic="custom.rapid", handler=handler, once=True)

    # Send two events back-to-back — both enter dispatch before removal task executes
    ev1 = Event(topic="custom.rapid", payload=SimpleNamespace(value=1))
    ev2 = Event(topic="custom.rapid", payload=SimpleNamespace(value=2))
    await hassette.send_event("custom.rapid", ev1)
    await hassette.send_event("custom.rapid", ev2)

    # Wait for at least one handler invocation, then let tasks drain
    await wait_for(lambda: call_count >= 1, desc="once handler fired at least once")
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks cleaned up")

    assert call_count == 1, f"once=True handler should fire exactly once, fired {call_count} times"


async def test_bus_background_tasks_cleanup(hassette_with_bus: "Hassette") -> None:
    """Bus cleans up background tasks after a once handler completes."""
    hassette = hassette_with_bus

    event_received = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:  # noqa
        hassette_with_bus.task_bucket.post_to_loop(event_received.set)

    hassette._bus.on(topic="custom.cleanup", handler=handler, once=True)

    await hassette.send_event("custom.cleanup", Event(topic="custom.cleanup", payload=SimpleNamespace(value=9)))

    await asyncio.wait_for(event_received.wait(), timeout=1)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks cleaned up")

    assert len(hassette._bus.task_bucket) == 0, (
        f"Expected no leftover bus tasks, found {len(hassette._bus.task_bucket)}"
    )


async def test_bus_uses_kwargs(hassette_with_bus: "Hassette") -> None:
    """Handlers receive configured args and kwargs when invoked."""
    hassette = hassette_with_bus

    formatted_messages: list[str] = []
    event_processed = asyncio.Event()

    def handler(event: Event[SimpleNamespace], suffix: str) -> None:
        formatted_messages.append(f"Value: {event.payload.value}{suffix}")
        hassette_with_bus.task_bucket.post_to_loop(event_processed.set)

    hassette._bus.on(topic="custom.args", handler=handler, kwargs={"suffix": "!"})

    await hassette.send_event("custom.args", Event(topic="custom.args", payload=SimpleNamespace(value="Test")))

    await asyncio.wait_for(event_processed.wait(), timeout=1)

    assert formatted_messages == ["Value: Test!"], (
        f"Expected handler to receive formatted value, got {formatted_messages}"
    )


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.kitchen", "sensor.kitchen"),
        ("sensor.*", {"sensor.kitchen", "sensor.living_room"}),
        ("*.kitchen", {"sensor.kitchen", "light.kitchen"}),
        ("*kitchen*", {"sensor.kitchen", "light.kitchen"}),
        ("sensor.kitch?n", "sensor.kitchen"),
        ("senso?.kit*en", "sensor.kitchen"),
        ("*", {"sensor.kitchen", "light.living_room", "switch.garage", "light.kitchen", "sensor.living_room"}),
    ],
)
async def test_state_change_handles_globs(
    hassette_with_bus: "Hassette", entity_id: str, expected: str | set[str]
) -> None:
    """Bus matches state change with glob patterns correctly."""
    hassette = hassette_with_bus

    expected = {expected} if isinstance(expected, str) else expected

    received_entity_ids: list[str] = []
    events_processed = asyncio.Event()

    def handler(event: RawStateChangeEvent) -> None:
        received_entity_ids.append(event.payload.entity_id)
        if set(received_entity_ids) == expected:
            hassette_with_bus.task_bucket.post_to_loop(events_processed.set)

    hassette._bus.on_state_change(entity_id=entity_id, handler=handler)

    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="light.living_room", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="sensor.living_room", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="switch.garage", old_value="off", new_value="on"),
    )

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(events_processed.wait(), timeout=0.2)

    actual = set(received_entity_ids)

    assert actual == expected, f"Expected handler to receive {expected}, got {actual}"


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.kitchen", "sensor.kitchen"),
        ("sensor.*", {"sensor.kitchen", "sensor.living_room"}),
        ("*.kitchen", {"sensor.kitchen", "light.kitchen"}),
        ("*kitchen*", {"sensor.kitchen", "light.kitchen"}),
        ("sensor.kitch?n", "sensor.kitchen"),
        ("senso?.kit*en", "sensor.kitchen"),
        ("*", {"sensor.kitchen", "light.living_room", "switch.garage", "light.kitchen", "sensor.living_room"}),
    ],
)
async def test_attribute_change_handles_globs(
    hassette_with_bus: "Hassette", entity_id: str, expected: str | set[str]
) -> None:
    """Bus matches attribute change topics with glob patterns correctly."""
    hassette = hassette_with_bus

    expected = {expected} if isinstance(expected, str) else expected

    received_entity_ids: list[str] = []
    events_processed = asyncio.Event()

    def handler(event: RawStateChangeEvent) -> None:
        received_entity_ids.append(event.payload.entity_id)
        if set(received_entity_ids) == expected:
            hassette_with_bus.task_bucket.post_to_loop(events_processed.set)

    hassette._bus.on_attribute_change(entity_id=entity_id, attr="friendly_name", handler=handler)

    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="sensor.kitchen", old_value="off", new_value="on", new_attrs={"friendly_name": "Kitchen Sensor"}
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="light.kitchen", old_value="off", new_value="on", new_attrs={"friendly_name": "Kitchen Light"}
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="light.living_room",
            old_value="off",
            new_value="on",
            new_attrs={"friendly_name": "Living Room Light"},
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="sensor.living_room",
            old_value="off",
            new_value="on",
            new_attrs={"friendly_name": "Living Room Sensor"},
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="switch.garage", old_value="off", new_value="on", new_attrs={"friendly_name": "Garage Switch"}
        ),
    )

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(events_processed.wait(), timeout=0.2)

    actual = set(received_entity_ids)

    assert actual == expected, f"Expected handler to receive {expected}, got {actual}"


async def test_listener_registration_spawns_background_task(hassette_with_bus: "Hassette") -> None:
    """Listener registration spawns a background task to persist the listener via executor.

    The Bus parent must have app_key set so the listener has a non-empty app_key
    and triggers DB registration (empty app_key skips registration).
    """
    hassette = hassette_with_bus

    # Set app_key on the Bus's parent so the listener triggers DB registration
    bus = hassette._bus
    assert bus is not None
    bus.parent.app_key = "test_app"  # type: ignore[union-attr]
    bus.parent.index = 0  # type: ignore[union-attr]
    try:

        def handler(event: Event) -> None:
            pass

        subscription = bus.on_state_change("sensor.eager_test", handler=handler)
        listener = subscription.listener

        # Allow the add_listener registration task to complete
        await asyncio.sleep(0.05)

        # The mock executor's register_listener should have been called
        hassette._bus_service._executor.register_listener.assert_called()
        # db_id should be set by the background task (mock returns 42)
        assert listener.db_id == 42
    finally:
        # Clean up: reset app_key and index so other tests using this module-scoped fixture aren't affected
        bus.parent.app_key = ""  # type: ignore[union-attr]
        bus.parent.index = 0  # type: ignore[union-attr]


async def test_can_subscribe_to_all_state_change_events(hassette_with_bus: "Hassette") -> None:
    """Bus can subscribe to all state change events."""
    hassette = hassette_with_bus

    expected = {"sensor.kitchen", "light.living_room", "switch.garage"}
    received_entity_ids: list[str] = []
    events_processed = asyncio.Event()

    def handler(event: RawStateChangeEvent) -> None:
        received_entity_ids.append(event.payload.entity_id)
        if set(received_entity_ids) == expected:
            hassette_with_bus.task_bucket.post_to_loop(events_processed.set)

    hassette._bus.on_state_change(entity_id="*", handler=handler)

    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="light.living_room", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="switch.garage", old_value="off", new_value="on"),
    )

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(events_processed.wait(), timeout=0.2)

    actual = set(received_entity_ids)

    assert actual == expected, f"Expected handler to receive {expected}, got {actual}"


async def test_dispatch_calls_executor(hassette_with_bus: "Hassette") -> None:
    """_dispatch() delegates to the executor for app-owned listeners (db_id set)."""
    from hassette.core.commands import InvokeHandler
    from hassette.events.base import Event

    hassette = hassette_with_bus
    event_handled = asyncio.Event()

    def handler(_event: Event) -> None:
        hassette_with_bus.task_bucket.post_to_loop(event_handled.set)

    hassette._bus.on(topic="custom.exec_test", handler=handler)

    # Simulate an app-owned listener by setting db_id (internal listeners have db_id=None)
    # Wait for the listener to be added to the router
    await asyncio.sleep(0.05)
    all_listeners = await hassette._bus_service.router.get_topic_listeners("custom.exec_test")
    for listener in all_listeners:
        if listener.db_id is None:
            listener.mark_registered(99)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    payload_event = Event(topic="custom.exec_test", payload="test-payload")
    await hassette.send_event("custom.exec_test", payload_event)

    await asyncio.wait_for(event_handled.wait(), timeout=1.0)

    executor.execute.assert_called()
    call_args = executor.execute.call_args_list
    assert len(call_args) >= 1
    cmd = call_args[-1].args[0]
    assert isinstance(cmd, InvokeHandler), f"Expected InvokeHandler, got {type(cmd)}"


async def test_dispatch_internal_handler_bypasses_executor(hassette_with_bus: "Hassette") -> None:
    """Internal listeners (db_id=None) invoke directly, bypassing CommandExecutor."""
    from hassette.events.base import Event

    hassette = hassette_with_bus
    event_handled = asyncio.Event()

    def handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(event_handled.set)

    # Internal bus (no app_key) — listener gets db_id=None
    hassette._bus.on(topic="custom.internal_test", handler=handler)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    payload_event = Event(topic="custom.internal_test", payload="test-payload")
    await hassette.send_event("custom.internal_test", payload_event)

    await asyncio.wait_for(event_handled.wait(), timeout=1.0)

    # Executor should NOT have been called for internal handlers
    executor.execute.assert_not_called()


async def test_dispatch_internal_handler_logs_error_on_exception(hassette_with_bus: "Hassette") -> None:
    """Internal handler exceptions are logged, not propagated or sent to CommandExecutor."""
    from hassette.events.base import Event

    hassette = hassette_with_bus
    error_raised = asyncio.Event()

    def failing_handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(error_raised.set)
        raise ValueError("test error from internal handler")

    hassette._bus.on(topic="custom.error_test", handler=failing_handler)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    payload_event = Event(topic="custom.error_test", payload="test-payload")
    await hassette.send_event("custom.error_test", payload_event)

    await asyncio.wait_for(error_raised.wait(), timeout=1.0)
    # Allow the exception to propagate through the dispatch path
    await asyncio.sleep(0.05)

    # Executor should NOT have been called
    executor.execute.assert_not_called()


async def test_debounced_dispatch_coalesces_events_through_executor(hassette_with_bus: "Hassette") -> None:
    """Debounced app-owned listener coalesces rapid events and routes through CommandExecutor.

    This tests the full pipeline: _dispatch -> _make_tracked_invoke_fn -> rate_limiter.call(execute_fn) ->
    debounce delay -> execute_fn -> CommandExecutor.execute(InvokeHandler).
    """
    from hassette.core.commands import InvokeHandler
    from hassette.events.base import Event

    hassette = hassette_with_bus
    event_handled = asyncio.Event()

    def handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(event_handled.set)

    hassette._bus.on(topic="custom.debounce_test", handler=handler, debounce=0.1)

    # Wait for listener registration, then set db_id to make it app-owned
    await asyncio.sleep(0.05)
    all_listeners = await hassette._bus_service.router.get_topic_listeners("custom.debounce_test")
    for listener in all_listeners:
        if listener.db_id is None:
            listener.mark_registered(42)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    # Send 3 rapid events — debounce should coalesce into 1 executor call
    for i in range(3):
        await hassette.send_event("custom.debounce_test", Event(topic="custom.debounce_test", payload=f"event-{i}"))

    # Wait for debounce to fire
    await asyncio.wait_for(event_handled.wait(), timeout=1.0)
    await asyncio.sleep(0.05)  # Let tasks drain

    # Executor should have been called exactly once (debounce coalesced)
    assert executor.execute.call_count == 1, (
        f"Expected executor called once (debounce coalesce), got {executor.execute.call_count}"
    )
    cmd = executor.execute.call_args.args[0]
    assert isinstance(cmd, InvokeHandler)
    assert cmd.listener_id == 42


async def test_throttled_dispatch_drops_events_through_executor(hassette_with_bus: "Hassette") -> None:
    """Throttled app-owned listener fires once and drops subsequent events within the window.

    This tests the full pipeline: _dispatch -> _make_tracked_invoke_fn -> rate_limiter.call(execute_fn) ->
    throttle check -> execute_fn -> CommandExecutor.execute(InvokeHandler).
    """
    from hassette.core.commands import InvokeHandler
    from hassette.events.base import Event

    hassette = hassette_with_bus
    event_handled = asyncio.Event()

    def handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(event_handled.set)

    hassette._bus.on(topic="custom.throttle_test", handler=handler, throttle=5.0)

    # Wait for listener registration, then set db_id to make it app-owned
    await asyncio.sleep(0.05)
    all_listeners = await hassette._bus_service.router.get_topic_listeners("custom.throttle_test")
    for listener in all_listeners:
        if listener.db_id is None:
            listener.mark_registered(77)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    # Send 3 rapid events — throttle should allow only the first
    for i in range(3):
        await hassette.send_event("custom.throttle_test", Event(topic="custom.throttle_test", payload=f"event-{i}"))

    await asyncio.wait_for(event_handled.wait(), timeout=1.0)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks cleaned up")

    # Executor should have been called exactly once (throttle dropped the rest)
    assert executor.execute.call_count == 1, (
        f"Expected executor called once (throttle), got {executor.execute.call_count}"
    )
    cmd = executor.execute.call_args.args[0]
    assert isinstance(cmd, InvokeHandler)
    assert cmd.listener_id == 77


# ---------------------------------------------------------------------------
# Internal dispatch (db_id=None) with rate limiting
# ---------------------------------------------------------------------------


async def test_internal_dispatch_with_debounce_coalesces_events(hassette_with_bus: "Hassette") -> None:
    """Internal listener (db_id=None) with debounce coalesces rapid events.

    Unlike tracked dispatch, internal dispatch wraps the handler in a try/except
    rather than routing through CommandExecutor.  This test verifies the debounce
    path works correctly for internal listeners.
    """
    hassette = hassette_with_bus
    call_count = 0
    event_handled = asyncio.Event()

    def handler(_event: Event) -> None:
        nonlocal call_count
        call_count += 1
        hassette.task_bucket.post_to_loop(event_handled.set)

    # Internal bus (no app_key) — listener gets db_id=None
    hassette._bus.on(topic="custom.internal_debounce", handler=handler, debounce=0.1)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    # Send 3 rapid events — debounce should coalesce into 1 handler call
    for i in range(3):
        await hassette.send_event(
            "custom.internal_debounce", Event(topic="custom.internal_debounce", payload=f"event-{i}")
        )

    await asyncio.wait_for(event_handled.wait(), timeout=1.0)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks drained")

    assert call_count == 1, f"Expected 1 call (debounce coalesce), got {call_count}"
    # Executor should NOT be involved for internal handlers
    executor.execute.assert_not_called()


async def test_internal_dispatch_with_throttle_drops_events(hassette_with_bus: "Hassette") -> None:
    """Internal listener (db_id=None) with throttle fires once and drops subsequent events."""
    hassette = hassette_with_bus
    call_count = 0
    event_handled = asyncio.Event()

    def handler(_event: Event) -> None:
        nonlocal call_count
        call_count += 1
        hassette.task_bucket.post_to_loop(event_handled.set)

    hassette._bus.on(topic="custom.internal_throttle", handler=handler, throttle=5.0)

    executor = hassette._bus_service._executor
    executor.execute.reset_mock()

    # Send 3 rapid events — throttle should allow only the first
    for i in range(3):
        await hassette.send_event(
            "custom.internal_throttle", Event(topic="custom.internal_throttle", payload=f"event-{i}")
        )

    await asyncio.wait_for(event_handled.wait(), timeout=1.0)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks cleaned up")

    assert call_count == 1, f"Expected 1 call (throttle), got {call_count}"
    executor.execute.assert_not_called()


async def test_internal_dispatch_with_debounce_logs_handler_error(
    hassette_with_bus: "Hassette", caplog: pytest.LogCaptureFixture
) -> None:
    """Internal debounced handler exceptions are logged, not propagated."""
    hassette = hassette_with_bus
    error_raised = asyncio.Event()

    def failing_handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(error_raised.set)
        raise ValueError("test error from debounced internal handler")

    hassette._bus.on(topic="custom.internal_debounce_error", handler=failing_handler, debounce=0.05)

    await hassette.send_event(
        "custom.internal_debounce_error",
        Event(topic="custom.internal_debounce_error", payload="test"),
    )

    await asyncio.wait_for(error_raised.wait(), timeout=1.0)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks drained")

    # Error is absorbed by safe_invoke() and logged, not propagated
    assert any("Internal handler error" in r.message for r in caplog.records), (
        "Expected 'Internal handler error' log record from safe_invoke()"
    )


# ---------------------------------------------------------------------------
# Cancel-during-debounce regression test
# ---------------------------------------------------------------------------


async def test_cancel_during_debounce_prevents_handler_fire(hassette_with_bus: "Hassette") -> None:
    """Cancelling a rate limiter during the debounce sleep window prevents the handler from firing.

    Uses the asyncio.Event gate pattern from CLAUDE.md regression test patterns.
    """
    from hassette.bus.rate_limiter import RateLimiter

    hassette = hassette_with_bus
    handler_fired = False

    def handler(_event: Event) -> None:
        nonlocal handler_fired
        handler_fired = True

    hassette._bus.on(topic="custom.cancel_debounce", handler=handler, debounce=0.5)

    # Wait deterministically for listener registration and rate limiter attachment
    listener = None
    rate_limiter = None
    for _ in range(100):
        all_listeners = await hassette._bus_service.router.get_topic_listeners("custom.cancel_debounce")
        if len(all_listeners) == 1 and all_listeners[0].rate_limiter is not None:
            listener = all_listeners[0]
            rate_limiter = listener.rate_limiter
            break
        await asyncio.sleep(0.01)

    assert listener is not None, "Listener for custom.cancel_debounce was not registered in time"
    assert isinstance(rate_limiter, RateLimiter)

    # Send an event to start the debounce timer
    await hassette.send_event("custom.cancel_debounce", Event(topic="custom.cancel_debounce", payload="test"))
    # Wait until the debounce task is actually sleeping
    await wait_for(lambda: rate_limiter._debounce_task is not None, desc="debounce task spawned")

    # Cancel the rate limiter while debounce is sleeping
    rate_limiter.cancel()

    # Wait until the debounce task has been cancelled and cleared
    await wait_for(
        lambda: rate_limiter._debounce_task is None or rate_limiter._debounce_task.done(),
        desc="debounce task cancelled or completed",
    )

    assert not handler_fired, "Handler should not fire after rate limiter cancellation"
