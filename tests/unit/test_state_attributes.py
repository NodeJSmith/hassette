"""Tests for state model attribute alignment with HA core.

Covers all attributes added and removed as part of #289.
"""

import pytest

from hassette.models.states.alarm_control_panel import AlarmControlPanelAttributes
from hassette.models.states.camera import CameraAttributes
from hassette.models.states.climate import ClimateAttributes
from hassette.models.states.fan import FanAttributes
from hassette.models.states.humidifier import HumidifierAttributes
from hassette.models.states.light import LightAttributes
from hassette.models.states.lock import LockAttributes
from hassette.models.states.media_player import MediaPlayerAttributes
from hassette.models.states.sensor import SensorAttributes
from hassette.models.states.weather import WeatherAttributes


# ── Sensor (Finding #9) ──────────────────────────────────────────────


class TestSensorAttributes:
    def test_last_reset_present(self) -> None:
        attrs = SensorAttributes(last_reset="2024-01-01T00:00:00+00:00")
        assert attrs.last_reset == "2024-01-01T00:00:00+00:00"

    def test_last_reset_defaults_to_none(self) -> None:
        attrs = SensorAttributes()
        assert attrs.last_reset is None


# ── Humidifier (Finding #10) ─────────────────────────────────────────


class TestHumidifierAttributes:
    def test_target_humidity_step_present(self) -> None:
        attrs = HumidifierAttributes(target_humidity_step=5.0)
        assert attrs.target_humidity_step == 5.0

    def test_target_humidity_step_defaults_to_none(self) -> None:
        attrs = HumidifierAttributes()
        assert attrs.target_humidity_step is None


# ── Alarm Control Panel (Finding #11) ────────────────────────────────


class TestAlarmControlPanelAttributes:
    def test_changed_by_is_str(self) -> None:
        attrs = AlarmControlPanelAttributes(changed_by="user123")
        assert attrs.changed_by == "user123"

    def test_removed_previous_state_lands_in_extras(self) -> None:
        attrs = AlarmControlPanelAttributes(previous_state="armed_away")
        assert attrs.extra("previous_state") == "armed_away"

    def test_removed_next_state_lands_in_extras(self) -> None:
        attrs = AlarmControlPanelAttributes(next_state="disarmed")
        assert attrs.extra("next_state") == "disarmed"


# ── Light (Finding #4) ───────────────────────────────────────────────


class TestLightAttributes:
    def test_rgbw_color_present(self) -> None:
        attrs = LightAttributes(rgbw_color=(255, 0, 0, 128))
        assert attrs.rgbw_color == (255, 0, 0, 128)

    def test_rgbw_color_defaults_to_none(self) -> None:
        attrs = LightAttributes()
        assert attrs.rgbw_color is None

    def test_rgbww_color_present(self) -> None:
        attrs = LightAttributes(rgbww_color=(255, 0, 0, 128, 64))
        assert attrs.rgbww_color == (255, 0, 0, 128, 64)

    def test_rgbww_color_defaults_to_none(self) -> None:
        attrs = LightAttributes()
        assert attrs.rgbww_color is None


# ── Climate (Finding #5) ─────────────────────────────────────────────


class TestClimateAttributes:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("humidity", 50.0),
            ("swing_horizontal_mode", "auto"),
            ("target_temp_step", 0.5),
            ("min_humidity", 30.0),
            ("max_humidity", 70.0),
            ("target_humidity_step", 5.0),
            ("swing_horizontal_modes", ["auto", "off"]),
        ],
    )
    def test_new_field_present(self, field: str, value: object) -> None:
        attrs = ClimateAttributes(**{field: value})
        assert getattr(attrs, field) == value

    @pytest.mark.parametrize(
        "field",
        [
            "humidity",
            "swing_horizontal_mode",
            "target_temp_step",
            "min_humidity",
            "max_humidity",
            "target_humidity_step",
            "swing_horizontal_modes",
        ],
    )
    def test_new_field_defaults_to_none(self, field: str) -> None:
        attrs = ClimateAttributes()
        assert getattr(attrs, field) is None


# ── Weather (Finding #6) ─────────────────────────────────────────────


class TestWeatherAttributes:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("ozone", 280.0),
            ("uv_index", 7.5),
            ("wind_gust_speed", 25.0),
            ("visibility", 10.0),
        ],
    )
    def test_new_field_present(self, field: str, value: object) -> None:
        attrs = WeatherAttributes(**{field: value})
        assert getattr(attrs, field) == value

    @pytest.mark.parametrize(
        "field",
        ["ozone", "uv_index", "wind_gust_speed", "visibility"],
    )
    def test_new_field_defaults_to_none(self, field: str) -> None:
        attrs = WeatherAttributes()
        assert getattr(attrs, field) is None


# ── Fan (Finding #7) ─────────────────────────────────────────────────


class TestFanAttributes:
    def test_direction_present(self) -> None:
        attrs = FanAttributes(direction="forward")
        assert attrs.direction == "forward"

    def test_direction_defaults_to_none(self) -> None:
        attrs = FanAttributes()
        assert attrs.direction is None

    @pytest.mark.parametrize(
        "field",
        ["temperature", "model", "sn", "screen_status", "child_lock", "night_light", "mode"],
    )
    def test_removed_field_lands_in_extras(self, field: str) -> None:
        attrs = FanAttributes(**{field: "test_value"})
        assert attrs.extra(field) == "test_value"


# ── Camera (Finding #8) ──────────────────────────────────────────────


class TestCameraAttributes:
    def test_motion_detection_present(self) -> None:
        attrs = CameraAttributes(motion_detection=True)
        assert attrs.motion_detection is True

    def test_motion_detection_defaults_to_none(self) -> None:
        attrs = CameraAttributes()
        assert attrs.motion_detection is None


# ── Lock (Finding #3) ────────────────────────────────────────────────


class TestLockAttributes:
    def test_changed_by_present(self) -> None:
        attrs = LockAttributes(changed_by="user123")
        assert attrs.changed_by == "user123"

    def test_changed_by_defaults_to_none(self) -> None:
        attrs = LockAttributes()
        assert attrs.changed_by is None

    def test_code_format_present(self) -> None:
        attrs = LockAttributes(code_format="^\\d{4}$")
        assert attrs.code_format == "^\\d{4}$"

    def test_code_format_defaults_to_none(self) -> None:
        attrs = LockAttributes()
        assert attrs.code_format is None


# ── Media Player (Finding #1) ────────────────────────────────────────


class TestMediaPlayerAttributes:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("volume_level", 0.75),
            ("is_volume_muted", True),
            ("media_content_id", "spotify:track:123"),
            ("media_content_type", "music"),
            ("media_duration", 300),
            ("media_position", 120),
            ("media_position_updated_at", "2024-01-01T12:00:00+00:00"),
            ("media_title", "Song Title"),
            ("media_artist", "Artist Name"),
            ("media_album_name", "Album Name"),
            ("media_album_artist", "Album Artist"),
            ("media_track", 5),
            ("media_series_title", "Series Title"),
            ("media_season", "1"),
            ("media_episode", "5"),
            ("media_channel", "HBO"),
            ("media_playlist", "My Playlist"),
            ("app_id", "com.spotify"),
            ("app_name", "Spotify"),
            ("source", "HDMI 1"),
            ("sound_mode", "stereo"),
            ("shuffle", True),
            ("repeat", "all"),
            ("group_members", ["media_player.speaker_1", "media_player.speaker_2"]),
            ("source_list", ["HDMI 1", "HDMI 2", "AUX"]),
            ("sound_mode_list", ["stereo", "surround"]),
        ],
    )
    def test_new_field_present(self, field: str, value: object) -> None:
        attrs = MediaPlayerAttributes(**{field: value})
        assert getattr(attrs, field) == value

    @pytest.mark.parametrize(
        "field",
        [
            "volume_level",
            "is_volume_muted",
            "media_content_id",
            "media_content_type",
            "media_duration",
            "media_position",
            "media_position_updated_at",
            "media_title",
            "media_artist",
            "media_album_name",
            "media_album_artist",
            "media_track",
            "media_series_title",
            "media_season",
            "media_episode",
            "media_channel",
            "media_playlist",
            "app_id",
            "app_name",
            "source",
            "sound_mode",
            "shuffle",
            "repeat",
            "group_members",
            "source_list",
            "sound_mode_list",
        ],
    )
    def test_new_field_defaults_to_none(self, field: str) -> None:
        attrs = MediaPlayerAttributes()
        assert getattr(attrs, field) is None

    @pytest.mark.parametrize(
        "field",
        ["assumed_state", "adb_response", "hdmi_input"],
    )
    def test_removed_field_lands_in_extras(self, field: str) -> None:
        attrs = MediaPlayerAttributes(**{field: "test_value"})
        assert attrs.extra(field) == "test_value"
