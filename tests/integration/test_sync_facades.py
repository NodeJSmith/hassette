"""Integration tests for the Bus/Scheduler/Api synchronous facades.

``AppSync`` runs its lifecycle hooks in a worker thread. Because the bus,
scheduler, and api write methods are ``async``, a sync hook cannot await them
directly. ``self.bus.sync``, ``self.scheduler.sync``, and ``self.api.sync``
bridge the gap by running each coroutine on the event loop via
``task_bucket.run_sync``.

These tests confirm registration works from ``on_initialize_sync`` (AC#7 /
FR#11: the handle passes ``asyncio.iscoroutine`` and ``run_sync`` drives it to
completion), and that calling a facade from inside the event loop fails fast.
"""

import pytest

from hassette.app.app import AppSync
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
from hassette.test_utils.app_harness import AppTestHarness


class SyncFacadeConfig(AppConfig):
    """Minimal AppConfig for sync-facade tests."""


class SyncRegisteringApp(AppSync[SyncFacadeConfig]):
    """Registers a bus listener, a scheduled job, and fires a service from its sync init hook."""

    def on_initialize_sync(self) -> None:
        self.bus.sync.on_state_change("sensor.temp", handler=self.on_temp, name="sync_temp")
        self.scheduler.sync.run_in(self.delayed_task, 60, name="sync_delayed")
        self.api.sync.turn_on("light.kitchen")

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


async def test_api_sync_facade_fires_service_from_sync_init() -> None:
    """A service fired via self.api.sync in on_initialize_sync is recorded by RecordingApi.

    AC#7 / FR#11: the RegistrationHandle passes ``asyncio.iscoroutine`` and
    ``task_bucket.run_sync`` drives it to completion, so the call reaches
    RecordingApi and is appended to api_recorder.calls.
    """
    async with AppTestHarness(SyncRegisteringApp, config={}) as harness:
        calls_by_method = {c.method: c for c in harness.api_recorder.calls}
        assert "turn_on" in calls_by_method, f"Expected 'turn_on' in api_recorder.calls, got {sorted(calls_by_method)}"
        turn_on_call = calls_by_method["turn_on"]
        assert turn_on_call.kwargs.get("entity_id") == "light.kitchen", (
            f"Expected entity_id='light.kitchen', got {turn_on_call.kwargs!r}"
        )
