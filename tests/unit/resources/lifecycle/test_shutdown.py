"""Tests for shutdown propagation.

Verifies:
- shutdown() is idempotent, and initialize()/start() reset its completion state
- children shut down in reverse order, tolerating errors and skipping completed children
- leaf resources and Service subclasses propagate the same way
"""

from hassette_wire import ResourceStatus

from hassette.resources.lifecycle import start
from hassette.resources.operations import ordered_children_for_shutdown
from hassette.testing import wait_for
from tests.support.mock_hassette import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource, wait_for_running

from .conftest import (
    ErrorChild,
    OrderTrackingChild,
    ShutdownCounter,
    SimpleParent,
    SimpleService,
    make_initialized_shutdown_counter,
    make_parent_with_child,
    shutdown_order,
)


async def test_shutdown_completed_prevents_double_shutdown():
    """Calling shutdown() twice only runs on_shutdown once."""
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    await resource.shutdown()  # second call should be a no-op

    assert resource.shutdown_count == 1, f"Expected 1 shutdown, got {resource.shutdown_count}"


async def test_shutdown_completed_reset_by_initialize():
    """After shutdown then initialize, shutdown() works again."""
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    assert resource.shutdown_count == 1

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_count == 2, f"Expected 2 shutdowns, got {resource.shutdown_count}"


async def test_shutdown_event_cleared_by_initialize():
    """initialize() clears shutdown_event so it is not set."""
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    assert resource.shutdown_event.is_set(), "shutdown_event should be set after shutdown"

    await resource.initialize()
    assert not resource.shutdown_event.is_set(), "shutdown_event should be cleared after initialize"


async def test_start_resets_shutdown_completed():
    """start() spawns a joiner task; once it runs, the coordinator resets shutdown_completed.

    start() itself never assigns ``_init_task`` or resets shutdown state directly (design:
    "start() calls the public initialization front door but never assigns _init_task itself").
    Only the coordinated ``initialize()`` call the joiner makes does that, once it actually
    runs — so this test waits for that to happen instead of asserting synchronously.
    """
    resource = await make_initialized_shutdown_counter()

    await resource.shutdown()
    assert resource.shutdown_completed is True

    start(resource)
    # The pre-existing `_init_task` reference from make_initialized_shutdown_counter() is
    # already non-None (though done), so waiting on "is not None" alone would pass immediately
    # without ever letting start()'s spawned joiner run. Wait for the actual effect instead.
    await wait_for(lambda: not resource.shutdown_completed, desc="coordinator accepted new init attempt")
    assert resource._init_task is not None, "start() should have led to an init task being assigned"

    # Cleanup: await the spawned init task, then shut down
    assert resource._init_task is not None
    await resource._init_task
    await resource.shutdown()


async def test_shutdown_immediately_after_start_does_not_leave_resource_running():
    """A shutdown() called immediately after start(), with no intervening await, must not be
    overtaken by that pending start.

    Regression test: start()'s joiner does not assign ``_init_task`` synchronously -- only the
    joiner actually running ``coordinate_initialize()`` does that, which can be a full
    event-loop turn later. Without ``_pending_start_task`` tracking that pending joiner,
    ``shutdown()``'s ``_observe_active_initializer()`` would see ``_init_task`` still ``None``,
    conclude there was nothing to cancel, and complete cleanly -- only for the still-pending
    joiner to resume afterward, consume the just-stored safe outcome, and initialize the
    resource anyway, leaving it running after the explicit shutdown had already returned.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)

    start(resource)
    # No await between start() and shutdown(): the joiner has not had an event-loop turn yet.
    outcome = await resource.shutdown()

    assert outcome.is_restart_safe is True
    assert resource.status == ResourceStatus.STOPPED, (
        f"resource must stay STOPPED after an explicit shutdown, got {resource.status}"
    )
    assert resource._init_task is None or resource._init_task.done()
    assert resource._pending_start_task is None


async def test_shutdown_after_completed_shutdown_cancels_queued_start():
    """A shutdown() called immediately after start(), on a resource that already completed a
    prior clean shutdown, must not be overtaken by that pending start either.

    Regression test: distinct from ``test_shutdown_immediately_after_start_does_not_leave_
    resource_running`` above, which covers the *first* shutdown attempt (``_shutdown_task`` is
    still ``None`` at that point, so ``coordinate_shutdown()`` creates a fresh coordinator that
    calls ``_observe_active_initializer()`` and cancels the pending joiner). Here the resource
    has already shut down once, so ``_shutdown_task`` is a *completed* task -- it stays that way
    until the next accepted ``initialize()`` attempt consumes the outcome and clears it (see
    ``coordinate_initialize()``). Without the ``elif task.done():`` branch in
    ``coordinate_shutdown()``, this second ``shutdown()`` call would see a non-``None`` task and
    simply return the already-stored outcome without ever cancelling the newly-queued
    ``_pending_start_task`` -- letting that joiner resume afterward, consume the outcome, and
    initialize the resource despite the explicit shutdown having already returned.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)

    await resource.initialize()
    first_outcome = await resource.shutdown()
    assert first_outcome.is_restart_safe is True

    start(resource)
    # No await between start() and shutdown(): the joiner has not had an event-loop turn yet.
    second_outcome = await resource.shutdown()

    assert second_outcome.is_restart_safe is True
    assert resource.status == ResourceStatus.STOPPED, (
        f"resource must stay STOPPED after the second explicit shutdown, got {resource.status}"
    )
    assert resource._init_task is None or resource._init_task.done()
    assert resource._pending_start_task is None


async def test_ordered_children_for_shutdown_returns_reversed():
    """ordered_children_for_shutdown() returns children in reverse insertion order."""
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_a = parent.add_child(ShutdownCounter)
    child_b = parent.add_child(ShutdownCounter)
    child_c = parent.add_child(ShutdownCounter)

    ordered = ordered_children_for_shutdown(parent)
    assert ordered == [child_c, child_b, child_a], f"Expected [C, B, A], got {ordered}"


async def test_shutdown_propagates_to_children_in_reverse_order():
    """Parent with 3 children: shutdown propagates in reverse insertion order."""
    parent, child_a = make_parent_with_child(shutdown_order, OrderTrackingChild)
    child_b = parent.add_child(OrderTrackingChild)
    child_c = parent.add_child(OrderTrackingChild)

    await parent.initialize()
    await child_a.initialize()
    await child_b.initialize()
    await child_c.initialize()

    await parent.shutdown()

    # Children should be shut down in reverse insertion order: C, B, A
    assert shutdown_order == [
        child_c.unique_name,
        child_b.unique_name,
        child_a.unique_name,
    ], f"Expected reverse order, got {shutdown_order}"


async def test_shutdown_propagation_error_tolerance():
    """Middle child raises during shutdown; other children still shut down."""
    parent, child_a = make_parent_with_child(shutdown_order, OrderTrackingChild)
    child_b = parent.add_child(ErrorChild)  # will raise
    child_c = parent.add_child(OrderTrackingChild)

    await parent.initialize()
    await child_a.initialize()
    await child_b.initialize()
    await child_c.initialize()

    await parent.shutdown()

    # All three children should have had on_shutdown called (ErrorChild appends before raising)
    assert child_c.unique_name in shutdown_order
    assert child_b.unique_name in shutdown_order
    assert child_a.unique_name in shutdown_order
    assert len(shutdown_order) == 3


async def test_shutdown_propagation_skips_completed_children():
    """Pre-shutting down a child means parent propagation is a no-op for that child."""
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child.initialize()

    # Pre-shutdown the child directly
    await child.shutdown()
    assert child.shutdown_count == 1

    # Now shutdown the parent — propagation calls child.shutdown() again,
    # but shutdown_completed makes it a no-op
    await parent.shutdown()
    assert child.shutdown_count == 1, f"Expected 1, got {child.shutdown_count}"


async def test_shutdown_propagation_with_no_children():
    """Leaf Resource (no children) shuts down normally without errors."""
    hassette = make_mock_hassette(sealed=False)
    leaf = ShutdownCounter(hassette)

    await leaf.initialize()
    await leaf.shutdown()

    assert leaf.shutdown_count == 1
    assert leaf.shutdown_completed is True


async def test_service_inherits_shutdown_propagation():
    """Service subclass with children propagates shutdown after serve task cancellation."""
    shutdown_order.clear()
    hassette = make_mock_hassette(sealed=False)
    parent_svc = SimpleService(hassette)

    child_a = parent_svc.add_child(OrderTrackingChild)
    child_b = parent_svc.add_child(OrderTrackingChild)

    await parent_svc.initialize()
    await child_a.initialize()
    await child_b.initialize()

    await wait_for_running(parent_svc)

    await parent_svc.shutdown()

    # Children shut down in reverse order: B, A
    assert shutdown_order == [
        child_b.unique_name,
        child_a.unique_name,
    ], f"Expected reverse order, got {shutdown_order}"
