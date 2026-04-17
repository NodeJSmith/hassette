"""Tests for lifecycle propagation: shutdown and initialization.

Verifies shutdown:
- shutdown() only executes once (double-call is a no-op)
- initialize() resets the flag so shutdown() works again
- initialize() clears shutdown_event
- start() resets the flag
- _finalize_shutdown() propagates shutdown to children in reverse insertion order
- Child shutdown errors are tolerated and logged
- Already-completed children are skipped
- Leaf Resources (no children) shut down normally
- Service subclasses inherit propagation

Verifies initialization propagation:
- initialize() propagates to children in insertion order
- Running children are skipped
- Starting children are skipped
- Stopped children are re-initialized
- Failed children are re-initialized
- Propagation runs before handle_running() (parent stays STARTING)
- Service propagation runs after serve task is spawned

Verifies leaf resource readiness:
- Bus is not ready after construction, only after initialize()
- Scheduler is not ready after construction, only after initialize()
- All leaf resources restore readiness after shutdown + re-initialize
"""

import asyncio
import logging
from contextlib import suppress
from unittest.mock import MagicMock

import pytest

from hassette.api.api import Api
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.bus.bus import Bus
from hassette.core.scheduler_service import _ScheduledJobQueue
from hassette.resources.base import FinalMeta, Resource, Service
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.types.enums import ResourceStatus
from hassette.utils.date_utils import now

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

    # Cleanup: await the spawned init task, then shut down
    assert resource._init_task is not None
    await resource._init_task
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


async def test_ordered_children_for_shutdown_returns_reversed():
    """_ordered_children_for_shutdown() returns children in reverse insertion order."""
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child_a = parent.add_child(ShutdownCounter)
    child_b = parent.add_child(ShutdownCounter)
    child_c = parent.add_child(ShutdownCounter)

    ordered = parent._ordered_children_for_shutdown()
    assert ordered == [child_c, child_b, child_a], f"Expected [C, B, A], got {ordered}"


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


async def test_shutdown_propagation_timeout_forces_terminal_state():
    """When child shutdown times out, timed-out children are forced to consistent terminal state."""
    hassette = _make_hassette_stub()
    hassette.config.resource_shutdown_timeout_seconds = 0.1  # very short timeout

    class HangingChild(Resource):
        """Resource whose shutdown hangs indefinitely."""

        async def on_shutdown(self) -> None:
            await asyncio.Event().wait()  # hang forever

    parent = SimpleParent(hassette)
    hanging = parent.add_child(HangingChild)
    normal = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await hanging.initialize()
    await normal.initialize()

    await parent.shutdown()

    # Parent should complete despite the hanging child
    assert parent._shutdown_completed is True
    # Hanging child should be forced to terminal state
    assert hanging._shutdown_completed is True
    assert hanging._shutting_down is False
    # Normal child should also be shut down (gather runs concurrently)
    assert normal._shutdown_completed is True


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


# ---------------------------------------------------------------------------
# Init Propagation Helpers
# ---------------------------------------------------------------------------

# Shared list to record init order across multiple children
_init_order: list[str] = []


class InitTrackingChild(Resource):
    """Resource that records its unique_name on initialization."""

    init_count: int = 0

    async def on_initialize(self) -> None:
        self.init_count += 1
        _init_order.append(self.unique_name)


class StatusCapturingChild(Resource):
    """Resource that captures the parent's status during its own initialization."""

    parent_status_during_init: ResourceStatus | None = None

    async def on_initialize(self) -> None:
        if self.parent is not None:
            self.parent_status_during_init = self.parent.status


class SimpleServiceWithServeFlag(Service):
    """Service that sets a flag once serve() starts running."""

    serve_started: bool = False

    async def serve(self) -> None:
        self.serve_started = True
        await asyncio.Event().wait()  # block forever


class ServiceInitTrackingChild(Resource):
    """Resource that records whether the parent's serve task exists during init."""

    parent_serve_task_exists: bool = False

    async def on_initialize(self) -> None:
        if isinstance(self.parent, SimpleServiceWithServeFlag):
            self.parent_serve_task_exists = self.parent._serve_task is not None


# ---------------------------------------------------------------------------
# Init Propagation Tests
# ---------------------------------------------------------------------------


async def test_init_propagates_to_children_in_insertion_order():
    """Parent with 3 children: init propagates in insertion order."""
    _init_order.clear()
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child_a = parent.add_child(InitTrackingChild)
    child_b = parent.add_child(InitTrackingChild)
    child_c = parent.add_child(InitTrackingChild)

    await parent.initialize()

    assert _init_order == [
        child_a.unique_name,
        child_b.unique_name,
        child_c.unique_name,
    ], f"Expected insertion order, got {_init_order}"
    assert child_a.init_count == 1
    assert child_b.init_count == 1
    assert child_c.init_count == 1


async def test_init_skips_running_children():
    """Pre-initialized (RUNNING) children are not re-initialized."""
    _init_order.clear()
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child_a = parent.add_child(InitTrackingChild)
    child_b = parent.add_child(InitTrackingChild)

    # Pre-initialize child_a so it reaches RUNNING
    await child_a.initialize()
    assert child_a.status == ResourceStatus.RUNNING
    _init_order.clear()  # reset tracking

    await parent.initialize()

    # Only child_b should have been initialized
    assert _init_order == [child_b.unique_name], f"Expected only child_b, got {_init_order}"
    assert child_a.init_count == 1  # not re-initialized
    assert child_b.init_count == 1


async def test_init_skips_starting_children():
    """Children in STARTING status are skipped during propagation."""
    _init_order.clear()
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child = parent.add_child(InitTrackingChild)

    # Force child into STARTING status
    await child.handle_starting()
    assert child.status == ResourceStatus.STARTING

    await parent.initialize()

    # Child should have been skipped
    assert _init_order == [], f"Expected empty, got {_init_order}"
    assert child.init_count == 0


async def test_init_reinitializes_stopped_children():
    """Stopped children are re-initialized when parent initializes."""
    _init_order.clear()
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child = parent.add_child(InitTrackingChild)

    # Initialize then shut down to reach STOPPED
    await child.initialize()
    await child.shutdown()
    assert child.status == ResourceStatus.STOPPED
    _init_order.clear()

    await parent.initialize()

    assert _init_order == [child.unique_name], f"Expected child re-init, got {_init_order}"
    assert child.init_count == 2  # once direct, once via propagation


async def test_init_reinitializes_failed_children():
    """Failed children are re-initialized when parent initializes."""
    _init_order.clear()
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child = parent.add_child(InitTrackingChild)

    # Force child into FAILED status
    await child.handle_failed(RuntimeError("test failure"))
    assert child.status == ResourceStatus.FAILED

    await parent.initialize()

    assert _init_order == [child.unique_name], f"Expected child re-init, got {_init_order}"
    assert child.init_count == 1


async def test_init_propagation_runs_before_handle_running():
    """Parent is still STARTING during child initialization, RUNNING after."""
    hassette = _make_hassette_stub()
    parent = SimpleParent(hassette)

    child = parent.add_child(StatusCapturingChild)

    await parent.initialize()

    assert child.parent_status_during_init == ResourceStatus.STARTING, (
        f"Expected STARTING during child init, got {child.parent_status_during_init}"
    )
    assert parent.status == ResourceStatus.RUNNING


async def test_service_init_propagation_after_serve_spawn():
    """Service child init runs after serve task is spawned."""
    hassette = _make_hassette_stub()
    parent_svc = SimpleServiceWithServeFlag(hassette)

    child = parent_svc.add_child(ServiceInitTrackingChild)

    await parent_svc.initialize()
    # Let serve task start
    await asyncio.sleep(0.01)

    assert child.parent_serve_task_exists is True, "Child should see serve task during init"

    # Cleanup
    await parent_svc.shutdown()


async def test_service_status_is_starting_after_initialize():
    """Service.initialize() returns with status STARTING, not RUNNING.

    Unlike Resource.initialize() which calls handle_running() at the end,
    Service defers handle_running() to _serve_wrapper(). This is intentional:
    Services are ready when serve() actually starts, not when initialize() returns.
    """
    hassette = _make_hassette_stub()
    svc = SimpleServiceWithServeFlag(hassette)

    await svc.initialize()

    assert svc.status == ResourceStatus.STARTING, f"Service should be STARTING after initialize(), got {svc.status}"

    # Cleanup
    await svc.shutdown()


# ---------------------------------------------------------------------------
# Leaf Resource Readiness Tests (WP04)
# ---------------------------------------------------------------------------


def _make_leaf(hassette, leaf_type: str) -> Resource:
    """Create a leaf resource by type name, returning the resource to check readiness on."""
    if leaf_type == "Bus":
        return Bus(hassette)
    if leaf_type == "Scheduler":
        return Scheduler(hassette)
    if leaf_type == "Api":
        return Api(hassette)
    if leaf_type == "ApiSyncFacade":
        api = Api(hassette)
        return api.sync
    if leaf_type == "_ScheduledJobQueue":
        return _ScheduledJobQueue(hassette)
    raise ValueError(f"Unknown leaf type: {leaf_type}")


_LEAF_TYPES = ["Bus", "Scheduler", "Api", "ApiSyncFacade", "_ScheduledJobQueue"]


@pytest.mark.parametrize("leaf_type", _LEAF_TYPES)
async def test_leaf_ready_after_initialize_not_after_init(leaf_type: str):
    """Leaf resources should NOT be ready after construction — only after initialize()."""
    hassette = _make_hassette_stub()
    resource = _make_leaf(hassette, leaf_type)

    assert not resource.is_ready(), f"{leaf_type} should not be ready after construction"

    # For ApiSyncFacade, initialize the parent Api (which propagates to the facade)
    if leaf_type == "ApiSyncFacade":
        await resource.parent.initialize()
    else:
        await resource.initialize()

    assert resource.is_ready(), f"{leaf_type} should be ready after initialize()"


@pytest.mark.parametrize("leaf_type", _LEAF_TYPES)
async def test_leaf_ready_after_restart(leaf_type: str):
    """After shutdown + re-initialize, leaf resources restore readiness."""
    hassette = _make_hassette_stub()
    resource = _make_leaf(hassette, leaf_type)
    init_target = resource.parent if leaf_type == "ApiSyncFacade" else resource

    await init_target.initialize()
    assert resource.is_ready()

    await init_target.shutdown()
    assert not resource.is_ready(), f"{leaf_type} should not be ready after shutdown"

    await init_target.initialize()
    assert resource.is_ready(), f"{leaf_type} should be ready after re-initialize"


# ---------------------------------------------------------------------------
# Scheduler.on_shutdown / App propagation Tests (WP05)
# ---------------------------------------------------------------------------


def _make_dummy_job(owner_id: str, name: str = "test_job") -> ScheduledJob:
    """Create a minimal ScheduledJob for testing."""

    async def _noop() -> None:
        pass

    return ScheduledJob(owner_id=owner_id, next_run=now(), job=_noop, name=name)


async def test_scheduler_on_shutdown_dequeues_all_jobs():
    """Scheduler.on_shutdown() awaits _remove_all_jobs (via remove_jobs_by_owner)."""
    hassette = _make_hassette_stub()
    # Make add_job a sync MagicMock so calling it doesn't create an unawaited coroutine
    hassette._scheduler_service.add_job = MagicMock()
    scheduler = Scheduler(hassette)

    await scheduler.initialize()

    # Add a job so we know there's something to remove
    scheduler.add_job(
        _make_dummy_job(owner_id=scheduler.owner_id, name="test_job"),
    )

    await scheduler.shutdown()

    # remove_jobs_by_owner is called by remove_all_jobs, and it's on the mock service
    hassette._scheduler_service.remove_jobs_by_owner.assert_awaited_once_with(scheduler.owner_id)


async def test_app_shutdown_propagates_to_bus_and_scheduler():
    """App shutdown propagates to Bus.on_shutdown and Scheduler.on_shutdown via children."""
    hassette = _make_hassette_stub()
    hassette.config.app_shutdown_timeout_seconds = 5
    hassette.config.apps_log_level = "DEBUG"

    app = App(hassette, app_config=AppConfig(instance_name="test_app"), index=0)

    await app.initialize()

    # Verify bus and scheduler are children that will receive propagated shutdown
    assert app.bus in [child for child in app.children]
    assert app.scheduler in [child for child in app.children]

    # Both should be ready after init
    assert app.bus.is_ready()
    assert app.scheduler.is_ready()

    await app.shutdown()

    # After shutdown, children should have been shut down via propagation
    assert not app.bus.is_ready(), "Bus should not be ready after app shutdown"
    assert not app.scheduler.is_ready(), "Scheduler should not be ready after app shutdown"


# ---------------------------------------------------------------------------
# _force_terminal() Tests (WP09)
# ---------------------------------------------------------------------------


class StubResource(Resource):
    """Simple resource for testing _force_terminal()."""

    pass


class StubService(Service):
    """Simple service for testing _force_terminal()."""

    async def serve(self) -> None:
        await asyncio.Event().wait()


async def test_force_terminal_recurses_to_grandchildren():
    """_force_terminal() recursively sets all descendants to STOPPED with _shutdown_completed=True."""
    hassette = _make_hassette_stub()
    root = StubResource(hassette)

    child = root.add_child(StubResource)
    grandchild = child.add_child(StubResource)

    # Initialize all so they're in RUNNING state
    await root.initialize()

    assert root.status == ResourceStatus.RUNNING
    assert child.status == ResourceStatus.RUNNING
    assert grandchild.status == ResourceStatus.RUNNING

    root._force_terminal()

    assert root.status == ResourceStatus.STOPPED
    assert root._shutdown_completed is True
    assert child.status == ResourceStatus.STOPPED
    assert child._shutdown_completed is True
    assert grandchild.status == ResourceStatus.STOPPED
    assert grandchild._shutdown_completed is True


async def test_force_terminal_cancels_task_bucket():
    """_force_terminal() calls cancel_all_sync() on each resource's task bucket."""
    hassette = _make_hassette_stub()
    root = StubResource(hassette)
    child = root.add_child(StubResource)

    await root.initialize()

    # Patch cancel_all_sync on each resource's task bucket
    root.task_bucket.cancel_all_sync = MagicMock()
    child.task_bucket.cancel_all_sync = MagicMock()

    root._force_terminal()

    root.task_bucket.cancel_all_sync.assert_called_once()
    child.task_bucket.cancel_all_sync.assert_called_once()


async def test_force_terminal_skips_completed_children():
    """_force_terminal() returns early for resources with _shutdown_completed=True."""
    hassette = _make_hassette_stub()
    root = StubResource(hassette)
    child = root.add_child(StubResource)

    await root.initialize()

    # Pre-complete the child's shutdown
    await child.shutdown()
    assert child._shutdown_completed is True
    assert child.status == ResourceStatus.STOPPED

    # Track whether cancel() is called on the already-completed child
    child.cancel = MagicMock()

    root._force_terminal()

    # Root should be force-terminated
    assert root._shutdown_completed is True
    assert root.status == ResourceStatus.STOPPED
    # Child was already completed — cancel() should NOT have been called
    child.cancel.assert_not_called()


async def test_service_force_terminal_cancels_serve_task():
    """Service._force_terminal() cancels the _serve_task before calling super()."""
    hassette = _make_hassette_stub()
    svc = StubService(hassette)

    await svc.initialize()
    # Let the serve task start
    await asyncio.sleep(0.01)

    assert svc._serve_task is not None
    assert not svc._serve_task.done()

    svc._force_terminal()

    # _force_terminal is synchronous; the task is marked for cancellation but needs
    # an event loop tick to actually finish. Verify cancelling() is True.
    assert svc._serve_task.cancelling() > 0, "serve task should be marked for cancellation"
    assert svc.status == ResourceStatus.STOPPED
    assert svc._shutdown_completed is True

    # Let the event loop process the cancellation
    await asyncio.sleep(0)
    assert svc._serve_task.done(), "serve task should be done after yielding to event loop"


# ---------------------------------------------------------------------------
# _on_children_stopped() Hook Tests (WP09b)
# ---------------------------------------------------------------------------


class HookTrackingParent(Resource):
    """Resource that records whether _on_children_stopped was called."""

    hook_called: bool = False

    async def _on_children_stopped(self) -> None:
        await super()._on_children_stopped()
        self.hook_called = True


async def test_on_children_stopped_called_on_clean_shutdown():
    """_on_children_stopped() fires when children shut down cleanly."""
    hassette = _make_hassette_stub()
    parent = HookTrackingParent(hassette)
    child = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child.initialize()

    await parent.shutdown()

    assert parent.hook_called is True, "_on_children_stopped should have been called"
    assert child._shutdown_completed is True


async def test_on_children_stopped_skipped_on_timeout():
    """_on_children_stopped() is NOT called when child shutdown times out."""
    hassette = _make_hassette_stub()
    hassette.config.resource_shutdown_timeout_seconds = 0.1

    class HangingChild(Resource):
        async def on_shutdown(self) -> None:
            await asyncio.Event().wait()

    parent = HookTrackingParent(hassette)
    parent.add_child(HangingChild)

    await parent.initialize()

    await parent.shutdown()

    assert parent.hook_called is False, "_on_children_stopped should NOT be called on timeout"


# ---------------------------------------------------------------------------
# cleanup() Timeout Tests (WP09b)
# ---------------------------------------------------------------------------


async def test_cleanup_timeout_fires_on_hung_cleanup():
    """When cleanup() hangs, asyncio.timeout catches it and logs a warning."""
    hassette = _make_hassette_stub()
    hassette.config.resource_shutdown_timeout_seconds = 0.1

    class HungCleanupResource(Resource):
        async def cleanup(self, timeout: int | None = None) -> None:
            await asyncio.Event().wait()  # hang forever

    resource = HungCleanupResource(hassette)
    await resource.initialize()

    # Should complete without hanging — the timeout wrapping cleanup() should fire
    await resource.shutdown()

    assert resource._shutdown_completed is True


# ---------------------------------------------------------------------------
# _initializing Warning Tests (WP09b)
# ---------------------------------------------------------------------------


async def test_initializing_warning_on_shutdown_during_init(caplog):
    """_initializing=True + shutdown_event.set() -> DEBUG log; without -> WARNING."""

    hassette = _make_hassette_stub()

    # Case 1: shutdown requested during init (shutdown_event is set) -> DEBUG
    resource1 = StubResource(hassette)
    resource1._initializing = True
    resource1.shutdown_event.set()

    with caplog.at_level(logging.DEBUG):
        await resource1._finalize_shutdown()

    debug_msgs = [r for r in caplog.records if "shutting down with _initializing=True" in r.message]
    assert any(r.levelno == logging.DEBUG for r in debug_msgs), (
        f"Expected DEBUG log for shutdown-during-init, got levels: {[r.levelname for r in debug_msgs]}"
    )
    assert resource1._initializing is False

    caplog.clear()

    # Case 2: _initializing=True without shutdown_event -> WARNING (indicates a bug)
    resource2 = StubResource(hassette)
    resource2._initializing = True
    resource2.shutdown_event.clear()

    with caplog.at_level(logging.DEBUG):
        await resource2._finalize_shutdown()

    warning_msgs = [r for r in caplog.records if "shutting down with _initializing=True" in r.message]
    assert any(r.levelno == logging.WARNING for r in warning_msgs), (
        f"Expected WARNING log for unexpected _initializing, got levels: {[r.levelname for r in warning_msgs]}"
    )


# ---------------------------------------------------------------------------
# Total Shutdown Timeout Tests (WP11)
# ---------------------------------------------------------------------------


class _HangingChild(Resource):
    """Resource whose shutdown hangs indefinitely."""

    async def on_shutdown(self) -> None:
        await asyncio.Event().wait()


# Pre-register so FinalMeta allows the shutdown() override on this test helper
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.test_lifecycle_propagation._TotalTimeoutRoot")


class _TotalTimeoutRoot(Resource):
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
            async with asyncio.timeout(self.hassette.config.total_shutdown_timeout_seconds):
                await super().shutdown()
        except TimeoutError:
            self.logger.critical(
                "Total shutdown timeout (%ss) exceeded — forcing termination",
                self.hassette.config.total_shutdown_timeout_seconds,
            )
            for child in self.children:
                child._force_terminal()
        finally:
            self._order_counter += 1
            self._shutdown_completed_order = self._order_counter
            self._shutdown_completed = True
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
    hassette = _make_hassette_stub()
    hassette.config.total_shutdown_timeout_seconds = 0.2
    hassette.config.resource_shutdown_timeout_seconds = 5  # per-level timeout is much larger

    root = _TotalTimeoutRoot(hassette)
    hanging = root.add_child(_HangingChild)
    normal = root.add_child(ShutdownCounter)

    await root.initialize()
    await hanging.initialize()
    await normal.initialize()

    start = asyncio.get_event_loop().time()
    await root.shutdown()
    elapsed = asyncio.get_event_loop().time() - start

    # Should complete in roughly total_shutdown_timeout_seconds, not resource_shutdown_timeout_seconds
    assert elapsed < 1.0, f"Shutdown took {elapsed:.2f}s — total timeout should have capped it"
    assert root._shutdown_completed is True
    assert hanging._shutdown_completed is True


async def test_total_timeout_force_patches_all_descendants():
    """On total timeout, _force_terminal() is called recursively on all descendants."""
    hassette = _make_hassette_stub()
    hassette.config.total_shutdown_timeout_seconds = 0.1
    hassette.config.resource_shutdown_timeout_seconds = 5

    root = _TotalTimeoutRoot(hassette)
    hanging = root.add_child(_HangingChild)
    grandchild = hanging.add_child(StubResource)

    await root.initialize()
    await hanging.initialize()
    await grandchild.initialize()

    await root.shutdown()

    # All descendants should be force-terminated
    assert hanging._shutdown_completed is True
    assert hanging.status == ResourceStatus.STOPPED
    assert grandchild._shutdown_completed is True
    assert grandchild.status == ResourceStatus.STOPPED


async def test_total_timeout_finally_always_closes_streams():
    """close_streams() equivalent is called even when the total timeout fires."""
    hassette = _make_hassette_stub()
    hassette.config.total_shutdown_timeout_seconds = 0.1
    hassette.config.resource_shutdown_timeout_seconds = 5

    root = _TotalTimeoutRoot(hassette)
    root.add_child(_HangingChild)

    await root.initialize()

    await root.shutdown()

    assert root._close_streams_called is True, "close_streams must be called even on total timeout"


async def test_total_timeout_sets_shutdown_completed_first():
    """_shutdown_completed=True is set before handle_stop() and close_streams() in the finally block."""
    hassette = _make_hassette_stub()
    hassette.config.total_shutdown_timeout_seconds = 0.1
    hassette.config.resource_shutdown_timeout_seconds = 5

    root = _TotalTimeoutRoot(hassette)
    root.add_child(_HangingChild)

    await root.initialize()

    await root.shutdown()

    # _shutdown_completed_order should be less than handle_stop and close_streams
    assert root._shutdown_completed_order < root._handle_stop_order, (
        f"_shutdown_completed (order={root._shutdown_completed_order}) must be set before "
        f"handle_stop (order={root._handle_stop_order})"
    )
    assert root._shutdown_completed_order < root._close_streams_order, (
        f"_shutdown_completed (order={root._shutdown_completed_order}) must be set before "
        f"close_streams (order={root._close_streams_order})"
    )
