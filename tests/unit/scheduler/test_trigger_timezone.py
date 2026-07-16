"""Tests that scheduler triggers resolve HH:MM against the configured timezone."""

import pytest
from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.scheduler.triggers import Daily, Once


@pytest.fixture(autouse=True)
def _reset_configured_tz():
    yield
    date_utils.configure(None)


class TestOnceWithConfiguredTz:
    def test_once_resolves_against_configured_tz(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Once(at='07:00') uses the configured timezone, not system tz."""
        date_utils.configure("America/Chicago")
        fake_now = ZonedDateTime(2025, 8, 18, 6, 0, 0, tz="America/Chicago")
        monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

        trigger = Once(at="07:00")
        fire_time = trigger.first_run_time(fake_now)

        assert fire_time.tz == "America/Chicago"
        assert fire_time.hour == 7
        assert fire_time.minute == 0

    def test_once_uses_system_tz_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Once(at='07:00') uses system tz when no timezone is configured."""
        system_tz = ZonedDateTime.now_in_system_tz().tz
        fake_now = ZonedDateTime(2025, 8, 18, 6, 0, 0, tz=system_tz)
        monkeypatch.setattr("hassette.utils.date_utils.now", lambda: fake_now)

        trigger = Once(at="07:00")
        fire_time = trigger.first_run_time(fake_now)

        assert fire_time.tz == system_tz


class TestDailyWithConfiguredTz:
    def test_daily_resolves_against_configured_tz(self) -> None:
        """Daily(at='07:00') uses the configured timezone for cron scheduling."""
        date_utils.configure("America/Chicago")
        current = ZonedDateTime(2025, 8, 18, 6, 0, 0, tz="America/Chicago")

        trigger = Daily(at="07:00")
        fire_time = trigger.first_run_time(current)

        assert fire_time.tz == "America/Chicago"
        assert fire_time.hour == 7
        assert fire_time.minute == 0

    def test_daily_next_day_when_past(self) -> None:
        """Daily(at='07:00') schedules for tomorrow when current time is past 07:00."""
        date_utils.configure("America/Chicago")
        current = ZonedDateTime(2025, 8, 18, 8, 0, 0, tz="America/Chicago")

        trigger = Daily(at="07:00")
        fire_time = trigger.first_run_time(current)

        assert fire_time.day == 19
        assert fire_time.hour == 7
