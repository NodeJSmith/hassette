"""Tests for Service lifecycle: serve-task spawning lives in initialize/shutdown,
not in on_initialize/on_shutdown, so subclasses can freely override hooks."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from hassette.exceptions import CannotOverrideFinalError
from hassette.resources.base import FinalMeta, Service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hassette_stub() -> AsyncMock:
    """Minimal stub that satisfies Resource.__init__ and TaskBucket.spawn."""
    hassette = AsyncMock()
    hassette.config.log_level = "DEBUG"
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.resource_shutdown_timeout_seconds = 1
    hassette.config.task_cancellation_timeout_seconds = 1
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.dev_mode = False
    hassette.event_streams_closed = False
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    # TaskBucket.spawn needs these to use the fast path (asyncio.create_task)
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_event_loop()
    return hassette


class SimpleService(Service):
    """Minimal concrete Service for testing."""

    served: bool = False

    async def serve(self) -> None:
        self.served = True
        # Block until cancelled so the task stays alive
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


class ServiceWithCustomHooks(Service):
    """Service that overrides on_initialize and on_shutdown without calling super()."""

    init_called: bool = False
    shutdown_called: bool = False

    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    async def on_initialize(self) -> None:
        # Deliberately does NOT call super() — the old bug
        self.init_called = True

    async def on_shutdown(self) -> None:
        # Deliberately does NOT call super() — the old bug
        self.shutdown_called = True


class ServiceWithOrderTracking(Service):
    """Tracks the order of lifecycle events."""

    order: list[str]

    async def serve(self) -> None:
        self.order.append("serve_started")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.order.append("serve_cancelled")
            raise

    async def on_initialize(self) -> None:
        self.order.append("on_initialize")

    async def on_shutdown(self) -> None:
        self.order.append("on_shutdown")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_serve_task_spawned_even_when_on_initialize_overridden():
    """serve() task is spawned even when on_initialize is overridden without super()."""
    hassette = _make_hassette_stub()
    svc = ServiceWithCustomHooks(hassette)
    svc.order = []  # type: ignore[attr-defined]

    await svc.initialize()
    # Let the serve task start
    await asyncio.sleep(0.05)

    assert svc.init_called, "on_initialize should have been called"
    assert svc._serve_task is not None, "serve task should have been spawned"
    assert not svc._serve_task.done(), "serve task should still be running"

    # Cleanup
    await svc.shutdown()


async def test_serve_task_cancelled_even_when_on_shutdown_overridden():
    """serve() task is cancelled even when on_shutdown is overridden without super()."""
    hassette = _make_hassette_stub()
    svc = ServiceWithCustomHooks(hassette)

    await svc.initialize()
    await asyncio.sleep(0.05)
    assert svc._serve_task is not None
    assert not svc._serve_task.done()

    await svc.shutdown()

    assert svc.shutdown_called, "on_shutdown should have been called"
    assert svc._serve_task.done(), "serve task should be done after shutdown"


async def test_on_initialize_runs_before_serve_task_spawned():
    """on_initialize() runs before the serve task is spawned (ordering)."""
    hassette = _make_hassette_stub()
    svc = ServiceWithOrderTracking(hassette)
    svc.order = []

    await svc.initialize()
    await asyncio.sleep(0.05)

    # on_initialize must come before serve_started
    assert "on_initialize" in svc.order
    assert "serve_started" in svc.order
    idx_init = svc.order.index("on_initialize")
    idx_serve = svc.order.index("serve_started")
    assert idx_init < idx_serve, f"on_initialize ({idx_init}) should precede serve_started ({idx_serve})"

    await svc.shutdown()


async def test_serve_task_cancelled_before_on_shutdown():
    """serve() task is cancelled before on_shutdown() runs (ordering)."""
    hassette = _make_hassette_stub()
    svc = ServiceWithOrderTracking(hassette)
    svc.order = []

    await svc.initialize()
    await asyncio.sleep(0.05)

    svc.order.clear()  # reset to only track shutdown ordering
    await svc.shutdown()

    assert "serve_cancelled" in svc.order
    assert "on_shutdown" in svc.order
    idx_cancel = svc.order.index("serve_cancelled")
    idx_shutdown = svc.order.index("on_shutdown")
    assert idx_cancel < idx_shutdown, f"serve_cancelled ({idx_cancel}) should precede on_shutdown ({idx_shutdown})"


def test_finalmeta_blocks_service_subclass_from_overriding_initialize():
    """FinalMeta blocks Service subclasses from overriding initialize/shutdown."""
    # Clear the loaded classes cache so FinalMeta re-checks
    key = f"{__name__}._BadSubclass"
    FinalMeta.LOADED_CLASSES.discard(key)

    with pytest.raises(CannotOverrideFinalError):

        class _BadSubclass(Service):
            async def serve(self) -> None:
                pass

            async def initialize(self) -> None:  # type: ignore[override]
                pass


def test_finalmeta_blocks_service_subclass_from_overriding_shutdown():
    """FinalMeta blocks Service subclasses from overriding shutdown."""
    key = f"{__name__}._BadSubclass2"
    FinalMeta.LOADED_CLASSES.discard(key)

    with pytest.raises(CannotOverrideFinalError):

        class _BadSubclass2(Service):
            async def serve(self) -> None:
                pass

            async def shutdown(self) -> None:  # type: ignore[override]
                pass


async def test_simple_service_completes_full_lifecycle():
    """A simple service can initialize and shut down cleanly."""
    hassette = _make_hassette_stub()
    svc = SimpleService(hassette)

    await svc.initialize()
    await asyncio.sleep(0.05)

    assert svc._serve_task is not None
    assert not svc._serve_task.done()

    await svc.shutdown()

    assert svc._serve_task.done()
