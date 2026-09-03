"""Tests for _force_terminal() and related shutdown edge cases.

Verifies:
- Scheduler.on_shutdown() dequeues all jobs
- App shutdown propagates to Bus and Scheduler
- _force_terminal() recurses to grandchildren
- _force_terminal() cancels task buckets
- _force_terminal() still recurses into already-completed children
- _force_terminal() records FORCED_TERMINAL restart-unsafe evidence before cancelling work
- _force_terminal() leaves an already-completed SAFE report unchanged
- Service._force_terminal() cancels serve task
- _on_children_stopped() hook fires on clean shutdown
- _on_children_stopped() is skipped on timeout
- cleanup() timeout is enforced
- A completed shutdown() clears the read-only `initializing` property regardless of how
  shutdown_event was set beforehand
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.cache import AsyncCache
from hassette.resources.base import Resource
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.scheduler.classes import Job
from hassette.scheduler.scheduler import Scheduler
from hassette.types.enums import ResourceStatus
from tests.support.factories import make_scheduled_job
from tests.support.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from tests.support.mock_hassette import make_mock_hassette

from .conftest import HangingChild, ShutdownCounter, SimpleParent, make_running_simple_service


async def test_scheduler_on_shutdown_dequeues_all_jobs():
    """Scheduler.on_shutdown() awaits remove_all_jobs (via remove_jobs)."""
    hassette = make_mock_hassette(sealed=False)

    # add_job is now awaited inline — must be an AsyncMock
    async def _add_job(job: Job) -> None:
        job.mark_registered(1)

    hassette.scheduler_service.add_job = AsyncMock(side_effect=_add_job)
    scheduler = Scheduler(hassette, parent=hassette)

    await scheduler.initialize()

    # Add a job so we know there's something to remove
    job = make_scheduled_job(owner_id=scheduler.owner_id, name="test_job")
    await scheduler.add_job(job)

    await scheduler.shutdown()

    # remove_jobs is called by remove_all_jobs with this scheduler's own owned jobs
    # (including waiting/completed/manual jobs that remove_jobs_by_owner's heap-only scan
    # would miss), and it's on the mock service.
    hassette.scheduler_service.remove_jobs.assert_awaited_once_with([job])


async def test_app_shutdown_propagates_to_bus_and_scheduler():
    """App shutdown propagates to Bus.on_shutdown and Scheduler.on_shutdown via children."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.app_shutdown_timeout_seconds = 5
    hassette.config.logging.apps = "DEBUG"

    app = App(hassette, app_config=AppConfig(instance_name="test_app"), index=0, app_key="test_app")

    await app.initialize()

    # Verify bus and scheduler are children that will receive propagated shutdown
    assert app.bus in list(app.children)
    assert app.scheduler in list(app.children)

    # Both should be ready after init
    assert app.bus.is_ready()
    assert app.scheduler.is_ready()

    await app.shutdown()

    # After shutdown, children should have been shut down via propagation
    assert not app.bus.is_ready(), "Bus should not be ready after app shutdown"
    assert not app.scheduler.is_ready(), "Scheduler should not be ready after app shutdown"


async def test_force_terminal_stops_cache_connections():
    """App._force_terminal() must stop the cache's aiosqlite connections synchronously.

    Regression: force-terminal intentionally skips cleanup()/on_shutdown() (see
    Resource._force_terminal()'s docstring) because production assumes force-terminal is nearly
    always followed by process exit. That assumption does not hold in a long-lived process --
    notably the test suite -- where a leaked aiosqlite.Connection instead sits open until
    Python's GC eventually reclaims it, firing an unraisable-exception warning attributed to
    whichever test happens to be running at that moment. Observed in CI:
    tests/integration/test_hot_reload.py::TestBasicHotReload::test_hot_reload_starts_newly_enabled_app
    leaked two open connections this way when an app's shutdown was force-terminated.
    """
    hassette = make_mock_hassette(sealed=False)
    app = App(hassette, app_config=AppConfig(instance_name="test_app"), index=0, app_key="test_app")

    await app.initialize()

    assert isinstance(app.cache, AsyncCache)
    write_conn = app.cache._write
    read_conn = app.cache._read
    assert write_conn is not None
    assert read_conn is not None

    app._force_terminal()

    assert app.cache._write is None
    assert app.cache._read is None
    assert write_conn._running is False, "the write connection's background thread must be signaled to stop"
    assert read_conn._running is False, "the read connection's background thread must be signaled to stop"


async def test_force_terminal_recurses_to_grandchildren():
    """_force_terminal() recursively sets all descendants to STOPPED with shutdown_completed=True."""
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)

    child = root.add_child(SimpleParent)
    grandchild = child.add_child(SimpleParent)

    # Initialize all so they're in RUNNING state
    await root.initialize()

    assert root.status == ResourceStatus.RUNNING
    assert child.status == ResourceStatus.RUNNING
    assert grandchild.status == ResourceStatus.RUNNING

    root._force_terminal()

    assert root.status == ResourceStatus.STOPPED
    assert root.shutdown_completed is True
    assert child.status == ResourceStatus.STOPPED
    assert child.shutdown_completed is True
    assert grandchild.status == ResourceStatus.STOPPED
    assert grandchild.shutdown_completed is True


async def test_force_terminal_cancels_task_bucket():
    """_force_terminal() calls cancel_all_sync() on each resource's task bucket."""
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)
    child = root.add_child(SimpleParent)

    await root.initialize()

    # Patch cancel_all_sync on each resource's task bucket
    root.task_bucket.cancel_all_sync = MagicMock()
    child.task_bucket.cancel_all_sync = MagicMock()

    root._force_terminal()

    root.task_bucket.cancel_all_sync.assert_called_once()
    child.task_bucket.cancel_all_sync.assert_called_once()


async def test_force_terminal_still_recurses_into_already_completed_children():
    """Regression: _force_terminal() must still recurse into a child whose own report was
    already stored (e.g. an already-completed shutdown) -- only the report itself is left
    unchanged (see test_force_terminal_leaves_completed_safe_child_report_unchanged below), not
    the recursive call. An early return here would also skip any *grandchildren* under that
    child, which is exactly what Hassette._shutdown_body() relies on this method reaching
    unconditionally on its total-timeout path.
    """
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)
    child = root.add_child(SimpleParent)

    await root.initialize()

    # Pre-complete the child's shutdown
    await child.shutdown()
    assert child.shutdown_completed is True
    assert child.status == ResourceStatus.STOPPED

    # cancel() is a module-level function (hassette.resources.lifecycle), not a method —
    # patch it at the call site (base.py) rather than reassigning an instance attribute,
    # since _force_terminal() calls the free function directly.
    with patch("hassette.resources.base.cancel") as mock_cancel:
        root._force_terminal()

        # Root should be force-terminated
        assert root.shutdown_completed is True
        assert root.status == ResourceStatus.STOPPED
        # The already-completed child is still reached by the recursive call — cancel() is a
        # safe no-op on it (nothing left to cancel), but it must still be called so a hung
        # grandchild under it would also be reached.
        assert mock_cancel.call_args_list == [call(root), call(child)]


async def test_force_terminal_stores_forced_terminal_report_before_cancelling_work():
    """_force_terminal() stores its restart-unsafe report (FORCED_TERMINAL) before cancelling
    anything -- ``cancel()``, ``task_bucket.cancel_all_sync()``, and the recursive descendant
    call all happen strictly after ``self._teardown_report`` already reflects the forced
    outcome, so a caller inspecting the report mid-cancellation never sees ``None`` or a report
    that doesn't yet name the forced-terminal cause.
    """
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)
    await root.initialize()

    order: list[str] = []
    original_cancel_all_sync = root.task_bucket.cancel_all_sync

    def _spy_cancel_all_sync() -> None:
        assert root._teardown_report is not None, "report must already be stored before cancel_all_sync() runs"
        order.append("cancel_all_sync")
        original_cancel_all_sync()

    root.task_bucket.cancel_all_sync = _spy_cancel_all_sync  # pyright: ignore[reportAttributeAccessIssue]

    with patch("hassette.resources.base.cancel") as mock_cancel:
        mock_cancel.side_effect = lambda _r: order.append("cancel")
        root._force_terminal()

    report = root.teardown_report
    assert report is not None
    assert report.is_restart_safe is False
    assert TeardownCause.FORCED_TERMINAL in report.causes
    assert order == ["cancel", "cancel_all_sync"], "both cancellation calls must run after the report was stored"
    assert root.status == ResourceStatus.STOPPED


async def test_force_terminal_leaves_completed_safe_child_report_unchanged():
    """A child that already completed a clean, restart-safe shutdown before a parent's
    force-terminal call keeps its own report unchanged -- force-terminal only degrades resources
    that have not yet completed a teardown attempt.
    """
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)
    child = root.add_child(ShutdownCounter)

    await root.initialize()

    await child.shutdown()
    safe_report = child.teardown_report
    assert safe_report is not None
    assert safe_report.is_restart_safe is True

    root._force_terminal()

    assert child.teardown_report is safe_report, "force-terminal must not touch an already-completed SAFE report"
    assert child.teardown_report.is_restart_safe is True


async def test_force_terminal_reaches_grandchild_under_already_reported_child():
    """Regression: a live grandchild under a child whose own report was already stored must
    still be force-terminated. Before this fix, `_force_terminal()`'s "leave an already-stored
    report unchanged" guard returned before the recursive call into children entirely, so a
    resource with a stored report (restart-safe or not) blocked force-termination of its own
    descendants -- exactly the total-timeout path `Hassette._shutdown_body()` relies on this
    method reaching unconditionally.

    Sets the child's report directly (rather than via `child.shutdown()`, which would also
    propagate to and shut down the grandchild itself, defeating the scenario) to simulate a
    resource that completed its own teardown attempt while a descendant it owns is still alive.
    """
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)
    child = root.add_child(SimpleParent)
    grandchild = child.add_child(SimpleParent)

    await root.initialize()

    child._teardown_report = TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))
    assert grandchild.shutdown_completed is False
    assert grandchild.status == ResourceStatus.RUNNING

    root._force_terminal()

    assert grandchild.shutdown_completed is True
    assert grandchild.status == ResourceStatus.STOPPED


async def test_force_terminal_does_not_clobber_already_terminal_status():
    """`_force_terminal()` must not silently overwrite a status the resource already reached on
    its own (e.g. EXHAUSTED_DEAD from a restart-refusal path) with STOPPED. Before this fix, the
    unconditional `self._status = ResourceStatus.STOPPED` bypassed the setter's transition
    validation and would erase that evidence with no trace -- EXHAUSTED_DEAD's only modeled
    outbound transition is to STOPPING, never back to STOPPED, so this reversion could only
    happen via this bypass.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = SimpleParent(hassette)
    resource._status = ResourceStatus.EXHAUSTED_DEAD

    resource._force_terminal()

    assert resource.status == ResourceStatus.EXHAUSTED_DEAD


async def test_force_terminal_still_sets_stopped_from_a_non_terminal_status():
    """Companion to the guard test above: a resource NOT already in a terminal status is still
    forced to STOPPED as before -- the guard only protects an existing terminal status, it does
    not disable force-terminal's normal behavior.
    """
    hassette = make_mock_hassette(sealed=False)
    resource = SimpleParent(hassette)
    assert resource.status == ResourceStatus.NOT_STARTED

    resource._force_terminal()

    assert resource.status == ResourceStatus.STOPPED


async def test_service_force_terminal_cancels_serve_task():
    """Service._force_terminal() cancels the _serve_task before calling super()."""
    svc = await make_running_simple_service()

    assert svc._serve_task is not None
    assert not svc._serve_task.done()

    svc._force_terminal()

    # _force_terminal is synchronous; the task is marked for cancellation but needs
    # an event loop tick to actually finish. Verify cancelling() is True.
    assert svc._serve_task.cancelling() > 0, "serve task should be marked for cancellation"
    assert svc.status == ResourceStatus.STOPPED
    assert svc.shutdown_completed is True

    # Let the event loop process the cancellation
    await asyncio.sleep(0)
    assert svc._serve_task.done(), "serve task should be done after yielding to event loop"


class HookTrackingParent(Resource):
    """Resource that records whether _on_children_stopped was called."""

    hook_called: bool = False

    async def _on_children_stopped(self) -> None:
        await super()._on_children_stopped()
        self.hook_called = True


async def test_on_children_stopped_called_on_clean_shutdown():
    """_on_children_stopped() fires when children shut down cleanly."""
    hassette = make_mock_hassette(sealed=False)
    parent = HookTrackingParent(hassette)
    child = parent.add_child(ShutdownCounter)

    await parent.initialize()
    await child.initialize()

    await parent.shutdown()

    assert parent.hook_called is True, "_on_children_stopped should have been called"
    assert child.shutdown_completed is True


async def test_on_children_stopped_skipped_on_timeout():
    """_on_children_stopped() is NOT called when child shutdown times out."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    parent = HookTrackingParent(hassette)
    parent.add_child(HangingChild)

    await parent.initialize()

    await parent.shutdown()

    assert parent.hook_called is False, "_on_children_stopped should NOT be called on timeout"


async def test_cleanup_timeout_fires_on_hung_cleanup():
    """When cleanup() hangs, asyncio.timeout catches it and logs a warning."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS

    class HungCleanupResource(Resource):
        async def cleanup(self, timeout: float | None = None) -> None:
            await asyncio.Event().wait()  # hang forever

    resource = HungCleanupResource(hassette)
    await resource.initialize()

    # Should complete without hanging — the timeout wrapping cleanup() should fire
    await resource.shutdown()

    assert resource.shutdown_completed is True


async def test_shutdown_clears_initializing_regardless_of_shutdown_event_state():
    """A completed ``shutdown()`` leaves ``initializing`` False regardless of whether
    ``shutdown_event`` was already set beforehand.

    Superseded by the coordinator design: there is no ``_finalize_shutdown()`` method and no
    mutable ``initializing`` flag to force directly anymore — ``initializing`` is now a
    read-only property derived from ``_init_task`` (see ``LifecycleMixin.initializing`` in
    ``hassette.resources.mixins``). This exercises the same observable outcome (the resource
    is not "initializing" once its coordinated shutdown attempt has completed) through the
    public front doors instead.
    """
    hassette = make_mock_hassette(sealed=False)

    resource1 = SimpleParent(hassette)
    await resource1.initialize()
    resource1.shutdown_event.set()
    await resource1.shutdown()
    assert resource1.initializing is False

    resource2 = SimpleParent(hassette)
    await resource2.initialize()
    assert not resource2.shutdown_event.is_set()
    await resource2.shutdown()
    assert resource2.initializing is False
