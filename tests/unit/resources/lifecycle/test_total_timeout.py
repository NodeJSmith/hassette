"""Tests for total shutdown timeout behavior.

Verifies:
- Total timeout caps wall-clock shutdown duration
- _force_terminal() is called on all descendants when total timeout fires
- close_streams() equivalent runs even on total timeout
- shutdown_completed is set before handle_stop() and close_streams()
"""

import asyncio
from contextlib import suppress

from hassette.resources.base import FinalMeta, Resource
from hassette.test_utils import make_mock_hassette
from hassette.types.enums import ResourceStatus

from .conftest import HangingChild, ShutdownCounter, SimpleParent

# Pre-register so FinalMeta allows the shutdown() override on this test helper
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.lifecycle.test_total_timeout.TotalTimeoutRoot")


class TotalTimeoutRoot(Resource):
    """Mimics Hassette's shutdown() override with total timeout wrapping.

    Uses the same pattern as the real Hassette.shutdown() to test the
    total_shutdown_timeout_seconds behavior without requiring the full
    Hassette __init__ machinery.
    """

    _close_streams_called: bool = False
    _handle_stop_called: bool = False
    _handle_stop_order: int = 0
    _close_streams_order: int = 0
    _shutdown_completed_order: int = 0
    _order_counter: int = 0

    @property
    def event_streams_closed(self) -> bool:
        return self._close_streams_called

    async def _close_streams(self) -> None:
        self._order_counter += 1
        self._close_streams_order = self._order_counter
        self._close_streams_called = True

    async def shutdown(self) -> None:
        try:
            async with asyncio.timeout(self.hassette.config.lifecycle.total_shutdown_timeout_seconds):
                await super().shutdown()
        except TimeoutError:
            self.logger.critical(
                "Total shutdown timeout (%ss) exceeded — forcing termination",
                self.hassette.config.lifecycle.total_shutdown_timeout_seconds,
            )
            for child in self.children:
                child._force_terminal()
        finally:
            self._order_counter += 1
            self._shutdown_completed_order = self._order_counter
            self.shutdown_completed = True
            if not self.event_streams_closed:
                with suppress(Exception):
                    self._order_counter += 1
                    self._handle_stop_order = self._order_counter
                    self._handle_stop_called = True
                    await self.handle_stop()
            with suppress(Exception):
                await self._close_streams()
            self.status = ResourceStatus.STOPPED
            self.mark_not_ready("shutdown complete")


async def test_total_shutdown_timeout_caps_wall_clock():
    """Hassette-style total timeout ensures shutdown completes within budget even when a child hangs."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.2
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 5  # per-level timeout is much larger

    root = TotalTimeoutRoot(hassette)
    hanging = root.add_child(HangingChild)
    normal = root.add_child(ShutdownCounter)

    await root.initialize()
    await hanging.initialize()
    await normal.initialize()

    start = asyncio.get_event_loop().time()
    await root.shutdown()
    elapsed = asyncio.get_event_loop().time() - start

    # Should complete in roughly total_shutdown_timeout_seconds (0.2s), not
    # resource_shutdown_timeout_seconds (5s). The 3s cap gives generous margin
    # for CI runner variability while still catching the 5s per-resource path.
    assert elapsed < 3.0, f"Shutdown took {elapsed:.2f}s — total timeout should have capped it"
    assert root.shutdown_completed is True
    assert hanging.shutdown_completed is True


async def test_total_timeout_force_patches_all_descendants():
    """On total timeout, _force_terminal() is called recursively on all descendants."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.1
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 5

    root = TotalTimeoutRoot(hassette)
    hanging = root.add_child(HangingChild)
    grandchild = hanging.add_child(SimpleParent)

    await root.initialize()
    await hanging.initialize()
    await grandchild.initialize()

    await root.shutdown()

    # All descendants should be force-terminated
    assert hanging.shutdown_completed is True
    assert hanging.status == ResourceStatus.STOPPED
    assert grandchild.shutdown_completed is True
    assert grandchild.status == ResourceStatus.STOPPED


async def test_total_timeout_finally_always_closes_streams():
    """close_streams() equivalent is called even when the total timeout fires."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.1
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 5

    root = TotalTimeoutRoot(hassette)
    root.add_child(HangingChild)

    await root.initialize()

    await root.shutdown()

    assert root._close_streams_called is True, "close_streams must be called even on total timeout"


async def test_total_timeout_sets_shutdown_completed_first():
    """shutdown_completed=True is set before handle_stop() and close_streams() in the finally block."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.1
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 5

    root = TotalTimeoutRoot(hassette)
    root.add_child(HangingChild)

    await root.initialize()

    await root.shutdown()

    # _shutdown_completed_order should be less than handle_stop and close_streams
    assert root._shutdown_completed_order < root._handle_stop_order, (
        f"shutdown_completed (order={root._shutdown_completed_order}) must be set before "
        f"handle_stop (order={root._handle_stop_order})"
    )
    assert root._shutdown_completed_order < root._close_streams_order, (
        f"shutdown_completed (order={root._shutdown_completed_order}) must be set before "
        f"close_streams (order={root._close_streams_order})"
    )
