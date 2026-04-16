"""Tests for src/hassette/web/utils.py — resolve_trigger protocol dispatch."""

from unittest.mock import MagicMock

from whenever import TimeDelta

from hassette.scheduler.classes import CronTrigger, IntervalTrigger
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
        job = _make_job(Daily(at="07:00"))
        assert resolve_trigger(job) == ("cron", "0 7 * * *")

    def test_resolve_trigger_once(self) -> None:
        job = _make_job(Once(at="07:00"))
        assert resolve_trigger(job) == ("once", "07:00")

    def test_resolve_trigger_after(self) -> None:
        job = _make_job(After(seconds=30))
        assert resolve_trigger(job) == ("after", "30s")

    def test_resolve_trigger_no_trigger(self) -> None:
        job = _make_job(trigger=None)
        assert resolve_trigger(job) == (None, None)

    def test_resolve_trigger_custom(self) -> None:
        """Custom trigger implementing protocol methods — returns db_type, not label."""
        trigger = MagicMock()
        trigger.trigger_detail.return_value = "every 60s"
        trigger.trigger_db_type.return_value = "custom"
        job = _make_job(trigger)
        assert resolve_trigger(job) == ("custom", "every 60s")

    def test_resolve_trigger_legacy_interval(self) -> None:
        """Legacy IntervalTrigger without protocol methods — parses type:detail from str()."""
        trigger = IntervalTrigger(TimeDelta(seconds=30))
        job = _make_job(trigger)
        assert resolve_trigger(job) == ("interval", "30s")

    def test_resolve_trigger_legacy_cron(self) -> None:
        """Legacy CronTrigger without protocol methods — parses type:detail from str()."""
        trigger = CronTrigger("*/5 * * * *")
        job = _make_job(trigger)
        assert resolve_trigger(job) == ("cron", "*/5 * * * *")
