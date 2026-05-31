"""Integration tests for the Bus/Scheduler synchronous facades (issue #929).

``AppSync`` runs its lifecycle hooks in a worker thread. Because the bus and
scheduler registration methods are ``async``, a sync hook cannot await them
directly. ``self.bus.sync`` and ``self.scheduler.sync`` bridge the gap by
running each coroutine on the event loop via ``task_bucket.run_sync``.

These tests confirm registration works from ``on_initialize_sync`` and that
calling a facade from inside the event loop fails fast.
"""

import pytest

from hassette.app.app import AppSync
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
from hassette.test_utils.app_harness import AppTestHarness


class SyncFacadeConfig(AppConfig):
    """Minimal AppConfig for sync-facade tests."""


class SyncRegisteringApp(AppSync[SyncFacadeConfig]):
    """Registers a bus listener and a scheduled job from its sync init hook."""

    def on_initialize_sync(self) -> None:
        self.bus.sync.on_state_change("sensor.temp", handler=self.on_temp, name="sync_temp")
        self.scheduler.sync.run_in(self.delayed_task, 60, name="sync_delayed")

    def on_temp(self, event: RawStateChangeEvent) -> None:
        pass

    def delayed_task(self) -> None:
        pass


async def test_bus_sync_facade_registers_listener_from_sync_init():
    """A listener registered via self.bus.sync in on_initialize_sync is live with a real db_id."""
    async with AppTestHarness(SyncRegisteringApp, config={}) as harness:
        listeners = harness.bus.get_listeners()
        by_name = {listener.identity.name: listener for listener in listeners}

        assert "sync_temp" in by_name, f"Expected 'sync_temp' listener, got {sorted(by_name)}"
        db_id = by_name["sync_temp"].db_id
        assert isinstance(db_id, int), f"Listener db_id should be an int after sync registration, got {db_id!r}"
        assert db_id > 0, f"Listener db_id should be a real row id, got {db_id}"


async def test_scheduler_sync_facade_schedules_job_from_sync_init():
    """A job scheduled via self.scheduler.sync in on_initialize_sync is live with a real db_id."""
    async with AppTestHarness(SyncRegisteringApp, config={}) as harness:
        jobs = harness.scheduler.list_jobs()
        by_name = {job.name: job for job in jobs}

        assert "sync_delayed" in by_name, f"Expected 'sync_delayed' job, got {sorted(by_name)}"
        db_id = by_name["sync_delayed"].db_id
        assert isinstance(db_id, int), f"Job db_id should be an int after sync registration, got {db_id!r}"
        assert db_id > 0, f"Job db_id should be a real row id, got {db_id}"


async def test_bus_sync_facade_raises_inside_event_loop():
    """Calling the bus facade from the loop thread fails fast instead of deadlocking."""

    def noop(event: RawStateChangeEvent) -> None:
        pass

    async with AppTestHarness(SyncRegisteringApp, config={}) as harness:
        with pytest.raises(RuntimeError, match="called from within an event loop"):
            harness.bus.sync.on_state_change("sensor.other", handler=noop, name="loop_call")


async def test_scheduler_sync_facade_raises_inside_event_loop():
    """Calling the scheduler facade from the loop thread fails fast instead of deadlocking."""

    def noop() -> None:
        pass

    async with AppTestHarness(SyncRegisteringApp, config={}) as harness:
        with pytest.raises(RuntimeError, match="called from within an event loop"):
            harness.scheduler.sync.run_in(noop, 30, name="loop_job")
