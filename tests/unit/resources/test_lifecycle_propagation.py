"""Tests for shutdown idempotency via _shutdown_completed flag.

Verifies that:
- shutdown() only executes once (double-call is a no-op)
- initialize() resets the flag so shutdown() works again
- initialize() clears shutdown_event
- start() resets the flag
"""

import asyncio

from hassette.resources.base import Resource

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
