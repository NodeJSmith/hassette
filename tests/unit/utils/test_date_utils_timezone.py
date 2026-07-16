"""Tests for configurable timezone in date_utils."""

import pytest
from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils


@pytest.fixture(autouse=True)
def _reset_configured_tz():
    """Reset the configured timezone after each test."""
    yield
    date_utils.configure(None)


class TestConfigure:
    def test_configure_sets_timezone(self) -> None:
        date_utils.configure("America/Chicago")
        assert date_utils._configured_tz == "America/Chicago"

    def test_configure_none_clears_timezone(self) -> None:
        date_utils.configure("America/Chicago")
        date_utils.configure(None)
        assert date_utils._configured_tz is None


class TestNow:
    def test_now_uses_configured_tz(self) -> None:
        date_utils.configure("America/Chicago")
        result = date_utils.now()
        assert result.tz == "America/Chicago"

    def test_now_uses_system_tz_when_unconfigured(self) -> None:
        result = date_utils.now()
        system_tz = ZonedDateTime.now_in_system_tz().tz
        assert result.tz == system_tz

    def test_now_different_timezones_same_instant(self) -> None:
        """now() in different configured timezones represents the same instant."""
        date_utils.configure("America/Chicago")
        chicago = date_utils.now()
        date_utils.configure("Europe/London")
        london = date_utils.now()
        diff = abs((london - chicago).total("seconds"))
        assert diff < 1


class TestConvertUtcTimestamp:
    def test_uses_configured_tz(self) -> None:
        date_utils.configure("America/Chicago")
        result = date_utils.convert_utc_timestamp_to_system_tz(0)
        assert result.tz == "America/Chicago"
        assert result.hour == 18
        assert result.day == 31
        assert result.month == 12
        assert result.year == 1969

    def test_uses_system_tz_when_unconfigured(self) -> None:
        result = date_utils.convert_utc_timestamp_to_system_tz(0)
        system_tz = ZonedDateTime.now_in_system_tz().tz
        assert result.tz == system_tz

    def test_same_instant_regardless_of_tz(self) -> None:
        """The same timestamp maps to the same instant in different timezones."""
        ts = 1_700_000_000
        date_utils.configure("America/Chicago")
        chicago = date_utils.convert_utc_timestamp_to_system_tz(ts)
        date_utils.configure("Asia/Tokyo")
        tokyo = date_utils.convert_utc_timestamp_to_system_tz(ts)
        assert chicago.to_instant() == tokyo.to_instant()


class TestConvertDatetimeStr:
    def test_uses_configured_tz(self) -> None:
        date_utils.configure("America/Chicago")
        result = date_utils.convert_datetime_str_to_system_tz("2025-06-15T12:00:00+00:00")
        assert result is not None
        assert result.tz == "America/Chicago"
        assert result.hour == 7

    def test_uses_system_tz_when_unconfigured(self) -> None:
        result = date_utils.convert_datetime_str_to_system_tz("2025-06-15T12:00:00+00:00")
        assert result is not None
        system_tz = ZonedDateTime.now_in_system_tz().tz
        assert result.tz == system_tz

    def test_none_passthrough(self) -> None:
        date_utils.configure("America/Chicago")
        assert date_utils.convert_datetime_str_to_system_tz(None) is None

    def test_zoned_datetime_passthrough(self) -> None:
        zdt = ZonedDateTime(2025, 6, 15, 12, 0, tz="Europe/London")
        date_utils.configure("America/Chicago")
        result = date_utils.convert_datetime_str_to_system_tz(zdt)
        assert result is zdt

    def test_same_instant_regardless_of_tz(self) -> None:
        iso = "2025-06-15T12:00:00+00:00"
        date_utils.configure("America/Chicago")
        chicago = date_utils.convert_datetime_str_to_system_tz(iso)
        date_utils.configure("Asia/Tokyo")
        tokyo = date_utils.convert_datetime_str_to_system_tz(iso)
        assert chicago is not None
        assert tokyo is not None
        assert chicago.to_instant() == tokyo.to_instant()
