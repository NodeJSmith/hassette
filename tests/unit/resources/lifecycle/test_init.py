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
from hassette.resources.base import Resource, RestartSpec, Service
from hassette.scheduler.scheduler import Scheduler
from hassette.test_utils import make_mock_hassette, wait_for
from hassette.types.enums import ResourceStatus

from .conftest import SimpleParent

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
    _init_order.clear()
    hassette = make_mock_hassette(sealed=False)
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
    hassette = make_mock_hassette(sealed=False)
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
    hassette = make_mock_hassette(sealed=False)
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
    hassette = make_mock_hassette(sealed=False)
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
    hassette = make_mock_hassette(sealed=False)
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
    await wait_for(lambda: parent_svc.status == ResourceStatus.RUNNING, desc="parent service RUNNING")

    assert child.parent_serve_task_exists is True, "Child should see serve task during init"

    # Cleanup
    await parent_svc.shutdown()


async def test_service_status_is_starting_after_initialize():
    """Service.initialize() returns with status STARTING, not RUNNING.

    Unlike Resource.initialize() which calls handle_running() at the end,
    Service defers handle_running() to _serve_wrapper(). This is intentional:
    Services are ready when serve() actually starts, not when initialize() returns.
    """
    hassette = make_mock_hassette(sealed=False)
    svc = SimpleServiceWithServeFlag(hassette)

    await svc.initialize()

    assert svc.status == ResourceStatus.STARTING, f"Service should be STARTING after initialize(), got {svc.status}"

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


LEAF_TYPES = ["Bus", "Scheduler", "Api", "ApiSyncFacade", "_ScheduledJobQueue"]


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
