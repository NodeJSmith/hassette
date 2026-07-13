"""Tests for shutdown propagation.

Verifies:
- shutdown() only executes once (double-call is a no-op)
- initialize() resets the flag so shutdown() works again
- initialize() clears shutdown_event
- start() resets the flag
- _finalize_shutdown() propagates shutdown to children in reverse insertion order
- Child shutdown errors are tolerated and logged
- Already-completed children are skipped
- Leaf Resources (no children) shut down normally
- Service subclasses inherit propagation
"""

from hassette.resources.lifecycle import start
from hassette.resources.operations import ordered_children_for_shutdown
from hassette.test_utils import make_mock_hassette
from tests.unit.resources.conftest import wait_for_running

from .conftest import (
    ErrorChild,
    HangingChild,
    OrderTrackingChild,
    ShutdownCounter,
    SimpleParent,
    SimpleService,
    shutdown_order,
)


async def test_shutdown_completed_prevents_double_shutdown():
    """Calling shutdown() twice only runs on_shutdown once."""
    hassette = make_mock_hassette(sealed=False)
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    await resource.shutdown()  # second call should be a no-op

    assert resource.shutdown_count == 1, f"Expected 1 shutdown, got {resource.shutdown_count}"


async def test_shutdown_completed_reset_by_initialize():
    """After shutdown then initialize, shutdown() works again."""
    hassette = make_mock_hassette(sealed=False)
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_count == 1

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_count == 2, f"Expected 2 shutdowns, got {resource.shutdown_count}"


async def test_shutdown_event_cleared_by_initialize():
    """initialize() clears shutdown_event so it is not set."""
    hassette = make_mock_hassette(sealed=False)
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_event.is_set(), "shutdown_event should be set after shutdown"

    await resource.initialize()
    assert not resource.shutdown_event.is_set(), "shutdown_event should be cleared after initialize"


async def test_start_resets_shutdown_completed():
    """start() resets shutdown_completed so the init task is spawned."""
    hassette = make_mock_hassette(sealed=False)
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_completed is True

    start(resource)
    assert resource.shutdown_completed is False
    assert resource._init_task is not None, "start() should have spawned an init task"

    # Cleanup: await the spawned init task, then shut down
    assert resource._init_task is not None
    await resource._init_task
    await resource.shutdown()


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
    shutdown_order.clear()
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_a = parent.add_child(OrderTrackingChild)
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
    shutdown_order.clear()
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_a = parent.add_child(OrderTrackingChild)
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


async def test_shutdown_propagation_completes_despite_child_exception():
    """Parent completes shutdown even when a child's shutdown() raises unexpectedly.

    This tests the gather(return_exceptions=True) safety net: even if shutdown()
    itself raises (not just on_shutdown hooks), the parent still sets
    shutdown_completed and processes remaining children.
    """
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child_ok = parent.add_child(ShutdownCounter)
    child_broken = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child_ok.initialize()
    await child_broken.initialize()

    # Monkeypatch child_broken.shutdown to raise an unexpected error
    async def exploding_shutdown():
        raise RuntimeError("unexpected boom")

    # Bypass the @final descriptor by setting on the instance dict
    object.__setattr__(child_broken, "shutdown", exploding_shutdown)

    await parent.shutdown()

    # Parent must still complete shutdown
    assert parent.shutdown_completed is True
    # The working child should have been shut down (it's in reverse order, so child_ok runs second)
    assert child_ok.shutdown_count == 1


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


async def test_shutdown_propagation_timeout_forces_terminal_state():
    """When child shutdown times out, timed-out children are forced to consistent terminal state."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 0.1  # very short timeout

    parent = SimpleParent(hassette)
    hanging = parent.add_child(HangingChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    await parent.shutdown()

    # Parent should complete despite the hanging child
    assert parent.shutdown_completed is True
    # Hanging child should be forced to terminal state
    assert hanging.shutdown_completed is True
    assert hanging.shutting_down is False
    # Normal child should also be shut down (gather runs concurrently)
    assert normal.shutdown_completed is True


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
