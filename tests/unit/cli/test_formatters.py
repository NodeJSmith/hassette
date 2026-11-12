"""Unit tests for CLI column formatters (hassette.cli.formatters) not covered alongside the rendering layer."""

from collections.abc import Callable, Iterator

import pytest
import whenever

from hassette.cli.formatters import fmt_hour


class TestFmtHour:
    @pytest.fixture
    def system_tz(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
        """Set the system timezone whenever reads, restoring it afterwards."""

        def set_tz(name: str) -> None:
            monkeypatch.setenv("TZ", name)
            whenever.reset_system_tz()

        yield set_tz
        monkeypatch.undo()
        whenever.reset_system_tz()

    def test_whole_hour_offset(self, system_tz: Callable[[str], None]) -> None:
        system_tz("UTC")
        assert fmt_hour(0) == "1970-01-01 00:00"

    def test_fractional_hour_offset_keeps_local_minutes(self, system_tz: Callable[[str], None]) -> None:
        """A UTC hour bucket starts at :30 local time in a +05:30 zone."""
        system_tz("Asia/Kolkata")
        assert fmt_hour(0) == "1970-01-01 05:30"
