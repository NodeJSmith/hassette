"""Tests for src/hassette/web/utils.py — resolve_trigger protocol dispatch."""

from unittest.mock import MagicMock

from hassette.scheduler.triggers import After, Daily, Every, Once
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


# TestJobToDictFireAtJitter was removed in spec 2039 WP02 — _job_to_dict was
# deleted along with the /scheduler/jobs route. Live job serialisation now
# happens in the app_jobs route handler enrichment path.
