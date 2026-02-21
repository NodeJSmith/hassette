"""Tests for supported_features bitmask helpers on domain attribute classes."""

import pytest

from hassette.models.states.base import AttributesBase
from hassette.models.states.climate import ClimateAttributes
from hassette.models.states.cover import CoverAttributes
from hassette.models.states.fan import FanAttributes
from hassette.models.states.features import (
    ClimateEntityFeature,
    CoverEntityFeature,
    FanEntityFeature,
    LightEntityFeature,
    LockEntityFeature,
    MediaPlayerEntityFeature,
    VacuumEntityFeature,
)
from hassette.models.states.light import LightAttributes
from hassette.models.states.lock import LockAttributes
from hassette.models.states.media_player import MediaPlayerAttributes
from hassette.models.states.vacuum import VacuumAttributes


class TestAttributesBaseHasFeature:
    """Tests for the _has_feature() helper on AttributesBase."""

    def test_returns_false_when_supported_features_is_none(self) -> None:
        attrs = AttributesBase(supported_features=None)
        assert attrs._has_feature(1) is False

    def test_returns_false_when_flag_not_set(self) -> None:
        attrs = AttributesBase(supported_features=0)
        assert attrs._has_feature(1) is False

    def test_returns_true_when_single_flag_set(self) -> None:
        attrs = AttributesBase(supported_features=4)
        assert attrs._has_feature(4) is True

    def test_returns_true_when_flag_in_combined_bitmask(self) -> None:
        attrs = AttributesBase(supported_features=5)  # 1 | 4
        assert attrs._has_feature(4) is True
        assert attrs._has_feature(1) is True

    def test_returns_false_for_missing_flag_in_combined_bitmask(self) -> None:
        attrs = AttributesBase(supported_features=5)  # 1 | 4
        assert attrs._has_feature(2) is False

    def test_handles_float_supported_features(self) -> None:
        attrs = AttributesBase(supported_features=4.0)
        assert attrs._has_feature(4) is True

    def test_handles_large_bitmask(self) -> None:
        attrs = AttributesBase(supported_features=4194304)
        assert attrs._has_feature(4194304) is True
        assert attrs._has_feature(1) is False


# ── Light ──────────────────────────────────────────────────────────────


class TestLightSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (LightEntityFeature.EFFECT, "supports_effect"),
            (LightEntityFeature.FLASH, "supports_flash"),
            (LightEntityFeature.TRANSITION, "supports_transition"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = LightAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (LightEntityFeature.EFFECT, "supports_effect"),
            (LightEntityFeature.FLASH, "supports_flash"),
            (LightEntityFeature.TRANSITION, "supports_transition"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        # Use a bitmask that excludes this specific feature
        all_features = LightEntityFeature.EFFECT | LightEntityFeature.FLASH | LightEntityFeature.TRANSITION
        attrs = LightAttributes(supported_features=all_features & ~feature_value)
        assert getattr(attrs, property_name) is False

    def test_combined_bitmask(self) -> None:
        combined = LightEntityFeature.EFFECT | LightEntityFeature.TRANSITION
        attrs = LightAttributes(supported_features=combined)
        assert attrs.supports_effect is True
        assert attrs.supports_flash is False
        assert attrs.supports_transition is True

    def test_none_returns_all_false(self) -> None:
        attrs = LightAttributes(supported_features=None)
        assert attrs.supports_effect is False
        assert attrs.supports_flash is False
        assert attrs.supports_transition is False


# ── Climate ────────────────────────────────────────────────────────────


class TestClimateSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (ClimateEntityFeature.TARGET_TEMPERATURE, "supports_target_temperature"),
            (ClimateEntityFeature.TARGET_TEMPERATURE_RANGE, "supports_target_temperature_range"),
            (ClimateEntityFeature.TARGET_HUMIDITY, "supports_target_humidity"),
            (ClimateEntityFeature.FAN_MODE, "supports_fan_mode"),
            (ClimateEntityFeature.PRESET_MODE, "supports_preset_mode"),
            (ClimateEntityFeature.SWING_MODE, "supports_swing_mode"),
            (ClimateEntityFeature.TURN_OFF, "supports_turn_off"),
            (ClimateEntityFeature.TURN_ON, "supports_turn_on"),
            (ClimateEntityFeature.SWING_HORIZONTAL_MODE, "supports_swing_horizontal_mode"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = ClimateAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (ClimateEntityFeature.TARGET_TEMPERATURE, "supports_target_temperature"),
            (ClimateEntityFeature.TARGET_TEMPERATURE_RANGE, "supports_target_temperature_range"),
            (ClimateEntityFeature.TARGET_HUMIDITY, "supports_target_humidity"),
            (ClimateEntityFeature.FAN_MODE, "supports_fan_mode"),
            (ClimateEntityFeature.PRESET_MODE, "supports_preset_mode"),
            (ClimateEntityFeature.SWING_MODE, "supports_swing_mode"),
            (ClimateEntityFeature.TURN_OFF, "supports_turn_off"),
            (ClimateEntityFeature.TURN_ON, "supports_turn_on"),
            (ClimateEntityFeature.SWING_HORIZONTAL_MODE, "supports_swing_horizontal_mode"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        attrs = ClimateAttributes(supported_features=0)
        assert getattr(attrs, property_name) is False

    def test_combined_bitmask(self) -> None:
        combined = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.TURN_ON
        )
        attrs = ClimateAttributes(supported_features=combined)
        assert attrs.supports_target_temperature is True
        assert attrs.supports_fan_mode is True
        assert attrs.supports_turn_on is True
        assert attrs.supports_preset_mode is False
        assert attrs.supports_swing_mode is False

    def test_none_returns_all_false(self) -> None:
        attrs = ClimateAttributes(supported_features=None)
        assert attrs.supports_target_temperature is False
        assert attrs.supports_turn_on is False
        assert attrs.supports_swing_horizontal_mode is False


# ── Cover ──────────────────────────────────────────────────────────────


class TestCoverSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (CoverEntityFeature.OPEN, "supports_open"),
            (CoverEntityFeature.CLOSE, "supports_close"),
            (CoverEntityFeature.SET_POSITION, "supports_set_position"),
            (CoverEntityFeature.STOP, "supports_stop"),
            (CoverEntityFeature.OPEN_TILT, "supports_open_tilt"),
            (CoverEntityFeature.CLOSE_TILT, "supports_close_tilt"),
            (CoverEntityFeature.STOP_TILT, "supports_stop_tilt"),
            (CoverEntityFeature.SET_TILT_POSITION, "supports_set_tilt_position"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = CoverAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (CoverEntityFeature.OPEN, "supports_open"),
            (CoverEntityFeature.CLOSE, "supports_close"),
            (CoverEntityFeature.SET_POSITION, "supports_set_position"),
            (CoverEntityFeature.STOP, "supports_stop"),
            (CoverEntityFeature.OPEN_TILT, "supports_open_tilt"),
            (CoverEntityFeature.CLOSE_TILT, "supports_close_tilt"),
            (CoverEntityFeature.STOP_TILT, "supports_stop_tilt"),
            (CoverEntityFeature.SET_TILT_POSITION, "supports_set_tilt_position"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        attrs = CoverAttributes(supported_features=0)
        assert getattr(attrs, property_name) is False

    def test_combined_bitmask(self) -> None:
        combined = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        attrs = CoverAttributes(supported_features=combined)
        assert attrs.supports_open is True
        assert attrs.supports_close is True
        assert attrs.supports_stop is True
        assert attrs.supports_set_position is False
        assert attrs.supports_open_tilt is False

    def test_none_returns_all_false(self) -> None:
        attrs = CoverAttributes(supported_features=None)
        assert attrs.supports_open is False
        assert attrs.supports_set_tilt_position is False


# ── Fan ────────────────────────────────────────────────────────────────


class TestFanSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (FanEntityFeature.SET_SPEED, "supports_set_speed"),
            (FanEntityFeature.OSCILLATE, "supports_oscillate"),
            (FanEntityFeature.DIRECTION, "supports_direction"),
            (FanEntityFeature.PRESET_MODE, "supports_preset_mode"),
            (FanEntityFeature.TURN_OFF, "supports_turn_off"),
            (FanEntityFeature.TURN_ON, "supports_turn_on"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = FanAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (FanEntityFeature.SET_SPEED, "supports_set_speed"),
            (FanEntityFeature.OSCILLATE, "supports_oscillate"),
            (FanEntityFeature.DIRECTION, "supports_direction"),
            (FanEntityFeature.PRESET_MODE, "supports_preset_mode"),
            (FanEntityFeature.TURN_OFF, "supports_turn_off"),
            (FanEntityFeature.TURN_ON, "supports_turn_on"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        attrs = FanAttributes(supported_features=0)
        assert getattr(attrs, property_name) is False

    def test_combined_bitmask(self) -> None:
        combined = FanEntityFeature.SET_SPEED | FanEntityFeature.OSCILLATE | FanEntityFeature.TURN_ON
        attrs = FanAttributes(supported_features=combined)
        assert attrs.supports_set_speed is True
        assert attrs.supports_oscillate is True
        assert attrs.supports_turn_on is True
        assert attrs.supports_direction is False
        assert attrs.supports_preset_mode is False

    def test_none_returns_all_false(self) -> None:
        attrs = FanAttributes(supported_features=None)
        assert attrs.supports_set_speed is False
        assert attrs.supports_turn_on is False


# ── Media Player ───────────────────────────────────────────────────────


class TestMediaPlayerSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (MediaPlayerEntityFeature.PAUSE, "supports_pause"),
            (MediaPlayerEntityFeature.SEEK, "supports_seek"),
            (MediaPlayerEntityFeature.VOLUME_SET, "supports_volume_set"),
            (MediaPlayerEntityFeature.VOLUME_MUTE, "supports_volume_mute"),
            (MediaPlayerEntityFeature.PREVIOUS_TRACK, "supports_previous_track"),
            (MediaPlayerEntityFeature.NEXT_TRACK, "supports_next_track"),
            (MediaPlayerEntityFeature.TURN_ON, "supports_turn_on"),
            (MediaPlayerEntityFeature.TURN_OFF, "supports_turn_off"),
            (MediaPlayerEntityFeature.PLAY_MEDIA, "supports_play_media"),
            (MediaPlayerEntityFeature.VOLUME_STEP, "supports_volume_step"),
            (MediaPlayerEntityFeature.SELECT_SOURCE, "supports_select_source"),
            (MediaPlayerEntityFeature.STOP, "supports_stop"),
            (MediaPlayerEntityFeature.CLEAR_PLAYLIST, "supports_clear_playlist"),
            (MediaPlayerEntityFeature.PLAY, "supports_play"),
            (MediaPlayerEntityFeature.SHUFFLE_SET, "supports_shuffle_set"),
            (MediaPlayerEntityFeature.SELECT_SOUND_MODE, "supports_select_sound_mode"),
            (MediaPlayerEntityFeature.BROWSE_MEDIA, "supports_browse_media"),
            (MediaPlayerEntityFeature.REPEAT_SET, "supports_repeat_set"),
            (MediaPlayerEntityFeature.GROUPING, "supports_grouping"),
            (MediaPlayerEntityFeature.MEDIA_ANNOUNCE, "supports_media_announce"),
            (MediaPlayerEntityFeature.MEDIA_ENQUEUE, "supports_media_enqueue"),
            (MediaPlayerEntityFeature.SEARCH_MEDIA, "supports_search_media"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = MediaPlayerAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (MediaPlayerEntityFeature.PAUSE, "supports_pause"),
            (MediaPlayerEntityFeature.SEEK, "supports_seek"),
            (MediaPlayerEntityFeature.VOLUME_SET, "supports_volume_set"),
            (MediaPlayerEntityFeature.VOLUME_MUTE, "supports_volume_mute"),
            (MediaPlayerEntityFeature.PREVIOUS_TRACK, "supports_previous_track"),
            (MediaPlayerEntityFeature.NEXT_TRACK, "supports_next_track"),
            (MediaPlayerEntityFeature.TURN_ON, "supports_turn_on"),
            (MediaPlayerEntityFeature.TURN_OFF, "supports_turn_off"),
            (MediaPlayerEntityFeature.PLAY_MEDIA, "supports_play_media"),
            (MediaPlayerEntityFeature.VOLUME_STEP, "supports_volume_step"),
            (MediaPlayerEntityFeature.SELECT_SOURCE, "supports_select_source"),
            (MediaPlayerEntityFeature.STOP, "supports_stop"),
            (MediaPlayerEntityFeature.CLEAR_PLAYLIST, "supports_clear_playlist"),
            (MediaPlayerEntityFeature.PLAY, "supports_play"),
            (MediaPlayerEntityFeature.SHUFFLE_SET, "supports_shuffle_set"),
            (MediaPlayerEntityFeature.SELECT_SOUND_MODE, "supports_select_sound_mode"),
            (MediaPlayerEntityFeature.BROWSE_MEDIA, "supports_browse_media"),
            (MediaPlayerEntityFeature.REPEAT_SET, "supports_repeat_set"),
            (MediaPlayerEntityFeature.GROUPING, "supports_grouping"),
            (MediaPlayerEntityFeature.MEDIA_ANNOUNCE, "supports_media_announce"),
            (MediaPlayerEntityFeature.MEDIA_ENQUEUE, "supports_media_enqueue"),
            (MediaPlayerEntityFeature.SEARCH_MEDIA, "supports_search_media"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        attrs = MediaPlayerAttributes(supported_features=0)
        assert getattr(attrs, property_name) is False

    def test_combined_bitmask(self) -> None:
        combined = (
            MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
        )
        attrs = MediaPlayerAttributes(supported_features=combined)
        assert attrs.supports_pause is True
        assert attrs.supports_play is True
        assert attrs.supports_stop is True
        assert attrs.supports_volume_set is True
        assert attrs.supports_seek is False
        assert attrs.supports_shuffle_set is False

    def test_none_returns_all_false(self) -> None:
        attrs = MediaPlayerAttributes(supported_features=None)
        assert attrs.supports_pause is False
        assert attrs.supports_play is False
        assert attrs.supports_search_media is False


# ── Vacuum ─────────────────────────────────────────────────────────────


class TestVacuumSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (VacuumEntityFeature.PAUSE, "supports_pause"),
            (VacuumEntityFeature.STOP, "supports_stop"),
            (VacuumEntityFeature.RETURN_HOME, "supports_return_home"),
            (VacuumEntityFeature.FAN_SPEED, "supports_fan_speed"),
            (VacuumEntityFeature.SEND_COMMAND, "supports_send_command"),
            (VacuumEntityFeature.LOCATE, "supports_locate"),
            (VacuumEntityFeature.CLEAN_SPOT, "supports_clean_spot"),
            (VacuumEntityFeature.START, "supports_start"),
            (VacuumEntityFeature.CLEAN_AREA, "supports_clean_area"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = VacuumAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (VacuumEntityFeature.PAUSE, "supports_pause"),
            (VacuumEntityFeature.STOP, "supports_stop"),
            (VacuumEntityFeature.RETURN_HOME, "supports_return_home"),
            (VacuumEntityFeature.FAN_SPEED, "supports_fan_speed"),
            (VacuumEntityFeature.SEND_COMMAND, "supports_send_command"),
            (VacuumEntityFeature.LOCATE, "supports_locate"),
            (VacuumEntityFeature.CLEAN_SPOT, "supports_clean_spot"),
            (VacuumEntityFeature.START, "supports_start"),
            (VacuumEntityFeature.CLEAN_AREA, "supports_clean_area"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        attrs = VacuumAttributes(supported_features=0)
        assert getattr(attrs, property_name) is False

    def test_combined_bitmask(self) -> None:
        combined = VacuumEntityFeature.START | VacuumEntityFeature.PAUSE | VacuumEntityFeature.RETURN_HOME
        attrs = VacuumAttributes(supported_features=combined)
        assert attrs.supports_start is True
        assert attrs.supports_pause is True
        assert attrs.supports_return_home is True
        assert attrs.supports_stop is False
        assert attrs.supports_locate is False

    def test_none_returns_all_false(self) -> None:
        attrs = VacuumAttributes(supported_features=None)
        assert attrs.supports_start is False
        assert attrs.supports_clean_area is False


# ── Lock ──────────────────────────────────────────────────────────────


class TestLockSupportedFeatures:
    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (LockEntityFeature.OPEN, "supports_open"),
        ],
    )
    def test_feature_present(self, feature_value: int, property_name: str) -> None:
        attrs = LockAttributes(supported_features=feature_value)
        assert getattr(attrs, property_name) is True

    @pytest.mark.parametrize(
        ("feature_value", "property_name"),
        [
            (LockEntityFeature.OPEN, "supports_open"),
        ],
    )
    def test_feature_absent(self, feature_value: int, property_name: str) -> None:
        attrs = LockAttributes(supported_features=0)
        assert getattr(attrs, property_name) is False

    def test_none_returns_all_false(self) -> None:
        attrs = LockAttributes(supported_features=None)
        assert attrs.supports_open is False
