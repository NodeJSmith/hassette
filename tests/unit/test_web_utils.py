"""Tests for src/hassette/web/utils.py — resolve_trigger protocol dispatch."""

from unittest.mock import MagicMock

from whenever import ZonedDateTime

from hassette.scheduler.triggers import After, Daily, Every, Once
from hassette.web.routes.scheduler import _job_to_dict
from hassette.web.utils import resolve_trigger


def _make_job(trigger: object | None = None) -> MagicMock:
    """Build a stub ScheduledJob with the given trigger."""
    job = MagicMock()
    job.trigger = trigger
    return job


class TestResolveTrigger:
    def test_resolve_trigger_every(self) -> None:
        job = _make_job(Every(hours=1))
        assert resolve_trigger(job) == ("interval", "3600s")

    def test_resolve_trigger_daily(self) -> None:
        # Daily.trigger_detail() returns the user-written "HH:MM" (not the internal cron expression),
        # so the UI can render "Daily at 07:00" directly.
        job = _make_job(Daily(at="07:00"))
        assert resolve_trigger(job) == ("cron", "07:00")

    def test_resolve_trigger_once(self) -> None:
        job = _make_job(Once(at="07:00"))
        assert resolve_trigger(job) == ("once", "07:00")

    def test_resolve_trigger_after(self) -> None:
        job = _make_job(After(seconds=30))
        assert resolve_trigger(job) == ("after", "30s")

    def test_resolve_trigger_no_trigger(self) -> None:
        job = _make_job(trigger=None)
        assert resolve_trigger(job) == ("one-shot", None)

    def test_resolve_trigger_custom(self) -> None:
        """Custom trigger implementing protocol methods — returns db_type, not label."""
        from typing import Literal

        from whenever import ZonedDateTime

        class _CustomTrigger:
            def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
                return current_time

            def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
                return current_time

            def trigger_label(self) -> str:
                return "custom"

            def trigger_detail(self) -> str | None:
                return "every 60s"

            def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]:
                return "custom"

            def trigger_id(self) -> str:
                return "custom:60"

        job = _make_job(_CustomTrigger())
        assert resolve_trigger(job) == ("custom", "every 60s")


class TestJobToDictFireAtJitter:
    """F7: _job_to_dict must include fire_at and jitter for jittered jobs."""

    def _base_job(self) -> MagicMock:
        job = MagicMock()
        job.trigger = Every(hours=1)
        job.db_id = 1
        job.name = "test_job"
        job.owner_id = "owner"
        job.cancelled = False
        return job

    def test_jittered_job_has_fire_at_and_jitter(self) -> None:
        """When fire_at != next_run, fire_at and jitter are serialised."""
        job = self._base_job()
        base_time = ZonedDateTime(2025, 6, 1, 12, 0, tz="UTC")
        jittered_time = ZonedDateTime(2025, 6, 1, 12, 0, 45, tz="UTC")
        job.next_run = base_time
        job.fire_at = jittered_time
        job.jitter = 120.0

        result = _job_to_dict(job)

        assert result["fire_at"] == jittered_time.format_iso()
        assert result["jitter"] == 120.0

    def test_non_jittered_job_fire_at_is_none(self) -> None:
        """When fire_at == next_run, fire_at is None and jitter may be None."""
        job = self._base_job()
        base_time = ZonedDateTime(2025, 6, 1, 12, 0, tz="UTC")
        job.next_run = base_time
        job.fire_at = base_time
        job.jitter = None

        result = _job_to_dict(job)

        assert result["fire_at"] is None
        assert result["jitter"] is None
