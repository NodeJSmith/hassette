"""Tests for initialization propagation.

Verifies:
- initialize() propagates to children in insertion order
- Running children are skipped
- Starting children are skipped
- Stopped children are re-initialized
- Failed children are re-initialized
- Propagation runs before handle_running() (parent stays STARTING)
- Service propagation runs after serve task is spawned
- Service status is STARTING (not RUNNING) after initialize() returns

Verifies leaf resource readiness:
- Bus is not ready after construction, only after initialize()
- Scheduler is not ready after construction, only after initialize()
- All leaf resources restore readiness after shutdown + re-initialize
"""

import asyncio

import pytest

from hassette.api.api import Api
from hassette.bus.bus import Bus
from hassette.core.scheduler_service import _ScheduledJobQueue
from hassette.exceptions import LifecycleReentryError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import handle_failed, handle_starting
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.scheduler.scheduler import Scheduler
from hassette.types.enums import ResourceStatus
from tests.support.factories import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource, wait_for_running

from .conftest import SimpleParent, make_parent_with_child

# Shared list to record init order across multiple children
_init_order: list[str] = []


LEAF_TYPES = ["Bus", "Scheduler", "Api", "ApiSyncFacade", "_ScheduledJobQueue"]


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

    restart_spec = RestartSpec()
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


async def test_init_propagates_to_children_in_insertion_order():
    """Parent with 3 children: init propagates in insertion order."""
    parent, child_a = make_parent_with_child(_init_order, InitTrackingChild)
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
    parent, child_a = make_parent_with_child(_init_order, InitTrackingChild)
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
    parent, child = make_parent_with_child(_init_order, InitTrackingChild)

    # Force child into STARTING status
    await handle_starting(child)
    assert child.status == ResourceStatus.STARTING

    await parent.initialize()

    # Child should have been skipped
    assert _init_order == [], f"Expected empty, got {_init_order}"
    assert child.init_count == 0


async def test_init_reinitializes_stopped_children():
    """Stopped children are re-initialized when parent initializes."""
    parent, child = make_parent_with_child(_init_order, InitTrackingChild)

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
    parent, child = make_parent_with_child(_init_order, InitTrackingChild)

    # Force child into FAILED status
    await handle_failed(child, RuntimeError("test failure"))
    assert child.status == ResourceStatus.FAILED

    await parent.initialize()

    assert _init_order == [child.unique_name], f"Expected child re-init, got {_init_order}"
    assert child.init_count == 1


async def test_init_propagation_runs_before_handle_running():
    """Parent is still STARTING during child initialization, RUNNING after."""
    hassette = make_mock_hassette(sealed=False)
    parent = SimpleParent(hassette)

    child = parent.add_child(StatusCapturingChild)

    await parent.initialize()

    assert child.parent_status_during_init == ResourceStatus.STARTING, (
        f"Expected STARTING during child init, got {child.parent_status_during_init}"
    )
    assert parent.status == ResourceStatus.RUNNING


async def test_service_init_propagation_after_serve_spawn():
    """Service child init runs after serve task is spawned."""
    hassette = make_mock_hassette(sealed=False)
    parent_svc = SimpleServiceWithServeFlag(hassette)

    child = parent_svc.add_child(ServiceInitTrackingChild)

    await parent_svc.initialize()
    await wait_for_running(parent_svc)

    assert child.parent_serve_task_exists is True, "Child should see serve task during init"

    # Cleanup
    await parent_svc.shutdown()


async def test_service_status_is_starting_before_serve_task_runs():
    """Service._initialize_body() spawns the serve task with status still STARTING.

    Unlike Resource._initialize_body() which calls handle_running() at the end,
    Service defers handle_running() to _serve_wrapper(). This is intentional:
    Services are ready when serve() actually starts, not when the initialize body returns.

    ``initialize()`` itself is now the coordinator front door: it runs ``_initialize_body()``
    in its own owned ``_init_task`` (every initialization path, including a direct
    ``await initialize()``, must be tracked by that one task so concurrent callers and shutdown
    can join or observe it). That task-based execution means the event loop gets a chance to
    run the freshly spawned serve task's synchronous prefix (through its first suspension
    point) before ``await svc.initialize()`` returns to its caller -- so by the time
    ``initialize()`` returns, ``handle_running()`` has typically already run and status has
    already advanced to RUNNING. The STARTING-not-RUNNING guarantee this test protects now
    applies to the body itself, observed via a status-capturing hook, not to the state visible
    after ``initialize()`` returns.
    """
    hassette = make_mock_hassette(sealed=False)
    svc = SimpleServiceWithServeFlag(hassette)

    statuses_during_body: list[ResourceStatus] = []

    async def _capture_before_serve_spawn() -> None:
        statuses_during_body.append(svc.status)

    svc.after_initialize = _capture_before_serve_spawn  # runs after serve task spawn, before body returns

    await svc.initialize()

    assert statuses_during_body == [ResourceStatus.STARTING], (
        f"Service body should still be STARTING right after spawning serve(), got {statuses_during_body}"
    )

    # Cleanup
    await svc.shutdown()


def make_leaf(hassette, leaf_type: str) -> Resource:
    """Create a leaf resource by type name, returning the resource to check readiness on."""
    if leaf_type == "Bus":
        return Bus(hassette, parent=hassette)
    if leaf_type == "Scheduler":
        return Scheduler(hassette, parent=hassette)
    if leaf_type == "Api":
        return Api(hassette)
    if leaf_type == "ApiSyncFacade":
        api = Api(hassette)
        return api.sync
    if leaf_type == "_ScheduledJobQueue":
        return _ScheduledJobQueue(hassette)
    raise ValueError(f"Unknown leaf type: {leaf_type}")


@pytest.mark.parametrize("leaf_type", LEAF_TYPES)
async def test_leaf_ready_after_initialize_not_after_init(leaf_type: str):
    """Leaf resources should NOT be ready after construction — only after initialize()."""
    hassette = make_mock_hassette(sealed=False)
    resource = make_leaf(hassette, leaf_type)

    assert not resource.is_ready(), f"{leaf_type} should not be ready after construction"

    # For ApiSyncFacade, initialize the parent Api (which propagates to the facade)
    if leaf_type == "ApiSyncFacade":
        await resource.parent.initialize()
    else:
        await resource.initialize()

    assert resource.is_ready(), f"{leaf_type} should be ready after initialize()"


@pytest.mark.parametrize("leaf_type", LEAF_TYPES)
async def test_leaf_ready_after_restart(leaf_type: str):
    """After shutdown + re-initialize, leaf resources restore readiness."""
    hassette = make_mock_hassette(sealed=False)
    resource = make_leaf(hassette, leaf_type)
    init_target = resource.parent if leaf_type == "ApiSyncFacade" else resource

    await init_target.initialize()
    assert resource.is_ready()

    await init_target.shutdown()
    assert not resource.is_ready(), f"{leaf_type} should not be ready after shutdown"

    await init_target.initialize()
    assert resource.is_ready(), f"{leaf_type} should be ready after re-initialize"


async def test_initialize_waits_for_active_shutdown_before_evaluating_report():
    """A concurrent ``initialize()`` call made while a shutdown is already in flight waits for
    that shutdown's outcome (shielding ``_shutdown_task``) before deciding whether a new
    initialization attempt is admitted -- it does not race ahead of the report the shutdown
    attempt is about to store.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)
    await resource.initialize()
    assert resource.status == ResourceStatus.RUNNING

    shutdown_entered = asyncio.Event()
    shutdown_release = asyncio.Event()

    async def _gated_on_shutdown() -> None:
        shutdown_entered.set()
        await shutdown_release.wait()

    resource.on_shutdown = _gated_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    shutdown_task = asyncio.create_task(resource.shutdown())
    await asyncio.wait_for(shutdown_entered.wait(), timeout=1)

    init_entered = asyncio.Event()

    async def _tracking_on_initialize() -> None:
        init_entered.set()

    resource.on_initialize = _tracking_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    init_task = asyncio.create_task(resource.initialize())

    # While shutdown is still gated, the concurrent initialize() must not have proceeded past
    # its shielded wait on the shutdown task -- it must not have reached a new attempt's
    # on_initialize() hook yet. Bounded wait expecting a timeout proves this deterministically.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(init_entered.wait(), timeout=0.2)
    assert not init_entered.is_set()
    assert not init_task.done()

    # Release the shutdown; only now may initialize() evaluate the stored report and proceed.
    shutdown_release.set()
    report = await shutdown_task
    await init_task

    assert report.is_restart_safe is True
    assert init_entered.is_set(), "initialize() must proceed only after the active shutdown's report exists"
    assert resource.status == ResourceStatus.RUNNING


async def test_shutdown_cancels_and_observes_initializer_before_shutdown_hooks():
    """``shutdown()`` cancels and bound-observes an active initializer *before* running any
    shutdown hooks (``before_shutdown``/``on_shutdown``) -- the initializer must be cancelled
    first, not concurrently or after.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)

    init_entered = asyncio.Event()
    init_cancelled = asyncio.Event()

    async def _gated_on_initialize() -> None:
        init_entered.set()
        try:
            await asyncio.Event().wait()  # block forever until cancelled
        except asyncio.CancelledError:
            init_cancelled.set()
            raise

    resource.on_initialize = _gated_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    init_task = asyncio.create_task(resource.initialize())
    await asyncio.wait_for(init_entered.wait(), timeout=1)

    shutdown_hook_entered = asyncio.Event()

    async def _tracking_on_shutdown() -> None:
        # Must only run after the initializer has already been observed as cancelled.
        assert init_cancelled.is_set(), "shutdown hooks must not run before the initializer is cancelled/observed"
        shutdown_hook_entered.set()

    resource.on_shutdown = _tracking_on_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    report = await resource.shutdown()

    assert init_cancelled.is_set()
    assert shutdown_hook_entered.is_set()
    assert report.is_restart_safe is True

    with pytest.raises(asyncio.CancelledError):
        await init_task


async def test_initialize_rejects_reentrant_call_from_initialize_hook():
    """An initialization hook that calls ``self.initialize()`` (or another lifecycle front
    door) on itself must be rejected with ``LifecycleReentryError`` before any duplicate task
    creation or state mutation -- the calling task *is* the initialization coordinator being
    awaited.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = ConcreteResource(hassette=hassette)

    captured: list[BaseException] = []
    call_count = 0

    async def _reentrant_on_initialize() -> None:
        nonlocal call_count
        call_count += 1
        try:
            await resource.initialize()
        except LifecycleReentryError as exc:
            captured.append(exc)

    resource.on_initialize = _reentrant_on_initialize  # pyright: ignore[reportAttributeAccessIssue]

    await resource.initialize()

    assert len(captured) == 1
    assert isinstance(captured[0], LifecycleReentryError)
    assert call_count == 1, "the re-entrant call must not have started a second attempt"
    assert resource.status == ResourceStatus.RUNNING

    await resource.shutdown()
