"""Tests for CronTrigger — the internal cron-expression engine backing Daily and Cron.

Covers __eq__, __hash__, __str__, first_run_time/next_run_time delegation, and the
MAX_CRON_ITERATIONS skip-ahead fallback in _next_after. DST disambiguation paths are
already covered by tests/unit/test_triggers.py via Daily(); this file focuses on
CronTrigger's own dunder/identity behavior and the iteration-bound fallback.
"""

from unittest.mock import patch

import pytest

from hassette.scheduler.classes import CronTrigger

from .conftest import TZ, zdt


class TestCronTriggerEquality:
    def test_eq_true_for_same_expression(self) -> None:
        """Two CronTrigger instances with the same expression compare equal."""
        assert CronTrigger("0 9 * * *") == CronTrigger("0 9 * * *")

    def test_eq_false_for_different_expression(self) -> None:
        """CronTrigger instances with different expressions are not equal."""
        assert CronTrigger("0 9 * * *") != CronTrigger("0 10 * * *")

    def test_eq_not_implemented_for_other_type(self) -> None:
        """Comparing against a non-CronTrigger returns NotImplemented, so == is False."""
        trigger = CronTrigger("0 9 * * *")
        assert trigger.__eq__("0 9 * * *") is NotImplemented
        assert (trigger == "0 9 * * *") is False

    def test_hash_matches_for_equal_expressions(self) -> None:
        """Equal CronTrigger instances hash identically (dict/set usability)."""
        a = CronTrigger("*/5 * * * *")
        b = CronTrigger("*/5 * * * *")
        assert hash(a) == hash(b)

    def test_str_includes_expression(self) -> None:
        """__str__ returns 'cron:<expression>'."""
        trigger = CronTrigger("0 9 * * 1-5")
        assert str(trigger) == "cron:0 9 * * 1-5"


class TestCronTriggerConstruction:
    def test_invalid_expression_raises_at_construction(self) -> None:
        """An invalid cron expression raises eagerly at __init__, not on first use."""
        with pytest.raises(ValueError, match="columns"):
            CronTrigger("not a cron expression")


class TestCronTriggerRunTimes:
    def test_first_run_time_no_start_uses_current_time_as_anchor(self) -> None:
        """With no start, first_run_time anchors the cron grid to current_time."""
        trigger = CronTrigger("0 9 * * *")
        current_time = zdt(2025, 8, 18, 7, 0, 0)
        result = trigger.first_run_time(current_time)
        assert result == zdt(2025, 8, 18, 9, 0, 0)

    def test_first_run_time_with_future_start_anchors_to_start(self) -> None:
        """When start is in the future relative to current_time, the search anchors to start
        and returns the first cron-grid tick strictly after it — not current_time, and not
        necessarily start itself when start isn't exactly on the grid.
        """
        start = zdt(2025, 8, 20, 8, 0, 0)  # not on the "0 9 * * *" grid
        trigger = CronTrigger("0 9 * * *", start=start)
        current_time = zdt(2025, 8, 18, 7, 0, 0)
        result = trigger.first_run_time(current_time)
        assert result == zdt(2025, 8, 20, 9, 0, 0)

    def test_next_run_time_after_previous_run(self) -> None:
        """next_run_time returns the next cron-grid tick strictly after previous_run."""
        trigger = CronTrigger("0 9 * * *")
        previous_run = zdt(2025, 8, 18, 9, 0, 0)
        current_time = zdt(2025, 8, 18, 12, 0, 0)
        result = trigger.next_run_time(previous_run, current_time)
        assert result == zdt(2025, 8, 19, 9, 0, 0)

    def test_next_run_time_every_15_minutes(self) -> None:
        """A sub-hourly cron expression advances to the correct next grid tick."""
        trigger = CronTrigger("*/15 * * * *")
        previous_run = zdt(2025, 8, 18, 9, 0, 0)
        current_time = zdt(2025, 8, 18, 9, 7, 0)
        result = trigger.next_run_time(previous_run, current_time)
        assert result == zdt(2025, 8, 18, 9, 15, 0)


class TestCronTriggerMaxIterationsFallback:
    def test_exceeding_max_iterations_skips_ahead_from_current_time(self) -> None:
        """When catching up would take more than MAX_CRON_ITERATIONS ticks, the loop
        gives up and re-anchors from current_time instead of iterating forever.

        Patches MAX_CRON_ITERATIONS to 5 so the test doesn't spin through 10k iterations.
        """
        anchor = zdt(2025, 8, 18, 0, 0, 0)
        current_time = anchor.add(minutes=10)

        with patch("hassette.scheduler.classes.MAX_CRON_ITERATIONS", 5):
            trigger = CronTrigger("* * * * *", start=anchor)
            result = trigger.first_run_time(current_time)

        assert result > current_time
        assert (result - current_time).total("seconds") <= 60

    def test_exceeding_max_iterations_result_is_timezone_correct(self) -> None:
        """The skip-ahead result still carries the trigger's original timezone."""
        anchor = zdt(2025, 8, 18, 0, 0, 0)
        current_time = anchor.add(minutes=10)

        with patch("hassette.scheduler.classes.MAX_CRON_ITERATIONS", 5):
            trigger = CronTrigger("* * * * *", start=anchor)
            result = trigger.first_run_time(current_time)

        assert result.tz == TZ
