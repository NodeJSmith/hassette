"""Jitter is rolled when a Job's next run is set, so ``fire_at`` is final before any enqueue."""

import pytest
from hassette_wire import ScheduleStatus
from whenever import ZonedDateTime

from hassette.scheduler.classes import apply_jitter
from tests.support.factories import make_scheduled_job
from tests.support.helpers import noop

NEXT_RUN = ZonedDateTime(2030, 1, 1, 12, 0, tz="UTC")
JITTER_SECONDS = 30.0


def assert_fire_at_within_jitter(fire_at: ZonedDateTime | None, next_run: ZonedDateTime | None) -> None:
    assert fire_at is not None
    assert next_run is not None
    offset = (fire_at - next_run).total("seconds")
    assert 0 <= offset <= JITTER_SECONDS


def test_set_next_run_rolls_jitter_into_fire_at() -> None:
    """With jitter, set_next_run leaves next_run unjittered and puts fire_at within the jitter bound."""
    job = make_scheduled_job(job=noop, jitter=JITTER_SECONDS)

    job.set_next_run(NEXT_RUN)

    assert job.next_run == NEXT_RUN
    assert_fire_at_within_jitter(job.fire_at, job.next_run)
    assert job.fire_at is not None
    assert job.sort_index == (job.fire_at.timestamp(unit="nanosecond"), id(job))


def test_transition_to_scheduled_rolls_jitter_into_fire_at() -> None:
    """transition_to(SCHEDULED) jitters fire_at the same way, with no enqueue involved."""
    job = make_scheduled_job(job=noop, jitter=JITTER_SECONDS, schedule_status=ScheduleStatus.WAITING)

    job.transition_to(ScheduleStatus.SCHEDULED, next_run=NEXT_RUN)

    assert job.next_run == NEXT_RUN
    assert_fire_at_within_jitter(job.fire_at, job.next_run)
    assert job.fire_at is not None
    assert job.sort_index == (job.fire_at.timestamp(unit="nanosecond"), id(job))


def test_jitter_offset_is_actually_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rolled offset lands on fire_at, not just somewhere inside the bound."""
    monkeypatch.setattr("hassette.scheduler.classes.random.uniform", lambda _low, _high: 12.5)
    job = make_scheduled_job(job=noop, jitter=JITTER_SECONDS)

    job.set_next_run(NEXT_RUN)

    assert job.fire_at == NEXT_RUN.add(seconds=12.5)


def test_transition_to_explicit_fire_at_overrides_jitter() -> None:
    """An explicit fire_at= passed to transition_to wins over the rolled jitter."""
    job = make_scheduled_job(job=noop, jitter=JITTER_SECONDS)
    explicit = NEXT_RUN.add(seconds=5)

    job.transition_to(ScheduleStatus.SCHEDULED, next_run=NEXT_RUN, fire_at=explicit)

    assert job.fire_at == explicit


@pytest.mark.parametrize("jitter", [None, 0.0])
def test_without_jitter_fire_at_equals_next_run(jitter: float | None) -> None:
    job = make_scheduled_job(job=noop, jitter=jitter)

    job.set_next_run(NEXT_RUN)

    assert job.fire_at == job.next_run == NEXT_RUN
    assert job.sort_index == (NEXT_RUN.timestamp(unit="nanosecond"), id(job))


def test_apply_jitter_falls_back_when_offset_overflows() -> None:
    """An offset that pushes past the representable range keeps the unjittered time."""
    near_max = ZonedDateTime(9999, 12, 31, 23, 59, 59, tz="UTC")

    assert apply_jitter(near_max, 3600.0) == near_max
