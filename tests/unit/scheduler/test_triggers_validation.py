"""Tests for trigger validation and metadata methods not covered by tests/unit/test_triggers.py.

Focuses on: parse_hh_mm error branches, After/Once/Every/Daily/Cron construction validation,
and the trigger_label/trigger_detail/trigger_db_type metadata methods used for telemetry/UI.
"""

import pytest
from whenever import TimeDelta

from hassette.scheduler.triggers import After, Cron, Daily, Every, Once, parse_hh_mm

from .conftest import zdt


class TestParseHHMM:
    def test_missing_colon_raises(self) -> None:
        """A string with no ':' separator raises ValueError naming the expected format."""
        with pytest.raises(ValueError, match="must be 'HH:MM'"):
            parse_hh_mm("0700", "TestLabel")

    def test_too_many_parts_raises(self) -> None:
        """A string with more than one ':' raises ValueError."""
        with pytest.raises(ValueError, match="must be 'HH:MM'"):
            parse_hh_mm("07:00:00", "TestLabel")

    def test_non_numeric_parts_raise(self) -> None:
        """Non-numeric hour/minute components raise ValueError naming the expected format."""
        with pytest.raises(ValueError, match="must be 'HH:MM'"):
            parse_hh_mm("ab:cd", "TestLabel")

    def test_hour_out_of_range_raises(self) -> None:
        """An hour outside 0-23 raises ValueError naming the out-of-range time."""
        with pytest.raises(ValueError, match="out of range"):
            parse_hh_mm("24:00", "TestLabel")

    def test_minute_out_of_range_raises(self) -> None:
        """A minute outside 0-59 raises ValueError naming the out-of-range time."""
        with pytest.raises(ValueError, match="out of range"):
            parse_hh_mm("07:60", "TestLabel")

    def test_valid_time_returns_hour_and_minute(self) -> None:
        """A valid 'HH:MM' string returns the parsed (hour, minute) tuple."""
        assert parse_hh_mm("07:30", "TestLabel") == (7, 30)

    def test_boundary_values_accepted(self) -> None:
        """The boundary values 00:00 and 23:59 are accepted."""
        assert parse_hh_mm("00:00", "TestLabel") == (0, 0)
        assert parse_hh_mm("23:59", "TestLabel") == (23, 59)


class TestAfterValidation:
    def test_zero_delay_raises(self) -> None:
        """After() with a zero-second total delay raises ValueError."""
        with pytest.raises(ValueError, match="delay must be positive"):
            After(seconds=0, minutes=0)

    def test_negative_delay_raises(self) -> None:
        """After() with a negative delay raises ValueError."""
        with pytest.raises(ValueError, match="delay must be positive"):
            After(seconds=-5)

    def test_timedelta_argument_used_directly(self) -> None:
        """Passing timedelta= uses it directly instead of seconds/minutes."""
        trigger = After(timedelta=TimeDelta(minutes=2))
        assert trigger.trigger_id() == "after:120"

    def test_seconds_and_minutes_combine(self) -> None:
        """seconds and minutes combine into a single delay."""
        trigger = After(seconds=30, minutes=1)
        assert trigger.trigger_id() == "after:90"

    def test_metadata_methods(self) -> None:
        """trigger_label/trigger_detail/trigger_db_type return the expected values."""
        trigger = After(seconds=45)
        assert trigger.trigger_label() == "after"
        assert trigger.trigger_detail() == "45s"
        assert trigger.trigger_db_type() == "after"


class TestOnceValidation:
    def test_zoned_datetime_in_future_fires_at_that_instant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Once(at=future_zdt) fires exactly at that instant, with no deferral logic applied."""
        now_t = zdt(2025, 8, 18, 6, 0, 0)
        monkeypatch.setattr("hassette.utils.date_utils.now", lambda: now_t)

        future = zdt(2025, 8, 18, 10, 0, 0)
        trigger = Once(at=future)
        assert trigger.first_run_time(now_t) == future

    def test_zoned_datetime_future_if_past_error_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """if_past='error' with a future ZonedDateTime does not raise (only past times raise)."""
        now_t = zdt(2025, 8, 18, 6, 0, 0)
        monkeypatch.setattr("hassette.utils.date_utils.now", lambda: now_t)

        future = zdt(2025, 8, 18, 10, 0, 0)
        trigger = Once(at=future, if_past="error")
        assert trigger.first_run_time(future) == future

    def test_metadata_methods_for_string_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """trigger_detail() returns the original 'HH:MM' string when constructed from a string."""
        now_t = zdt(2025, 8, 18, 6, 0, 0)
        monkeypatch.setattr("hassette.utils.date_utils.now", lambda: now_t)

        trigger = Once(at="09:15")
        assert trigger.trigger_label() == "once"
        assert trigger.trigger_detail() == "09:15"
        assert trigger.trigger_db_type() == "once"

    def test_metadata_methods_for_zoned_datetime_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """trigger_detail() falls back to the ISO timestamp when constructed from a ZonedDateTime."""
        now_t = zdt(2025, 8, 18, 6, 0, 0)
        monkeypatch.setattr("hassette.utils.date_utils.now", lambda: now_t)

        target = zdt(2025, 8, 20, 9, 0, 0)
        trigger = Once(at=target)
        assert trigger.trigger_detail() == target.format_iso()

    def test_next_run_time_returns_none(self) -> None:
        """Once is one-shot: next_run_time always returns None regardless of inputs."""
        target = zdt(2025, 8, 20, 9, 0, 0)
        trigger = Once(at=target)
        assert trigger.next_run_time(target, target) is None


class TestEveryValidation:
    def test_zero_interval_raises(self) -> None:
        """Every() with a zero total interval raises ValueError."""
        with pytest.raises(ValueError, match="interval must be positive"):
            Every(seconds=0)

    def test_negative_interval_raises(self) -> None:
        """Every() with a negative interval raises ValueError."""
        with pytest.raises(ValueError, match="interval must be positive"):
            Every(seconds=-30)

    def test_fractional_interval_raises(self) -> None:
        """Every() with a sub-second (non-whole-second) interval raises ValueError."""
        with pytest.raises(ValueError, match="whole number of seconds"):
            Every(seconds=0.5)

    def test_interval_seconds_property(self) -> None:
        """interval_seconds reflects the combined seconds/minutes/hours interval."""
        trigger = Every(minutes=1, seconds=30)
        assert trigger.interval_seconds == 90

    def test_first_run_time_start_equal_to_current_time_advances(self) -> None:
        """When start == current_time exactly, first_run_time advances past it (not <=)."""
        t = zdt(2025, 8, 18, 7, 0, 0)
        trigger = Every(seconds=60, start=t)
        result = trigger.first_run_time(t)
        assert result == zdt(2025, 8, 18, 7, 1, 0)

    def test_metadata_methods(self) -> None:
        """trigger_label/trigger_detail/trigger_db_type return the expected values."""
        trigger = Every(minutes=2)
        assert trigger.trigger_label() == "every"
        assert trigger.trigger_detail() == "120s"
        assert trigger.trigger_db_type() == "interval"


class TestDailyValidation:
    def test_invalid_at_raises(self) -> None:
        """Daily() propagates parse_hh_mm's ValueError for a malformed 'at' string."""
        with pytest.raises(ValueError, match="must be 'HH:MM'"):
            Daily(at="not-a-time")

    def test_metadata_methods(self) -> None:
        """trigger_label/trigger_detail/trigger_db_type return the expected values."""
        trigger = Daily(at="08:30")
        assert trigger.trigger_label() == "daily"
        assert trigger.trigger_detail() == "08:30"
        assert trigger.trigger_db_type() == "cron"


class TestCronValidation:
    def test_invalid_expression_wraps_croniter_error(self) -> None:
        """Cron() wraps the underlying croniter ValueError with a descriptive message."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            Cron("99 99 * * *")

    def test_metadata_methods(self) -> None:
        """trigger_label/trigger_detail/trigger_db_type return the expected values."""
        trigger = Cron("0 9 * * 1-5")
        assert trigger.trigger_label() == "cron"
        assert trigger.trigger_detail() == "0 9 * * 1-5"
        assert trigger.trigger_db_type() == "cron"

    def test_next_run_time_delegates_to_internal_cron_trigger(self) -> None:
        """Cron.next_run_time() returns the next grid-aligned tick after previous_run."""
        trigger = Cron("0 9 * * *")
        previous_run = zdt(2025, 8, 18, 9, 0, 0)
        current_time = zdt(2025, 8, 18, 12, 0, 0)
        result = trigger.next_run_time(previous_run, current_time)
        assert result == zdt(2025, 8, 19, 9, 0, 0)
