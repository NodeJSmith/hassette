"""Unit tests for EntityWatch sub-struct."""

from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import EntityWatch


class TestEntityWatchConstruction:
    def test_required_fields_with_duration(self) -> None:
        """EntityWatch can be constructed with entity_id and duration."""
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert cfg.duration == 5.0
        assert cfg.entity_id == "light.kitchen"

    def test_required_fields_entity_id_only(self) -> None:
        """EntityWatch can be constructed with only entity_id (duration defaults to None)."""
        cfg = EntityWatch(entity_id="light.kitchen")
        assert cfg.entity_id == "light.kitchen"
        assert cfg.duration is None

    def test_default_immediate(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert cfg.immediate is False

    def test_default_attribute_is_none(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert cfg.attribute is None

    def test_default_hold_predicate(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert cfg.hold_predicate is None

    def test_default_timer_is_none(self) -> None:
        """_timer starts as None — not yet attached."""
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert cfg._timer is None

    def test_set_immediate(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0, immediate=True)
        assert cfg.immediate is True

    def test_set_attribute(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0, attribute="brightness")
        assert cfg.attribute == "brightness"

    def test_set_hold_predicate(self) -> None:
        pred = MagicMock()
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0, hold_predicate=pred)
        assert cfg.hold_predicate is pred

    def test_has_slots(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert hasattr(type(cfg), "__slots__")


class TestEntityWatchValidation:
    @pytest.mark.parametrize("invalid_duration", [-1, 0, -0.001])
    def test_duration_must_be_positive(self, invalid_duration: float) -> None:
        with pytest.raises(ValueError, match="duration"):
            EntityWatch(entity_id="light.kitchen", duration=invalid_duration)

    @pytest.mark.parametrize("duration", [5, None])
    def test_entity_id_required(self, duration: float | None) -> None:
        with pytest.raises(ValueError, match="entity_id"):
            EntityWatch(entity_id="", duration=duration)

    @pytest.mark.parametrize("valid_duration", [0.001, 3600.0, None])
    def test_valid_durations_accepted(self, valid_duration: float | None) -> None:
        cfg = EntityWatch(entity_id="sensor.temp", duration=valid_duration)
        assert cfg.duration == valid_duration


class TestEntityWatchAttachTimer:
    @staticmethod
    def attach(cfg: EntityWatch) -> None:
        cfg.attach_timer(
            task_bucket=MagicMock(),
            owner_id="test_owner",
            create_cancel_sub=MagicMock(return_value=MagicMock()),
            on_cancel=MagicMock(),
        )

    def test_attach_timer_stores_timer(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        self.attach(cfg)
        assert cfg._timer is not None

    def test_timer_property_after_attach(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        self.attach(cfg)
        assert cfg.timer is not None
        assert cfg.timer is cfg._timer

    def test_timer_property_raises_before_attach(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        with pytest.raises(RuntimeError, match="timer not yet attached"):
            _ = cfg.timer

    def test_attach_timer_raises_if_already_attached(self) -> None:
        cfg = EntityWatch(entity_id="light.kitchen", duration=5.0)
        self.attach(cfg)
        with pytest.raises(RuntimeError, match="timer already attached"):
            self.attach(cfg)

    def test_attach_timer_passes_fields_to_duration_timer(self) -> None:
        pred = MagicMock()
        cfg = EntityWatch(
            entity_id="binary_sensor.motion",
            duration=10.0,
            hold_predicate=pred,
        )
        self.attach(cfg)

        timer = cfg._timer
        assert timer is not None
        assert timer.duration == 10.0
        assert timer.entity_id == "binary_sensor.motion"
        assert timer.predicates is pred
