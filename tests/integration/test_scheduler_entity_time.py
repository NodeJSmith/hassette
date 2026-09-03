"""Integration tests for entity-driven scheduling with the EntityTime trigger.

Exercises the full path: Scheduler.schedule() binds the trigger to live state, registers a
state-change listener for the entity, and moves the job between WAITING and SCHEDULED when
the entity reports (or loses) a usable time.
"""

import typing
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from whenever import TimeDelta

import hassette.utils.date_utils as date_utils
from hassette.resources.lifecycle import mark_ready
from hassette.scheduler.classes import ScheduleStatus
from hassette.scheduler.triggers import EntityTime
from hassette.testing import HassetteHarness, create_state_change_event, make_state_dict
from hassette.types import Topic
from tests.support.helpers import noop

if typing.TYPE_CHECKING:
    from hassette import Hassette

ALARM_ENTITY = "sensor.phone_next_alarm"


@pytest.fixture
async def entity_time_harness(test_config) -> AsyncIterator[HassetteHarness]:
    """Harness with bus + scheduler + state proxy, so entity-driven jobs can be scheduled."""
    harness = HassetteHarness(test_config, skip_global_set=False)
    harness.with_bus().with_scheduler().with_state_proxy().with_state_registry()

    api_mock = AsyncMock()
    api_mock.sync = AsyncMock()
    api_mock.get_states_raw = AsyncMock(return_value=[])
    harness.hassette._api = api_mock

    await harness.start()
    mark_ready(harness.state_proxy, reason="entity_time_harness: mark ready for test")

    try:
        yield harness
    finally:
        await harness.stop()


async def seed_alarm(harness: HassetteHarness, value: str) -> None:
    """Put an alarm time into the StateProxy cache."""
    await harness.seed_state(ALARM_ENTITY, make_state_dict(ALARM_ENTITY, value))


async def change_alarm(harness: HassetteHarness, old_value: str, new_value: str) -> None:
    """Send a state change for the alarm entity and wait for dispatch to settle."""
    event = create_state_change_event(entity_id=ALARM_ENTITY, old_value=old_value, new_value=new_value)
    await harness.hassette.send_event(event)
    await harness.bus_service.await_dispatch_idle()


def iso_in(minutes: int) -> str:
    """Return an ISO timestamp the given number of minutes from now."""
    return date_utils.now().add(minutes=minutes).round("second").format_iso()


def watch_listener_names(hassette: "Hassette") -> list[str]:
    """Return the names of the scheduler's entity-watch listeners for the alarm entity."""
    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{ALARM_ENTITY}"
    return [listener.identity.name for listener in hassette.bus_service.router.get_topic_listeners(topic)]


async def test_schedule_uses_the_entity_time(entity_time_harness: HassetteHarness) -> None:
    """A future alarm time becomes the job's next run."""
    alarm = iso_in(30)
    await seed_alarm(entity_time_harness, alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_uses_entity_time"
    )

    assert job.schedule_status == ScheduleStatus.SCHEDULED
    assert job.next_run == date_utils.convert_datetime_str_to_tz(alarm)
    job.remove()


async def test_schedule_applies_offset(entity_time_harness: HassetteHarness) -> None:
    """A negative offset moves the job earlier than the entity's time."""
    alarm = iso_in(60)
    await seed_alarm(entity_time_harness, alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop,
        EntityTime(ALARM_ENTITY, offset=TimeDelta(minutes=-30)),
        name="entity_time_applies_offset",
    )

    expected = date_utils.convert_datetime_str_to_tz(alarm).add(minutes=-30)
    assert job.next_run == expected
    job.remove()


async def test_unavailable_entity_registers_the_job_waiting(entity_time_harness: HassetteHarness) -> None:
    """An unavailable entity registers the job as waiting rather than failing or removing it."""
    await seed_alarm(entity_time_harness, "unavailable")

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_unavailable_waiting"
    )

    assert job.schedule_status == ScheduleStatus.WAITING
    assert job.next_run is None
    assert job.fire_at is None
    assert job.db_id is not None, "a waiting job is still a registered job"
    job.remove()


async def test_unavailable_entity_with_jitter_stays_waiting(entity_time_harness: HassetteHarness) -> None:
    """Jitter is stored on the job but never applied while it stays off-heap and waiting."""
    await seed_alarm(entity_time_harness, "unavailable")

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_unavailable_jitter", jitter=5.0
    )

    assert job.schedule_status == ScheduleStatus.WAITING
    assert job.next_run is None
    assert job.fire_at is None
    assert job.jitter == 5.0
    job.remove()


async def test_entity_change_moves_the_job(entity_time_harness: HassetteHarness) -> None:
    """Changing the alarm entity mid-schedule reschedules the pending job."""
    first_alarm = iso_in(60)
    await seed_alarm(entity_time_harness, first_alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_change_moves_job"
    )
    assert job.next_run == date_utils.convert_datetime_str_to_tz(first_alarm)

    second_alarm = iso_in(15)
    await change_alarm(entity_time_harness, first_alarm, second_alarm)

    assert job.schedule_status == ScheduleStatus.SCHEDULED
    assert job.next_run == date_utils.convert_datetime_str_to_tz(second_alarm)
    job.remove()


async def test_entity_going_unavailable_parks_a_scheduled_job(entity_time_harness: HassetteHarness) -> None:
    """Clearing the alarm moves a scheduled job to waiting instead of leaving it queued at a
    stale time.
    """
    alarm = iso_in(60)
    await seed_alarm(entity_time_harness, alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_unavailable_parks_running"
    )
    assert job.schedule_status == ScheduleStatus.SCHEDULED

    await change_alarm(entity_time_harness, alarm, "unavailable")

    assert job.schedule_status == ScheduleStatus.WAITING
    assert job.next_run is None
    assert job.fire_at is None
    job.remove()


async def test_waiting_job_removed_from_heap_but_stays_registered(entity_time_harness: HassetteHarness) -> None:
    """A job moved to waiting is no longer on the scheduler heap, but remains live.

    ``get_all_jobs()`` sources from the live registry (``_jobs_by_id``), not the heap, so a
    waiting job is still found there — the heap-specific check goes through ``_job_queue``
    directly.
    """
    alarm = iso_in(60)
    await seed_alarm(entity_time_harness, alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_waiting_off_heap"
    )
    heap_before = await entity_time_harness.scheduler_service._job_queue.get_all()
    assert any(j is job for j in heap_before)

    await change_alarm(entity_time_harness, alarm, "unavailable")

    heap_after = await entity_time_harness.scheduler_service._job_queue.get_all()
    assert not any(j is job for j in heap_after), "waiting job must not be on the heap"
    live_after = await entity_time_harness.scheduler_service.get_all_jobs()
    assert any(j is job for j in live_after), "waiting job must stay in the live registry"
    assert job.name in entity_time_harness.scheduler._jobs_by_name, "waiting job must stay registered"
    job.remove()


async def test_parked_job_recovers_when_entity_reports_a_time(entity_time_harness: HassetteHarness) -> None:
    """A job parked at registration starts firing once the entity gets a time."""
    await seed_alarm(entity_time_harness, "unavailable")

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_parked_recovers"
    )
    assert job.schedule_status == ScheduleStatus.WAITING

    alarm = iso_in(45)
    await change_alarm(entity_time_harness, "unavailable", alarm)

    assert job.schedule_status == ScheduleStatus.SCHEDULED
    assert job.next_run == date_utils.convert_datetime_str_to_tz(alarm)
    job.remove()


async def test_waiting_job_reactivates_onto_the_heap(entity_time_harness: HassetteHarness) -> None:
    """Recovery from waiting puts the job back on the live heap, not just changes its status.

    ``get_all_jobs()`` sources from the live registry, so a waiting job is already present
    there before recovery — the heap-membership check goes through ``_job_queue`` directly.
    """
    await seed_alarm(entity_time_harness, "unavailable")

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_waiting_reactivates"
    )
    heap_while_waiting = await entity_time_harness.scheduler_service._job_queue.get_all()
    assert not any(j is job for j in heap_while_waiting)

    alarm = iso_in(45)
    await change_alarm(entity_time_harness, "unavailable", alarm)

    heap_after = await entity_time_harness.scheduler_service._job_queue.get_all()
    assert any(j is job for j in heap_after), "job must be back on the heap after recovering a usable time"
    job.remove()


async def test_still_unavailable_change_does_not_disturb_a_waiting_job(entity_time_harness: HassetteHarness) -> None:
    """A state change that still names no usable time is a no-op for an already-waiting job."""
    await seed_alarm(entity_time_harness, "unavailable")

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_still_unavailable_noop"
    )
    assert job.schedule_status == ScheduleStatus.WAITING

    # "unknown" also carries no usable time — the job should simply stay waiting.
    await change_alarm(entity_time_harness, "unavailable", "unknown")

    assert job.schedule_status == ScheduleStatus.WAITING
    assert job.next_run is None
    job.remove()


async def test_daily_mode_ignores_the_entity_date(entity_time_harness: HassetteHarness) -> None:
    """daily=True keeps only the time of day, so a stale date still schedules today or tomorrow."""
    target = date_utils.now().add(minutes=90).round("second")
    stale = target.add(hours=-24 * 400)
    await seed_alarm(entity_time_harness, stale.format_iso())

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY, daily=True), name="entity_time_daily_ignores_date"
    )

    # Cron granularity is whole minutes, so compare the wall-clock minute.
    assert (job.next_run.hour, job.next_run.minute) == (target.hour, target.minute)
    assert job.next_run > date_utils.now()
    job.remove()


async def test_change_during_registration_is_picked_up(entity_time_harness: HassetteHarness) -> None:
    """A change landing while the job is being registered is reconciled, not lost.

    Registration awaits a database write before the state-change listener exists, so a change
    arriving in that window reaches neither the initial read nor the listener. Simulated here
    by moving the entity from inside the awaited add_job call.
    """
    first_alarm = iso_in(60)
    second_alarm = iso_in(15)
    await seed_alarm(entity_time_harness, first_alarm)

    scheduler_service = entity_time_harness.scheduler_service
    original_add_job = scheduler_service.add_job

    async def add_job_then_move_the_entity(job):
        await original_add_job(job)
        await seed_alarm(entity_time_harness, second_alarm)

    scheduler_service.add_job = add_job_then_move_the_entity  # pyright: ignore[reportAttributeAccessIssue]
    try:
        job = await entity_time_harness.scheduler.schedule(
            noop, EntityTime(ALARM_ENTITY), name="entity_time_registration_window"
        )
    finally:
        scheduler_service.add_job = original_add_job  # pyright: ignore[reportAttributeAccessIssue]

    assert job.next_run == date_utils.convert_datetime_str_to_tz(second_alarm)
    job.remove()


async def test_registration_race_reconciles_to_waiting(entity_time_harness: HassetteHarness) -> None:
    """A change to "no usable time" landing during registration is reconciled to waiting.

    Mirrors test_change_during_registration_is_picked_up but for the opposite direction: the
    entity goes from available to unavailable inside the registration window, so the job must
    end up waiting rather than scheduled at a stale time.
    """
    first_alarm = iso_in(60)
    await seed_alarm(entity_time_harness, first_alarm)

    scheduler_service = entity_time_harness.scheduler_service
    original_add_job = scheduler_service.add_job

    async def add_job_then_clear_the_entity(job):
        await original_add_job(job)
        await seed_alarm(entity_time_harness, "unavailable")

    scheduler_service.add_job = add_job_then_clear_the_entity  # pyright: ignore[reportAttributeAccessIssue]
    try:
        job = await entity_time_harness.scheduler.schedule(
            noop, EntityTime(ALARM_ENTITY), name="entity_time_registration_race_waiting"
        )
    finally:
        scheduler_service.add_job = original_add_job  # pyright: ignore[reportAttributeAccessIssue]

    assert job.schedule_status == ScheduleStatus.WAITING
    assert job.next_run is None
    job.remove()


async def test_change_while_job_is_mid_dispatch_is_not_lost(entity_time_harness: HassetteHarness) -> None:
    """A reschedule that lands after heap-pop is applied by dispatch_and_log."""
    first_alarm = iso_in(60)
    second_alarm = iso_in(15)
    await seed_alarm(entity_time_harness, first_alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_mid_dispatch_reschedule"
    )
    expected = date_utils.convert_datetime_str_to_tz(second_alarm)

    removed = await entity_time_harness.scheduler_service._job_queue.remove_job(job)
    assert removed is True

    await change_alarm(entity_time_harness, first_alarm, second_alarm)
    assert job._pending_entity_time_transition == expected

    await entity_time_harness.scheduler_service.dispatch_and_log(job)

    assert job.next_run == expected
    assert job._pending_entity_time_transition is None
    job.remove()


async def test_change_during_dispatch_reenqueue_is_not_lost(entity_time_harness: HassetteHarness) -> None:
    """A reschedule after next-run computation still moves the re-enqueued job."""
    first_alarm = iso_in(60)
    second_alarm = iso_in(15)
    await seed_alarm(entity_time_harness, first_alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_reenqueue_window"
    )
    expected = date_utils.convert_datetime_str_to_tz(second_alarm)

    removed = await entity_time_harness.scheduler_service._job_queue.remove_job(job)
    assert removed is True

    original_enqueue = entity_time_harness.scheduler_service.enqueue_job
    injected = False

    async def enqueue_after_change(enqueued_job):
        nonlocal injected
        if not injected:
            injected = True
            await entity_time_harness.scheduler_service.reschedule_job(enqueued_job, expected)
        await original_enqueue(enqueued_job)

    entity_time_harness.scheduler_service.enqueue_job = enqueue_after_change  # pyright: ignore[reportAttributeAccessIssue]
    try:
        await entity_time_harness.scheduler_service.dispatch_and_log(job)
    finally:
        entity_time_harness.scheduler_service.enqueue_job = original_enqueue  # pyright: ignore[reportAttributeAccessIssue]

    assert job.next_run == expected
    assert job._pending_entity_time_transition is None
    job.remove()


async def test_watcher_registration_failure_cleans_up_job(
    entity_time_harness: HassetteHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """schedule() must not leave a live job when the entity watcher cannot register."""
    await seed_alarm(entity_time_harness, iso_in(60))

    async def fail_on_state_change(*_args, **_kwargs):
        raise RuntimeError("listener registration failed")

    monkeypatch.setattr(entity_time_harness.hassette.bus, "on_state_change", fail_on_state_change)

    with pytest.raises(RuntimeError, match="listener registration failed"):
        await entity_time_harness.scheduler.schedule(
            noop, EntityTime(ALARM_ENTITY), name="entity_time_watcher_failure_cleanup"
        )

    assert entity_time_harness.scheduler.list_jobs() == []


async def test_watch_listener_is_registered_and_cancelled_with_the_job(
    entity_time_harness: HassetteHarness,
) -> None:
    """The entity-watch listener exists for the job's lifetime and no longer."""
    await seed_alarm(entity_time_harness, iso_in(30))
    hassette = typing.cast("Hassette", entity_time_harness.hassette)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_watch_listener"
    )

    expected_name = f"scheduler.entity_time.{entity_time_harness.scheduler.owner_id}.{job.name}"
    assert expected_name in watch_listener_names(hassette)

    job.remove()

    assert expected_name not in watch_listener_names(hassette)


async def test_watcher_survives_transition_to_waiting(entity_time_harness: HassetteHarness) -> None:
    """The entity-watch listener stays registered when the job moves to waiting.

    A waiting job must still hear about later entity changes so it can recover — losing the
    watcher here would strand it waiting forever.
    """
    alarm = iso_in(30)
    await seed_alarm(entity_time_harness, alarm)
    hassette = typing.cast("Hassette", entity_time_harness.hassette)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_watcher_survives_waiting"
    )
    expected_name = f"scheduler.entity_time.{entity_time_harness.scheduler.owner_id}.{job.name}"
    assert expected_name in watch_listener_names(hassette)

    await change_alarm(entity_time_harness, alarm, "unavailable")

    assert job.schedule_status == ScheduleStatus.WAITING
    assert expected_name in watch_listener_names(hassette), "watcher must survive the waiting transition"
    job.remove()


async def test_cancelled_job_is_not_rescheduled(entity_time_harness: HassetteHarness) -> None:
    """A change arriving after removal does not resurrect the job."""
    alarm = iso_in(60)
    await seed_alarm(entity_time_harness, alarm)

    job = await entity_time_harness.scheduler.schedule(
        noop, EntityTime(ALARM_ENTITY), name="entity_time_cancelled_not_rescheduled"
    )
    original_next_run = job.next_run
    job.remove()

    await change_alarm(entity_time_harness, alarm, iso_in(5))

    assert job.next_run == original_next_run
