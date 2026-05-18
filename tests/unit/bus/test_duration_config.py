"""Unit tests for DurationConfig sub-struct."""

from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import DurationConfig


class TestDurationConfigConstruction:
    def test_required_fields_with_duration(self) -> None:
        """DurationConfig can be constructed with entity_id and duration."""
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        assert cfg.duration == 5.0
        assert cfg.entity_id == "light.kitchen"

    def test_required_fields_entity_id_only(self) -> None:
        """DurationConfig can be constructed with only entity_id (duration defaults to None)."""
        cfg = DurationConfig(entity_id="light.kitchen")
        assert cfg.entity_id == "light.kitchen"
        assert cfg.duration is None

    def test_default_immediate(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        assert cfg.immediate is False

    def test_default_is_attribute_listener(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        assert cfg.is_attribute_listener is False

    def test_default_hold_predicate(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        assert cfg.hold_predicate is None

    def test_default_timer_is_none(self) -> None:
        """_timer starts as None — not yet attached."""
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        assert cfg._timer is None

    def test_set_immediate(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0, immediate=True)
        assert cfg.immediate is True

    def test_set_is_attribute_listener(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0, is_attribute_listener=True)
        assert cfg.is_attribute_listener is True

    def test_set_hold_predicate(self) -> None:
        pred = MagicMock()
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0, hold_predicate=pred)
        assert cfg.hold_predicate is pred

    def test_has_slots(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        assert hasattr(type(cfg), "__slots__")


class TestDurationConfigValidation:
    @pytest.mark.parametrize("invalid_duration", [-1, 0, -0.001])
    def test_duration_must_be_positive(self, invalid_duration: float) -> None:
        with pytest.raises(ValueError, match="duration"):
            DurationConfig(entity_id="light.kitchen", duration=invalid_duration)

    @pytest.mark.parametrize("duration", [5, None])
    def test_entity_id_required(self, duration: float | None) -> None:
        with pytest.raises(ValueError, match="entity_id"):
            DurationConfig(entity_id="", duration=duration)

    @pytest.mark.parametrize("valid_duration", [0.001, 3600.0, None])
    def test_valid_durations_accepted(self, valid_duration: float | None) -> None:
        cfg = DurationConfig(entity_id="sensor.temp", duration=valid_duration)
        assert cfg.duration == valid_duration


class TestDurationConfigAttachTimer:
    @staticmethod
    def _attach(cfg: DurationConfig) -> None:
        cfg.attach_timer(
            task_bucket=MagicMock(),
            owner_id="test_owner",
            create_cancel_sub=MagicMock(return_value=MagicMock()),
            on_cancel=MagicMock(),
        )

    def test_attach_timer_stores_timer(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        self._attach(cfg)
        assert cfg._timer is not None

    def test_timer_property_after_attach(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        self._attach(cfg)
        assert cfg.timer is not None
        assert cfg.timer is cfg._timer

    def test_timer_property_raises_before_attach(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        with pytest.raises(AssertionError):
            _ = cfg.timer

    def test_attach_timer_raises_if_already_attached(self) -> None:
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        self._attach(cfg)
        with pytest.raises(AssertionError):
            self._attach(cfg)

    def test_attach_timer_passes_fields_to_duration_timer(self) -> None:
        pred = MagicMock()
        cfg = DurationConfig(
            entity_id="binary_sensor.motion",
            duration=10.0,
            hold_predicate=pred,
        )
        self._attach(cfg)

        timer = cfg._timer
        assert timer is not None
        assert timer.duration == 10.0
        assert timer.entity_id == "binary_sensor.motion"
        assert timer.predicates is pred
