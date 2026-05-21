"""Ordering guarantee tests for Bus synchronous routing.

These tests prove that routing operations (add, remove, query) complete
synchronously — no task interleaving, no deferred execution. Each test
would have been flaky under the previous async-task-based design because
remove and add operations were independent background tasks that could
execute in any order.

Tests:
- AC#1: Cancel-then-add ordering — exactly one handler routed after cancel+replace
- AC#3: Query after registration — handler immediately visible without task yield
- AC#4: Bulk remove then query — routing table empty immediately after remove_all_listeners()
"""

import typing

import pytest

if typing.TYPE_CHECKING:
    from hassette.bus import Bus
    from hassette.test_utils.harness import HassetteHarness


# ---------------------------------------------------------------------------
# Handlers — module-level named functions required by collision detection
# ---------------------------------------------------------------------------


async def handler_alpha(event) -> None:
    pass


async def handler_beta(event) -> None:
    pass


async def handler_gamma(event) -> None:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def ordering_harness(
    hassette_harness,
    test_config,
) -> "typing.AsyncIterator[HassetteHarness]":
    """Function-scoped harness for ordering tests — each test gets a clean Bus."""
    harness = hassette_harness(test_config)
    harness.with_bus()
    await harness.start()
    try:
        yield harness
    finally:
        await harness.stop()


@pytest.fixture
def bus(ordering_harness: "HassetteHarness") -> "Bus":
    """The Bus from the ordering harness."""
    return ordering_harness.bus


# ---------------------------------------------------------------------------
# AC#1: Cancel-then-add ordering
# ---------------------------------------------------------------------------


async def test_cancel_then_add_routes_exactly_one_handler(bus: "Bus") -> None:
    """AC#1: Cancelling a subscription and immediately registering a replacement results in
    exactly one handler routed, not zero or two.

    Under the old async-task design, remove and add were independent background tasks
    that could interleave: the add task could complete before the remove task, causing
    both handlers to coexist; or the remove task could execute after the harness
    assertion but before dispatch, causing neither to be present. With synchronous
    routing both operations complete before the next line of caller code runs.
    """
    topic = "test.ordering.cancel_replace"

    # Register original handler
    sub = bus.on(topic=topic, handler=handler_alpha, name="original")

    # Verify it's routed
    listeners_before = bus.get_listeners()
    assert len(listeners_before) == 1
    assert listeners_before[0].listener_id == sub.listener.listener_id

    # Cancel, then immediately register replacement — no await between them
    sub.cancel()
    sub2 = bus.on(topic=topic, handler=handler_beta, name="replacement")

    # Routing table must reflect exactly one handler — the replacement
    listeners_after = bus.get_listeners()
    assert len(listeners_after) == 1, (
        f"Expected exactly 1 handler after cancel+replace, got {len(listeners_after)}. "
        "Ordering bug: old handler still present or new handler dropped."
    )
    assert listeners_after[0].listener_id == sub2.listener.listener_id, (
        "Routed listener is not the replacement — old handler still present."
    )


async def test_cancel_then_add_different_topics_both_routed(bus: "Bus") -> None:
    """Cancel on one topic + add on another topic — both are independent, no collision."""
    sub_a = bus.on(topic="test.ordering.topic_a", handler=handler_alpha)
    sub_b = bus.on(topic="test.ordering.topic_b", handler=handler_beta)  # noqa: F841

    # Cancel topic_a handler
    sub_a.cancel()

    # Immediately add a new handler on topic_a
    bus.on(topic="test.ordering.topic_a", handler=handler_gamma, name="topic_a_replacement")

    listeners = bus.get_listeners()
    # Should have exactly 2 listeners: the replacement on topic_a, and beta on topic_b
    assert len(listeners) == 2


async def test_cancel_multiple_then_add_replacement(bus: "Bus") -> None:
    """Cancel several handlers then add a single replacement — exactly one handler routed."""
    topic = "test.ordering.multi_cancel"

    sub1 = bus.on(topic=topic, handler=handler_alpha, name="h1")
    sub2 = bus.on(topic=topic, handler=handler_beta, name="h2")

    # Both present
    assert len(bus.get_listeners()) == 2

    # Cancel both, then add one replacement — all synchronous, no yields
    sub1.cancel()
    sub2.cancel()
    sub3 = bus.on(topic=topic, handler=handler_gamma, name="h3")

    listeners = bus.get_listeners()
    assert len(listeners) == 1
    assert listeners[0].listener_id == sub3.listener.listener_id


# ---------------------------------------------------------------------------
# AC#3: Query after registration — synchronous visibility
# ---------------------------------------------------------------------------


async def test_get_listeners_immediately_visible_after_registration(bus: "Bus") -> None:
    """AC#3: A handler registered via bus.on() is immediately visible in get_listeners()
    without yielding to the event loop.

    This test does NOT use await between registration and query. Under the old
    async-task design, add_route was a background task, so a synchronous call to
    get_listeners() could return a stale snapshot that didn't yet include the new handler.
    """
    topic = "test.ordering.immediate_visibility"

    # Register, then immediately query — no await between them
    sub = bus.on(topic=topic, handler=handler_alpha)
    listeners = bus.get_listeners()

    assert len(listeners) == 1, (
        f"Handler not immediately visible after registration — got {len(listeners)} listeners. "
        "Routing must be synchronous."
    )
    assert listeners[0].listener_id == sub.listener.listener_id


async def test_multiple_registrations_all_immediately_visible(bus: "Bus") -> None:
    """AC#3: Multiple handlers registered sequentially are all immediately visible."""
    bus.on(topic="test.ordering.vis_a", handler=handler_alpha, name="va")
    bus.on(topic="test.ordering.vis_b", handler=handler_beta, name="vb")
    bus.on(topic="test.ordering.vis_c", handler=handler_gamma, name="vc")

    listeners = bus.get_listeners()
    assert len(listeners) == 3


async def test_get_listeners_empty_before_any_registration(bus: "Bus") -> None:
    """AC#3 baseline: No handlers registered → get_listeners() returns empty list immediately."""
    assert bus.get_listeners() == []


# ---------------------------------------------------------------------------
# AC#4: Bulk remove then query — synchronous completion
# ---------------------------------------------------------------------------


async def test_remove_all_listeners_then_query_is_empty(bus: "Bus") -> None:
    """AC#4: remove_all_listeners() followed immediately by get_listeners() returns an
    empty list, with no await between the two calls.

    Under the old design, remove_all_listeners() returned a Task — querying before
    the task completed would return stale listeners. With synchronous routing,
    removal is complete before the call returns.
    """
    topic = "test.ordering.bulk_remove"

    bus.on(topic=topic, handler=handler_alpha, name="r1")
    bus.on(topic=topic, handler=handler_beta, name="r2")
    bus.on(topic="test.ordering.bulk_remove_2", handler=handler_gamma)

    # Confirm all 3 are present
    assert len(bus.get_listeners()) == 3

    # Bulk remove, then immediately query — no await between them
    bus.remove_all_listeners()
    listeners = bus.get_listeners()

    assert listeners == [], (
        f"Expected empty list after remove_all_listeners(), got {len(listeners)} listeners. "
        "Removal must complete synchronously before the call returns."
    )


async def test_remove_all_listeners_idempotent(bus: "Bus") -> None:
    """AC#4: Calling remove_all_listeners() on an already-empty bus is a no-op."""
    bus.remove_all_listeners()
    assert bus.get_listeners() == []


async def test_register_after_bulk_remove_works(bus: "Bus") -> None:
    """AC#4: After remove_all_listeners(), new registrations are accepted normally."""
    bus.on(topic="test.ordering.post_remove", handler=handler_alpha, name="first")
    bus.remove_all_listeners()

    # Should be able to register the same handler again (no stale collision key)
    sub = bus.on(topic="test.ordering.post_remove", handler=handler_alpha, name="first")
    listeners = bus.get_listeners()

    assert len(listeners) == 1
    assert listeners[0].listener_id == sub.listener.listener_id


async def test_interleaved_add_remove_preserves_count(bus: "Bus") -> None:
    """AC#1 + AC#4: Interleaved adds and removes maintain correct count at each step."""
    sub1 = bus.on(topic="test.ordering.interleaved", handler=handler_alpha, name="i1")
    assert len(bus.get_listeners()) == 1

    sub2 = bus.on(topic="test.ordering.interleaved", handler=handler_beta, name="i2")
    assert len(bus.get_listeners()) == 2

    sub1.cancel()
    listeners = bus.get_listeners()
    assert len(listeners) == 1
    assert listeners[0].listener_id == sub2.listener.listener_id

    sub2.cancel()
    assert bus.get_listeners() == []
