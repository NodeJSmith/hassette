"""Tests for ScheduledJob.mark_registered — one-time db_id assignment.

Mirrors tests/integration/test_listeners.py::TestMarkRegistered. The scheduler
keeps the first db_id (first call wins); the second call now also logs a WARNING
so a double-registration anomaly is surfaced rather than silently swallowed.
"""

from hassette.scheduler.classes import ScheduledJob
from hassette.utils.date_utils import now

from .conftest import noop


def make_job() -> ScheduledJob:
    return ScheduledJob(owner_id="test_owner", next_run=now(), job=noop, name="job")


def test_mark_registered_sets_db_id() -> None:
    """mark_registered() sets db_id on first call."""
    job = make_job()
    assert job.db_id is None

    job.mark_registered(42)
    assert job.db_id == 42


def test_mark_registered_keeps_first_db_id_on_double_call() -> None:
    """mark_registered() keeps the original db_id when called a second time."""
    job = make_job()
    job.mark_registered(42)
    job.mark_registered(99)

    assert job.db_id == 42
