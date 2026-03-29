"""Tests for shutdown lifecycle: idempotency (_shutdown_completed) and propagation.

Verifies that:
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

import asyncio

from hassette.resources.base import Resource, Service

from .conftest import _make_hassette_stub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ShutdownCounter(Resource):
    """Resource that counts on_shutdown calls."""

    shutdown_count: int = 0

    async def on_shutdown(self) -> None:
        self.shutdown_count += 1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_shutdown_completed_prevents_double_shutdown():
    """Calling shutdown() twice only runs on_shutdown once."""
    hassette = _make_hassette_stub()
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    await resource.shutdown()  # second call should be a no-op

    assert resource.shutdown_count == 1, f"Expected 1 shutdown, got {resource.shutdown_count}"


async def test_shutdown_completed_reset_by_initialize():
    """After shutdown then initialize, shutdown() works again."""
    hassette = _make_hassette_stub()
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_count == 1

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_count == 2, f"Expected 2 shutdowns, got {resource.shutdown_count}"


async def test_shutdown_event_cleared_by_initialize():
    """initialize() clears shutdown_event so it is not set."""
    hassette = _make_hassette_stub()
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    assert resource.shutdown_event.is_set(), "shutdown_event should be set after shutdown"

    await resource.initialize()
    assert not resource.shutdown_event.is_set(), "shutdown_event should be cleared after initialize"


async def test_start_resets_shutdown_completed():
    """start() resets _shutdown_completed so the init task is spawned."""
    hassette = _make_hassette_stub()
    resource = ShutdownCounter(hassette)

    await resource.initialize()
    await resource.shutdown()
    assert resource._shutdown_completed is True

    resource.start()
    assert resource._shutdown_completed is False
    assert resource._init_task is not None, "start() should have spawned an init task"

    # Cleanup: let the init task complete, then shut down
    await asyncio.sleep(0.05)
    await resource.shutdown()


# ---------------------------------------------------------------------------
# Propagation Helpers
# ---------------------------------------------------------------------------

# Shared list to record shutdown order across multiple children
_shutdown_order: list[str] = []


class OrderTrackingChild(Resource):
    """Resource that appends its unique_name to a shared list on shutdown."""

    async def on_shutdown(self) -> None:
        _shutdown_order.append(self.unique_name)


class ErrorChild(Resource):
    """Resource that raises during on_shutdown."""

    async def on_shutdown(self) -> None:
        _shutdown_order.append(self.unique_name)
        raise RuntimeError(f"{self.unique_name} exploded")


class SimpleParent(Resource):
    """Parent resource with no custom shutdown logic."""

    pass


# ---------------------------------------------------------------------------
# Propagation Tests
# ---------------------------------------------------------------------------


async def test_shutdown_propagates_to_children_in_reverse_order():
    """Parent with 3 children: shutdown propagates in reverse insertion order."""
    _shutdown_order.clear()
    hassette = _make_hassette_stub()
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
    assert _shutdown_order == [
        child_c.unique_name,
        child_b.unique_name,
        child_a.unique_name,
    ], f"Expected reverse order, got {_shutdown_order}"


async def test_shutdown_propagation_error_tolerance():
    """Middle child raises during shutdown; other children still shut down."""
    _shutdown_order.clear()
    hassette = _make_hassette_stub()
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
    assert child_c.unique_name in _shutdown_order
    assert child_b.unique_name in _shutdown_order
    assert child_a.unique_name in _shutdown_order
    assert len(_shutdown_order) == 3


async def test_shutdown_propagation_completes_despite_child_exception():
    """Parent completes shutdown even when a child's shutdown() raises unexpectedly.

    This tests the gather(return_exceptions=True) safety net: even if shutdown()
    itself raises (not just on_shutdown hooks), the parent still sets
    _shutdown_completed and processes remaining children.
    """
    hassette = _make_hassette_stub()
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
    assert parent._shutdown_completed is True
    # The working child should have been shut down (it's in reverse order, so child_ok runs second)
    assert child_ok.shutdown_count == 1


async def test_shutdown_propagation_skips_completed_children():
    """Pre-shutting down a child means parent propagation is a no-op for that child."""
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child.initialize()

    # Pre-shutdown the child directly
    await child.shutdown()
    assert child.shutdown_count == 1

    # Now shutdown the parent — propagation calls child.shutdown() again,
    # but _shutdown_completed makes it a no-op
    await parent.shutdown()
    assert child.shutdown_count == 1, f"Expected 1, got {child.shutdown_count}"


async def test_shutdown_propagation_with_no_children():
    """Leaf Resource (no children) shuts down normally without errors."""
    hassette = _make_hassette_stub()
    leaf = ShutdownCounter(hassette)

    await leaf.initialize()
    await leaf.shutdown()

    assert leaf.shutdown_count == 1
    assert leaf._shutdown_completed is True


class SimpleService(Service):
    """Service that runs indefinitely until cancelled."""

    async def serve(self) -> None:
        await asyncio.Event().wait()  # block forever


async def test_service_inherits_shutdown_propagation():
    """Service subclass with children propagates shutdown after serve task cancellation."""
    _shutdown_order.clear()
    hassette = _make_hassette_stub()
    parent_svc = SimpleService(hassette)

    child_a = parent_svc.add_child(OrderTrackingChild)
    child_b = parent_svc.add_child(OrderTrackingChild)

    await parent_svc.initialize()
    await child_a.initialize()
    await child_b.initialize()

    # Let the serve task start
    await asyncio.sleep(0.01)

    await parent_svc.shutdown()

    # Children shut down in reverse order: B, A
    assert _shutdown_order == [
        child_b.unique_name,
        child_a.unique_name,
    ], f"Expected reverse order, got {_shutdown_order}"
