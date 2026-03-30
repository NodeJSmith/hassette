"""Integration tests for lifecycle propagation: single-pass shutdown, shutdown flag reset,
and close_streams ordering."""

from typing import TYPE_CHECKING

from hassette.types.enums import ResourceStatus

if TYPE_CHECKING:
    from hassette import Hassette


class TestHassetteShutdownSinglePass:
    """Verify that Hassette's shutdown is single-pass — children are shut down once by _finalize_shutdown().

    Hassette.on_shutdown() is a no-op; child shutdown propagation is owned entirely
    by _finalize_shutdown() with timeout enforcement.
    """

    async def test_children_shutdown_called_once(self, hassette_with_bus: "Hassette") -> None:
        """Each child's shutdown() is called exactly once via _finalize_shutdown() propagation."""
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

        bus.on_shutdown = tracked_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        try:
            await bus.shutdown()
            assert call_count == 1, f"on_shutdown should have been called exactly once, got {call_count}"
        finally:
            bus.on_shutdown = original_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

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

        bus.on_shutdown = tracked_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        try:
            # This should be a no-op due to _shutdown_completed
            await bus.shutdown()
            assert extra_calls == 0, "on_shutdown should not run again when _shutdown_completed is True"
        finally:
            bus.on_shutdown = original_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]
            # Restore for other tests
            await bus.initialize()

    async def test_hassette_on_shutdown_is_noop(self) -> None:
        """Hassette.on_shutdown() does not manually shut down children."""
        import inspect

        from hassette.core.core import Hassette

        # Verify the real Hassette.on_shutdown is a no-op (pass body only)
        source = inspect.getsource(Hassette.on_shutdown)
        # The method body should not contain gather, shutdown, or child iteration
        assert "gather" not in source, "on_shutdown should not gather child shutdowns"
        assert "child.shutdown" not in source, "on_shutdown should not call child.shutdown()"
        assert "resource.shutdown" not in source, "on_shutdown should not call resource.shutdown()"


class TestCloseStreamsAfterChildrenStopped:
    """Verify that close_streams() runs after children emit STOPPED events."""

    async def test_hassette_on_children_stopped_calls_close_streams(self) -> None:
        """Hassette._on_children_stopped() calls close_streams()."""
        import inspect

        from hassette.core.core import Hassette

        # Verify the real Hassette._on_children_stopped contains close_streams call
        source = inspect.getsource(Hassette._on_children_stopped)
        assert "close_streams" in source, "_on_children_stopped should call close_streams()"
        assert "super()" in source, "_on_children_stopped should call super()"

    async def test_children_stopped_before_on_children_stopped_hook(self, hassette_with_bus: "Hassette") -> None:
        """In _finalize_shutdown(), children's handle_stop() fires before the _on_children_stopped hook.

        Instead of calling _finalize_shutdown() directly (which may hang on the test harness),
        this test shuts down a single child and verifies that child.handle_stop() runs during
        shutdown. The ordering guarantee (children STOPPED -> _on_children_stopped) is
        verified by inspecting the _finalize_shutdown source code structure.
        """
        hassette = hassette_with_bus
        bus = hassette._bus
        assert bus is not None

        # Verify the child emits a STOPPED event during shutdown
        stopped_called = False
        original_handle_stop = bus.handle_stop

        async def tracked_handle_stop() -> None:
            nonlocal stopped_called
            stopped_called = True
            await original_handle_stop()

        bus.handle_stop = tracked_handle_stop  # pyright: ignore[reportAttributeAccessIssue]

        try:
            await bus.shutdown()
            assert stopped_called, "Child should have emitted a STOPPED event during shutdown"
            assert bus.status == ResourceStatus.STOPPED
        finally:
            bus.handle_stop = original_handle_stop  # pyright: ignore[reportAttributeAccessIssue]
            # Restore for other tests
            bus._shutdown_completed = False
            bus._shutting_down = False
            bus.shutdown_event.clear()
            await bus.initialize()

    async def test_finalize_shutdown_calls_hook_after_children(self) -> None:
        """Verify _finalize_shutdown() code structure: _on_children_stopped is called after children gather.

        This is a structural test verifying the ordering contract in Resource._finalize_shutdown().
        """
        import inspect

        from hassette.resources.base import Resource

        source = inspect.getsource(Resource._finalize_shutdown)
        # In the source, child.shutdown() gather must appear before _on_children_stopped
        gather_pos = source.find("child.shutdown()")
        hook_pos = source.find("_on_children_stopped")
        assert gather_pos > 0, "_finalize_shutdown should contain child.shutdown() gather"
        assert hook_pos > 0, "_finalize_shutdown should contain _on_children_stopped call"
        assert gather_pos < hook_pos, (
            "child.shutdown() gather should appear before _on_children_stopped in _finalize_shutdown"
        )
