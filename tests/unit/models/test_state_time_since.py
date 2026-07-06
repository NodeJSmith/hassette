"""Tests for BaseState.time_since_last_change/update/report properties."""

from unittest.mock import patch

import pytest
from whenever import TimeDelta, ZonedDateTime

from hassette.models.states.light import LightState
from hassette.test_utils import make_light_state_dict

FIXED_NOW = ZonedDateTime(2026, 7, 6, 12, 0, 0, tz="UTC")
TEN_MINUTES_AGO = FIXED_NOW.subtract(minutes=10)


@pytest.fixture(autouse=True)
def _freeze_now():
    with patch("hassette.utils.date_utils.now", return_value=FIXED_NOW):
        yield


class TestTimeSinceLastChange:
    def test_returns_elapsed_time(self) -> None:
        data = make_light_state_dict(last_changed=TEN_MINUTES_AGO.format_iso())
        state = LightState(**data)
        assert state.time_since_last_change == TimeDelta(minutes=10)

    def test_returns_none_when_timestamp_is_none(self) -> None:
        data = make_light_state_dict()
        data["last_changed"] = None
        state = LightState(**data)
        assert state.time_since_last_change is None


class TestTimeSinceLastUpdate:
    def test_returns_elapsed_time(self) -> None:
        data = make_light_state_dict(last_updated=TEN_MINUTES_AGO.format_iso())
        state = LightState(**data)
        assert state.time_since_last_update == TimeDelta(minutes=10)

    def test_returns_none_when_timestamp_is_none(self) -> None:
        data = make_light_state_dict()
        data["last_updated"] = None
        state = LightState(**data)
        assert state.time_since_last_update is None


class TestTimeSinceLastReport:
    def test_returns_elapsed_time(self) -> None:
        data = make_light_state_dict(last_reported=TEN_MINUTES_AGO.format_iso())
        state = LightState(**data)
        assert state.time_since_last_report == TimeDelta(minutes=10)

    def test_returns_none_when_timestamp_is_none(self) -> None:
        data = make_light_state_dict()
        state = LightState(**data)
        assert state.time_since_last_report is None
