"""Unit tests for ApiResource._get_history_raw URL formatting."""

from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.utils.request_utils import format_time_param


class TestFormatTimeParam:
    def test_zoned_datetime_strips_iana_suffix(self) -> None:
        dt = ZonedDateTime(2026, 4, 26, 20, 13, 1, tz="America/Chicago")
        result = format_time_param(dt)
        assert "[" not in result
        assert "America/Chicago" not in result
        assert result == "2026-04-26T20:13:01-05:00"

    def test_plain_datetime_passes_through(self) -> None:
        dt = PlainDateTime(2026, 4, 26, 20, 13, 1)
        result = format_time_param(dt)
        assert result == "2026-04-26T20:13:01"

    def test_date_passes_through(self) -> None:
        dt = Date(2026, 4, 26)
        result = format_time_param(dt)
        assert result == "2026-04-26"

    def test_string_passes_through(self) -> None:
        result = format_time_param("2026-04-26T20:13:01-05:00")
        assert result == "2026-04-26T20:13:01-05:00"
