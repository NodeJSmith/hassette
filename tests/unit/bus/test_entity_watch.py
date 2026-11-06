"""Unit tests for EntityWatch sub-struct."""

from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import EntityWatch


class TestEntityWatchConstruction:
    def test_required_fields_with_duration(self) -> None:
        """EntityWatch can be constructed with entity_id and duration."""
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert watch.duration == 5.0
        assert watch.entity_id == "light.kitchen"

    def test_required_fields_entity_id_only(self) -> None:
        """EntityWatch can be constructed with only entity_id (duration defaults to None)."""
        watch = EntityWatch(entity_id="light.kitchen")
        assert watch.entity_id == "light.kitchen"
        assert watch.duration is None

    def test_default_immediate(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert watch.immediate is False

    def test_default_attribute_is_none(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert watch.attribute is None

    def test_default_hold_predicate(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert watch.hold_predicate is None

    def test_default_timer_is_none(self) -> None:
        """_timer starts as None — not yet attached."""
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert watch._timer is None

    def test_set_immediate(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0, immediate=True)
        assert watch.immediate is True

    def test_set_attribute(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0, attribute="brightness")
        assert watch.attribute == "brightness"

    def test_set_hold_predicate(self) -> None:
        pred = MagicMock()
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0, hold_predicate=pred)
        assert watch.hold_predicate is pred

    def test_has_slots(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        assert hasattr(type(watch), "__slots__")


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
        watch = EntityWatch(entity_id="sensor.temp", duration=valid_duration)
        assert watch.duration == valid_duration


class TestEntityWatchAttachTimer:
    @staticmethod
    def attach(watch: EntityWatch) -> None:
        watch.attach_timer(
            task_bucket=MagicMock(),
            owner_id="test_owner",
            create_cancel_sub=MagicMock(return_value=MagicMock()),
            on_cancel=MagicMock(),
        )

    def test_attach_timer_stores_timer(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        self.attach(watch)
        assert watch._timer is not None

    def test_timer_property_after_attach(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        self.attach(watch)
        assert watch.timer is not None
        assert watch.timer is watch._timer

    def test_timer_property_raises_before_attach(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        with pytest.raises(RuntimeError, match="timer not yet attached"):
            _ = watch.timer

    def test_attach_timer_raises_if_already_attached(self) -> None:
        watch = EntityWatch(entity_id="light.kitchen", duration=5.0)
        self.attach(watch)
        with pytest.raises(RuntimeError, match="timer already attached"):
            self.attach(watch)

    def test_attach_timer_passes_fields_to_duration_timer(self) -> None:
        pred = MagicMock()
        watch = EntityWatch(
            entity_id="binary_sensor.motion",
            duration=10.0,
            hold_predicate=pred,
        )
        self.attach(watch)

        timer = watch._timer
        assert timer is not None
        assert timer.duration == 10.0
        assert timer.entity_id == "binary_sensor.motion"
        assert timer.predicates is pred
