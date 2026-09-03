"""Tests for Service lifecycle: serve-task spawning lives in initialize/shutdown,
not in on_initialize/on_shutdown, so subclasses can freely override hooks.
"""

import asyncio
import warnings

import pytest

from hassette.exceptions import CannotOverrideFinalError
from hassette.resources.base import FinalMeta
from hassette.resources.operations import restart
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.testing import wait_for
from tests.support.factories import make_mock_hassette
from tests.support.helpers import block_until_cancelled
from tests.unit.resources.conftest import wait_for_running
from tests.unit.resources.lifecycle.conftest import make_running_simple_service


class ServiceWithCustomHooks(Service):
    """Service that overrides on_initialize and on_shutdown without calling super()."""

    restart_spec = RestartSpec()
    init_called: bool = False
    shutdown_called: bool = False

    serve = block_until_cancelled  # bound as instance method via the descriptor protocol

    async def on_initialize(self) -> None:
        # Deliberately does NOT call super() — the old bug
        self.init_called = True

    async def on_shutdown(self) -> None:
        # Deliberately does NOT call super() — the old bug
        self.shutdown_called = True


class ServiceWithOrderTracking(Service):
    """Tracks the order of lifecycle events."""

    restart_spec = RestartSpec()
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


async def test_serve_task_spawned_even_when_on_initialize_overridden():
    """serve() task is spawned even when on_initialize is overridden without super()."""
    hassette = make_mock_hassette(sealed=False)
    svc = ServiceWithCustomHooks(hassette)
    svc.order = []  # pyright: ignore[reportAttributeAccessIssue]

    await svc.initialize()
    await wait_for_running(svc)

    assert svc.init_called, "on_initialize should have been called"
    assert svc._serve_task is not None, "serve task should have been spawned"
    assert not svc._serve_task.done(), "serve task should still be running"

    # Cleanup
    await svc.shutdown()


async def test_serve_task_cancelled_even_when_on_shutdown_overridden():
    """serve() task is cancelled even when on_shutdown is overridden without super()."""
    hassette = make_mock_hassette(sealed=False)
    svc = ServiceWithCustomHooks(hassette)

    await svc.initialize()
    await wait_for_running(svc)
    assert svc._serve_task is not None
    assert not svc._serve_task.done()

    report = await svc.shutdown()

    assert svc.shutdown_called, "on_shutdown should have been called"
    assert svc._serve_task.done(), "serve task should be done after shutdown"
    assert report.is_restart_safe is True, "cooperative teardown must remain restart-safe"


async def test_on_initialize_runs_before_serve_task_spawned():
    """on_initialize() runs before the serve task is spawned (ordering)."""
    hassette = make_mock_hassette(sealed=False)
    svc = ServiceWithOrderTracking(hassette)
    svc.order = []

    await svc.initialize()
    await wait_for(lambda: "serve_started" in svc.order, desc="serve task started")

    # on_initialize must come before serve_started
    assert "on_initialize" in svc.order
    assert "serve_started" in svc.order
    idx_init = svc.order.index("on_initialize")
    idx_serve = svc.order.index("serve_started")
    assert idx_init < idx_serve, f"on_initialize ({idx_init}) should precede serve_started ({idx_serve})"

    await svc.shutdown()


async def test_serve_task_cancelled_before_on_shutdown():
    """serve() task is cancelled before on_shutdown() runs (ordering)."""
    hassette = make_mock_hassette(sealed=False)
    svc = ServiceWithOrderTracking(hassette)
    svc.order = []

    await svc.initialize()
    await wait_for_running(svc)

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

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(CannotOverrideFinalError):

            class _BadSubclass(Service):
                async def serve(self) -> None:
                    pass

                async def initialize(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
                    pass


def test_finalmeta_blocks_service_subclass_from_overriding_shutdown():
    """FinalMeta blocks Service subclasses from overriding shutdown."""
    key = f"{__name__}._BadSubclass2"
    FinalMeta.LOADED_CLASSES.discard(key)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(CannotOverrideFinalError):

            class _BadSubclass2(Service):
                async def serve(self) -> None:
                    pass

                async def shutdown(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
                    pass


async def test_simple_service_completes_full_lifecycle():
    """A simple service can initialize and shut down cleanly."""
    svc = await make_running_simple_service()

    assert svc._serve_task is not None
    assert not svc._serve_task.done()

    report = await svc.shutdown()

    assert svc._serve_task.done()
    assert report.is_restart_safe is True, "cooperative teardown must remain restart-safe"


async def test_clean_teardown_still_permits_same_instance_restart():
    """A restart-safe report from cooperative Service teardown continues to authorize
    same-instance restart via the existing ``restart()`` round trip: the serve() task is
    replaced with a fresh one and the service returns to RUNNING.
    """
    svc = await make_running_simple_service()
    old_task = svc._serve_task
    assert old_task is not None

    await restart(svc)
    await wait_for_running(svc)

    assert svc._serve_task is not None
    assert svc._serve_task is not old_task, "restart() must spawn a fresh serve() task"
    assert not svc._serve_task.done()
    assert svc.teardown_report is None, "an accepted new initialization consumes the prior SAFE report"

    await svc.shutdown()
