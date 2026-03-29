"""Integration tests for lifecycle propagation: idempotent shutdown and shutdown flag reset."""

from typing import TYPE_CHECKING

from hassette.types.enums import ResourceStatus

if TYPE_CHECKING:
    from hassette import Hassette


class TestHassetteShutdownIdempotent:
    """Verify that Hassette's double-shutdown path (on_shutdown + _finalize_shutdown) is idempotent.

    Hassette.on_shutdown() manually gathers child.shutdown() for all children,
    then _finalize_shutdown() propagation tries to shut them down again.
    The _shutdown_completed flag should make the second pass a no-op.
    """

    async def test_children_shutdown_called_once(self, hassette_with_bus: "Hassette") -> None:
        """Children's on_shutdown hooks run exactly once despite double-shutdown path."""
        hassette = hassette_with_bus
        bus = hassette._bus
        assert bus is not None

        # Track calls to the bus's on_shutdown
        original_on_shutdown = bus.on_shutdown
        call_count = 0

        async def tracked_on_shutdown() -> None:
            nonlocal call_count
            call_count += 1
            await original_on_shutdown()

        bus.on_shutdown = tracked_on_shutdown  # type: ignore[assignment]

        try:
            # First explicit shutdown (simulating what Hassette.on_shutdown does)
            await bus.shutdown()
            assert call_count == 1, f"on_shutdown should have been called once, got {call_count}"

            # Second shutdown (simulating what _finalize_shutdown propagation does)
            await bus.shutdown()
            # _shutdown_completed flag should prevent the second call
            assert call_count == 1, f"on_shutdown should still be 1 after idempotent second call, got {call_count}"
        finally:
            bus.on_shutdown = original_on_shutdown  # type: ignore[assignment]

    async def test_shutdown_then_initialize_resets_flag(self, hassette_with_bus: "Hassette") -> None:
        """After shutdown + initialize, the resource can be shut down again."""
        hassette = hassette_with_bus
        bus = hassette._bus
        assert bus is not None

        await bus.shutdown()
        assert bus._shutdown_completed is True

        # Re-initialize should reset the flag
        await bus.initialize()
        assert bus._shutdown_completed is False

        # Should be able to shut down again
        await bus.shutdown()
        assert bus._shutdown_completed is True

        # Restore for other tests
        await bus.initialize()

    async def test_shutdown_completed_flag_blocks_repeated_hooks(self, hassette_with_bus: "Hassette") -> None:
        """The _shutdown_completed flag prevents on_shutdown from running a second time."""
        hassette = hassette_with_bus
        bus = hassette._bus
        assert bus is not None

        # Ensure we start clean
        if bus._shutdown_completed:
            await bus.initialize()

        await bus.shutdown()
        assert bus._shutdown_completed is True
        assert bus.status == ResourceStatus.STOPPED

        # Track any further on_shutdown calls
        original_on_shutdown = bus.on_shutdown
        extra_calls = 0

        async def tracked_on_shutdown() -> None:
            nonlocal extra_calls
            extra_calls += 1
            await original_on_shutdown()

        bus.on_shutdown = tracked_on_shutdown  # type: ignore[assignment]

        try:
            # This should be a no-op due to _shutdown_completed
            await bus.shutdown()
            assert extra_calls == 0, "on_shutdown should not run again when _shutdown_completed is True"
        finally:
            bus.on_shutdown = original_on_shutdown  # type: ignore[assignment]
            # Restore for other tests
            await bus.initialize()
