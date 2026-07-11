"""Tests for the --since CLI flag type converter."""

from unittest.mock import patch

import pytest
from whenever import Instant, OffsetDateTime, PlainDateTime

from hassette.cli.types import convert_since
from hassette.const.misc import SECONDS_PER_DAY, SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from tests.unit.cli.conftest import NOW_EPOCH, fixed_now


class TestRelativeDurations:
    def test_seconds(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            result = convert_since("30s")
        assert result == pytest.approx(NOW_EPOCH - 30, abs=1)

    def test_minutes(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            result = convert_since("30m")
        assert result == pytest.approx(NOW_EPOCH - 30 * SECONDS_PER_MINUTE, abs=1)

    def test_hours(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            result = convert_since("1h")
        assert result == pytest.approx(NOW_EPOCH - SECONDS_PER_HOUR, abs=1)

    def test_days(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            result = convert_since("7d")
        assert result == pytest.approx(NOW_EPOCH - 7 * SECONDS_PER_DAY, abs=1)

    def test_weeks(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            result = convert_since("2w")
        assert result == pytest.approx(NOW_EPOCH - 14 * SECONDS_PER_DAY, abs=1)


class TestISO8601WithTimezone:
    def test_offset_minus_four(self) -> None:
        result = convert_since("2026-05-22T14:00:00-04:00")
        expected = OffsetDateTime.parse_iso("2026-05-22T14:00:00-04:00").timestamp()
        assert result == pytest.approx(expected, abs=1)

    def test_utc_z(self) -> None:
        result = convert_since("2026-05-22T18:00:00Z")
        expected = Instant.parse_iso("2026-05-22T18:00:00Z").timestamp()
        assert result == pytest.approx(expected, abs=1)


class TestISO8601Naive:
    def test_naive_datetime_uses_local_time(self) -> None:
        result = convert_since("2026-05-22T14:00:00")
        expected = PlainDateTime.parse_iso("2026-05-22T14:00:00").assume_system_tz().timestamp()
        assert result == pytest.approx(expected, abs=1)


class TestDateOnly:
    def test_date_only_is_midnight_local(self) -> None:
        result = convert_since("2026-05-22")
        expected = PlainDateTime.parse_iso("2026-05-22T00:00:00").assume_system_tz().timestamp()
        assert result == pytest.approx(expected, abs=1)


class TestInvalidInputs:
    def _assert_raises_value_error(self, value: str) -> None:
        with pytest.raises(ValueError, match="Accepted formats"):
            convert_since(value)

    def test_invalid_word(self) -> None:
        self._assert_raises_value_error("abc")

    def test_unknown_suffix(self) -> None:
        self._assert_raises_value_error("1x")

    def test_double_dash(self) -> None:
        self._assert_raises_value_error("--")

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Empty --since value"):
            convert_since("")

    def test_compound_duration_not_supported(self) -> None:
        self._assert_raises_value_error("1h30m")

    def test_months_not_supported(self) -> None:
        self._assert_raises_value_error("1M")

    def test_years_not_supported(self) -> None:
        self._assert_raises_value_error("1y")
