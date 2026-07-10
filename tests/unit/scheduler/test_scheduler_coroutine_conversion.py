"""Tests for Scheduler scheduling methods converted to def -> Coroutine[Any, Any, ScheduledJob].

Covers:
    - Awaiting returns ScheduledJob with db_id set
    - No HassetteForgottenAwaitWarning or native coroutine warning when awaited
    - Every public scheduling method is a plain def (not async def)
    - Forgotten await on a delegate emits HassetteForgottenAwaitWarning
    - Awaited method returns ScheduledJob with db_id; no warning
    - ScheduledJob.source_location populated after conversion (add_job backfill)
    - add_job("not-a-job") raises synchronously at call time, before handle is constructed
"""

import gc
import inspect
import warnings

import pytest

from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import Every
from hassette.test_utils.helpers import noop
from hassette.utils.await_guard import RegistrationHandle
from hassette.utils.date_utils import now
from tests.unit.test_forgotten_await_completeness import CANONICAL_PROTECTED

from .conftest import make_scheduler


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


# Public scheduling methods must be plain def, not async def

# Derived from the canonical single source of truth — see test_forgotten_await_completeness.py.
_PUBLIC_SCHEDULING_METHODS = sorted(CANONICAL_PROTECTED[Scheduler])


@pytest.mark.parametrize("method_name", _PUBLIC_SCHEDULING_METHODS)
def test_scheduling_method_is_plain_def(method_name: str) -> None:
    """Every public scheduler scheduling method must be a plain def, not async def."""
    method = getattr(Scheduler, method_name)
    assert not inspect.iscoroutinefunction(method), (
        f"Scheduler.{method_name} must be a plain def (not async def) after conversion, "
        f"but inspect.iscoroutinefunction returned True."
    )


# Annotation-origin guard lives in tests/unit/test_forgotten_await_completeness.py::TestAnnotationOriginGuard.


# Awaiting returns ScheduledJob with db_id; no warnings emitted


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda s: s.add_job(ScheduledJob(owner_id="o", next_run=now(), job=noop, name="t")),
            id="add_job",
        ),
        pytest.param(lambda s: s.schedule(noop, Every(hours=1), name="t"), id="schedule"),
        pytest.param(lambda s: s.run_in(noop, 30, name="t"), id="run_in"),
        pytest.param(lambda s: s.run_every(noop, minutes=5, name="t"), id="run_every"),
        pytest.param(lambda s: s.run_daily(noop, at="08:00", name="t"), id="run_daily"),
        pytest.param(lambda s: s.run_cron(noop, "0 9 * * 1-5", name="t"), id="run_cron"),
        pytest.param(lambda s: s.run_once(noop, at="23:59", name="t"), id="run_once"),
        pytest.param(lambda s: s.run_minutely(noop, minutes=5, name="t"), id="run_minutely"),
        pytest.param(lambda s: s.run_hourly(noop, hours=2, name="t"), id="run_hourly"),
    ],
)
async def test_await_returns_scheduled_job(call) -> None:
    """Awaiting any scheduling method returns a ScheduledJob with db_id set, no warning."""
    scheduler = make_scheduler()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        job = await call(scheduler)
    assert isinstance(job, ScheduledJob)
    assert job.db_id is not None
    assert isinstance(job.db_id, int)


def test_add_job_existing_name_no_valueerror_at_call_time() -> None:
    """add_job with a duplicate name does NOT raise ValueError synchronously at call time.

    The if_exists collision check lives in _add_job's async body — it only runs when
    the handle is awaited. This test pins that: calling add_job() twice with the same
    name must not raise at call time.
    """
    scheduler = make_scheduler()
    job_a = ScheduledJob(owner_id="test_owner", next_run=now(), job=noop, name="duplicate_name")
    job_b = ScheduledJob(owner_id="test_owner", next_run=now(), job=noop, name="duplicate_name")

    handle_a = scheduler.add_job(job_a)
    # Second call with same name — must NOT raise ValueError here (collision check is async).
    handle_b = scheduler.add_job(job_b)

    # Clean up both handles to avoid warning leaks.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", HassetteForgottenAwaitWarning)
        handle_a.close()
        handle_b.close()


# Returned handle is a RegistrationHandle / collections.abc.Coroutine


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda s: s.add_job(ScheduledJob(owner_id="o", next_run=now(), job=noop, name="t")),
            id="add_job",
        ),
        pytest.param(lambda s: s.schedule(noop, Every(hours=1), name="t"), id="schedule"),
        pytest.param(lambda s: s.run_in(noop, 30, name="t"), id="run_in"),
    ],
)
def test_returns_registration_handle(call) -> None:
    """Scheduling methods return a RegistrationHandle before awaiting."""
    scheduler = make_scheduler()
    handle = call(scheduler)
    assert isinstance(handle, RegistrationHandle)
    handle.close()


# Dropping un-awaited handle emits HassetteForgottenAwaitWarning


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda s: s.add_job(ScheduledJob(owner_id="o", next_run=now(), job=noop, name="t")),
            id="add_job",
        ),
        pytest.param(lambda s: s.schedule(noop, Every(hours=1), name="t"), id="schedule"),
        pytest.param(lambda s: s.run_in(noop, 30, name="t"), id="run_in"),
        pytest.param(lambda s: s.run_every(noop, minutes=5, name="t"), id="run_every"),
        pytest.param(lambda s: s.run_daily(noop, at="08:00", name="t"), id="run_daily"),
        pytest.param(lambda s: s.run_cron(noop, "0 9 * * 1-5", name="t"), id="run_cron"),
        pytest.param(lambda s: s.run_once(noop, at="23:59", name="t"), id="run_once"),
        pytest.param(lambda s: s.run_minutely(noop, minutes=5, name="t"), id="run_minutely"),
        pytest.param(lambda s: s.run_hourly(noop, hours=2, name="t"), id="run_hourly"),
    ],
)
def test_forgotten_await_warns(call) -> None:
    """Dropping un-awaited handle emits HassetteForgottenAwaitWarning."""
    scheduler = make_scheduler()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = call(scheduler)
        del _
        gc.collect()


# Source threading — ScheduledJob.source_location is non-empty via add_job backfill


async def test_source_location_backfilled_via_schedule() -> None:
    """Source location captured in add_job is backfilled onto ScheduledJob via schedule()."""
    scheduler = make_scheduler()
    job = await scheduler.schedule(noop, Every(hours=1), name="src_schedule")
    assert job.source_location, (
        "ScheduledJob.source_location must be non-empty after conversion — "
        "add_job must backfill it from the captured source_location."
    )
    assert ":" in job.source_location, f"source_location should be 'file:lineno', got {job.source_location!r}"


async def test_source_location_backfilled_via_run_in() -> None:
    """Source location captured in add_job is backfilled onto ScheduledJob via run_in() two-hop chain."""
    scheduler = make_scheduler()
    job = await scheduler.run_in(noop, 30, name="src_run_in")
    assert job.source_location, "source_location must be non-empty"
    assert ":" in job.source_location, f"source_location should be 'file:lineno', got {job.source_location!r}"


async def test_source_location_preserved_when_already_set() -> None:
    """add_job backfill does NOT overwrite source_location already set on the job."""
    scheduler = make_scheduler()
    pre_set = "custom_file.py:42"
    job = ScheduledJob(
        owner_id="test_owner",
        next_run=now(),
        job=noop,
        name="src_preserve",
        source_location=pre_set,
        registration_source="custom_source",
    )
    result = await scheduler.add_job(job)
    assert result.source_location == pre_set, (
        f"add_job must not overwrite a pre-set source_location, got {result.source_location!r}"
    )


# TypeError on add_job("not-a-job") — synchronous, at call time


def test_add_job_wrong_type_raises_typeerror_synchronously() -> None:
    """add_job('not-a-job') raises TypeError synchronously at call time (no warning leaks)."""
    scheduler = make_scheduler()
    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        with pytest.raises(TypeError, match="Expected ScheduledJob"):
            scheduler.add_job("not-a-job")  # pyright: ignore[reportArgumentType]


# Calling without awaiting does NOT mutate scheduler state (no job registered)


def test_unawaited_schedule_does_not_register_job() -> None:
    """Calling schedule() without awaiting does not add a job to the scheduler's state."""
    scheduler = make_scheduler()
    initial_count = len(scheduler._jobs_by_name)
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = scheduler.schedule(noop, Every(hours=1), name="no_register")
        del _
        gc.collect()
    assert len(scheduler._jobs_by_name) == initial_count, (
        "A forgotten await on schedule() must not mutate scheduler state — "
        "_add_job (with registry mutations) only runs when the handle is awaited."
    )


def test_unawaited_run_in_does_not_register_job() -> None:
    """Calling run_in() without awaiting does not add a job to the scheduler's state."""
    scheduler = make_scheduler()
    initial_count = len(scheduler._jobs_by_name)
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = scheduler.run_in(noop, 30, name="no_register_run_in")
        del _
        gc.collect()
    assert len(scheduler._jobs_by_name) == initial_count, (
        "A forgotten await on run_in() must not mutate scheduler state."
    )
