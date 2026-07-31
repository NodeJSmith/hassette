"""Tests for the WAITING-status construction path in Scheduler.schedule().

Covers the interaction between EntityTime.first_run_time() returning WAITING and
Scheduler.schedule() building a Job with schedule_status=WAITING and next_run=None,
instead of a concrete timestamp. Enqueue-only-if-SCHEDULED gating on the live
SchedulerService (so a WAITING job never reaches the due-time heap end-to-end)
lands in a later task — this only covers the Job construction shape, using
make_scheduler()'s mocked scheduler_service.add_job() which never touches the heap.
"""

from unittest.mock import AsyncMock, patch

from hassette.scheduler.classes import ScheduleStatus
from hassette.scheduler.triggers import EntityTime
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.helpers import noop

from .conftest import PATCH_TARGET, make_scheduler


async def test_schedule_with_unresolvable_entity_time_builds_waiting_job() -> None:
    """An EntityTime trigger whose bound state reader has no usable time builds a WAITING job."""
    with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
        scheduler = make_scheduler()
        # schedule() rebinds EntityTime's state reader to hassette.bus_service.read_entity_state —
        # returning None here (entity absent from the cache) simulates the unresolvable case.
        scheduler.hassette.bus_service.read_entity_state = lambda _entity_id: None
        # _add_job_and_watch_entity awaits this to register the reconciliation listener.
        scheduler.hassette.bus.on_state_change = AsyncMock(return_value=object())

        job = await scheduler.schedule(
            noop,
            EntityTime("sensor.phone_next_alarm"),
            name="waiting_job",
        )

        assert job.schedule_status is ScheduleStatus.WAITING
        assert job.next_run is None
        assert job.fire_at is None
        assert job.trigger is not None


async def test_schedule_with_resolvable_entity_time_builds_scheduled_job() -> None:
    """An EntityTime trigger with a usable time builds a normal SCHEDULED job, not WAITING."""
    with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
        scheduler = make_scheduler()
        scheduler.hassette.bus_service.read_entity_state = lambda entity_id: {
            "entity_id": entity_id,
            "state": "2030-01-01T07:00:00-05:00",
            "attributes": {},
        }
        scheduler.hassette.bus.on_state_change = AsyncMock(return_value=object())

        job = await scheduler.schedule(
            noop,
            EntityTime("sensor.phone_next_alarm"),
            name="scheduled_entity_job",
        )

        assert job.schedule_status is ScheduleStatus.SCHEDULED
        assert job.next_run is not None
