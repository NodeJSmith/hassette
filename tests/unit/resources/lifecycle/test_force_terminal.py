"""Tests for _force_terminal() and related shutdown edge cases.

Verifies:
- Scheduler.on_shutdown() dequeues all jobs
- App shutdown propagates to Bus and Scheduler
- _force_terminal() recurses to grandchildren
- _force_terminal() cancels task buckets
- _force_terminal() skips completed children
- Service._force_terminal() cancels serve task
- _on_children_stopped() hook fires on clean shutdown
- _on_children_stopped() is skipped on timeout
- cleanup() timeout is enforced
- _finalize_shutdown() resets initializing flag
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.resources.base import Resource
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.test_utils import make_mock_hassette
from hassette.test_utils.factories import make_scheduled_job
from hassette.types.enums import ResourceStatus
from tests.unit.resources.conftest import wait_for_running

from .conftest import HangingChild, ShutdownCounter, SimpleParent, SimpleService


async def test_scheduler_on_shutdown_dequeues_all_jobs():
    """Scheduler.on_shutdown() awaits _remove_all_jobs (via remove_jobs_by_owner)."""
    hassette = make_mock_hassette(sealed=False)

    # add_job is now awaited inline — must be an AsyncMock
    async def _add_job(job: ScheduledJob) -> None:
        job.mark_registered(1)

    hassette.scheduler_service.add_job = AsyncMock(side_effect=_add_job)
    scheduler = Scheduler(hassette, parent=hassette)

    await scheduler.initialize()

    # Add a job so we know there's something to remove
    await scheduler.add_job(
        make_scheduled_job(owner_id=scheduler.owner_id, name="test_job"),
    )

    await scheduler.shutdown()

    # remove_jobs_by_owner is called by remove_all_jobs, and it's on the mock service
    hassette.scheduler_service.remove_jobs_by_owner.assert_awaited_once_with(scheduler.owner_id)


async def test_app_shutdown_propagates_to_bus_and_scheduler():
    """App shutdown propagates to Bus.on_shutdown and Scheduler.on_shutdown via children."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.app_shutdown_timeout_seconds = 5
    hassette.config.logging.apps = "DEBUG"

    app = App(hassette, app_config=AppConfig(instance_name="test_app"), index=0, app_key="test_app")

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


async def test_force_terminal_skips_completed_children():
    """_force_terminal() returns early for resources with shutdown_completed=True."""
    hassette = make_mock_hassette(sealed=False)
    root = SimpleParent(hassette)
    child = root.add_child(SimpleParent)

    await root.initialize()

    # Pre-complete the child's shutdown
    await child.shutdown()
    assert child.shutdown_completed is True
    assert child.status == ResourceStatus.STOPPED

    # Track whether cancel() is called on the already-completed child
    child.cancel = MagicMock()

    root._force_terminal()

    # Root should be force-terminated
    assert root.shutdown_completed is True
    assert root.status == ResourceStatus.STOPPED
    # Child was already completed — cancel() should NOT have been called
    child.cancel.assert_not_called()


async def test_service_force_terminal_cancels_serve_task():
    """Service._force_terminal() cancels the _serve_task before calling super()."""
    hassette = make_mock_hassette(sealed=False)
    svc = SimpleService(hassette)

    await svc.initialize()
    await wait_for_running(svc)

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
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 0.1

    parent = HookTrackingParent(hassette)
    parent.add_child(HangingChild)

    await parent.initialize()

    await parent.shutdown()

    assert parent.hook_called is False, "_on_children_stopped should NOT be called on timeout"


async def test_cleanup_timeout_fires_on_hung_cleanup():
    """When cleanup() hangs, asyncio.timeout catches it and logs a warning."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 0.1

    class HungCleanupResource(Resource):
        async def cleanup(self, timeout: float | None = None) -> None:
            await asyncio.Event().wait()  # hang forever

    resource = HungCleanupResource(hassette)
    await resource.initialize()

    # Should complete without hanging — the timeout wrapping cleanup() should fire
    await resource.shutdown()

    assert resource.shutdown_completed is True


async def test_finalize_shutdown_resets_initializing_flag():
    """_finalize_shutdown() clears initializing regardless of how shutdown was triggered."""
    hassette = make_mock_hassette(sealed=False)

    resource1 = SimpleParent(hassette)
    resource1.initializing = True
    resource1.shutdown_event.set()
    await resource1._finalize_shutdown()
    assert resource1.initializing is False

    resource2 = SimpleParent(hassette)
    resource2.initializing = True
    resource2.shutdown_event.clear()
    await resource2._finalize_shutdown()
    assert resource2.initializing is False
