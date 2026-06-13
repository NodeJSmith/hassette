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

from unittest.mock import MagicMock

import pytest

from hassette import context
from hassette.app.app import AppSync
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
from hassette.models.entities.cover import CoverEntity
from hassette.models.states import CoverState
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


async def test_entity_sync_facade_delegates_to_call_service() -> None:
    """entity.sync.<method>() delegates to the real (non-mocked) sync call_service with correct args.

    Points the entity's context api at the harness RecordingApi so the full delegation chain
    ``entity.sync.open_cover`` -> ``entity.api.sync.call_service`` is exercised against a real
    recording facade, not a MagicMock. The run_sync bridge itself is covered separately by
    ``test_task_bucket.test_run_sync_drives_coroutine_from_worker_thread``.
    """
    async with AppTestHarness(SyncRegisteringApp, config={}) as harness:
        recorder = harness.api_recorder
        # Point the entity's context api at the harness recorder, matching the make_*_entity
        # wiring in the unit tests. Scoped to try/finally so harness teardown sees the original
        # HASSETTE_INSTANCE restored — the entity calls must stay inside this block.
        hassette_stub = MagicMock()
        hassette_stub.api = recorder
        token = context.HASSETTE_INSTANCE.set(hassette_stub)
        try:
            state = CoverState.model_validate(
                {"entity_id": "cover.garage", "state": "open", "attributes": {}, "context": {}}
            )
            cover = CoverEntity(state=state)
            cover.sync.open_cover()
            cover.sync.set_cover_position(position=60)
        finally:
            context.HASSETTE_INSTANCE.reset(token)

        service_calls = {c.kwargs["service"]: c for c in recorder.calls if c.method == "call_service"}

        assert "open_cover" in service_calls, f"Expected open_cover call_service, got {sorted(service_calls)}"
        open_call = service_calls["open_cover"]
        assert open_call.kwargs["domain"] == "cover"
        assert open_call.kwargs["target"] == {"entity_id": "cover.garage"}

        assert "set_cover_position" in service_calls, f"Expected set_cover_position, got {sorted(service_calls)}"
        assert service_calls["set_cover_position"].kwargs.get("position") == 60
