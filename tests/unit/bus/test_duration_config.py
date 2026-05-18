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
    def test_duration_must_be_positive(self) -> None:
        """AC#5: DurationConfig(duration=-1, entity_id='x') raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            DurationConfig(entity_id="light.kitchen", duration=-1)

    def test_duration_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="duration"):
            DurationConfig(entity_id="light.kitchen", duration=0)

    def test_duration_negative_float_raises(self) -> None:
        with pytest.raises(ValueError, match="duration"):
            DurationConfig(entity_id="light.kitchen", duration=-0.001)

    def test_entity_id_required(self) -> None:
        """AC#5: DurationConfig(duration=5, entity_id='') raises ValueError."""
        with pytest.raises(ValueError, match="entity_id"):
            DurationConfig(entity_id="", duration=5)

    def test_entity_id_required_no_duration(self) -> None:
        """entity_id is required even when duration is None."""
        with pytest.raises(ValueError, match="entity_id"):
            DurationConfig(entity_id="")

    def test_positive_duration_ok(self) -> None:
        cfg = DurationConfig(entity_id="sensor.temp", duration=0.001)
        assert cfg.duration == 0.001

    def test_large_duration_ok(self) -> None:
        cfg = DurationConfig(entity_id="sensor.temp", duration=3600.0)
        assert cfg.duration == 3600.0

    def test_none_duration_ok(self) -> None:
        """duration=None is valid for entity_id-only or immediate-only configs."""
        cfg = DurationConfig(entity_id="light.kitchen")
        assert cfg.duration is None


class TestDurationConfigAttachTimer:
    def test_attach_timer_stores_timer(self) -> None:
        """attach_timer() constructs a DurationTimer and stores it in _timer."""
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)

        task_bucket = MagicMock()
        create_cancel_sub = MagicMock(return_value=MagicMock())
        on_cancel = MagicMock()

        cfg.attach_timer(
            task_bucket=task_bucket,
            owner_id="test_owner",
            create_cancel_sub=create_cancel_sub,
            on_cancel=on_cancel,
        )

        assert cfg._timer is not None

    def test_timer_property_after_attach(self) -> None:
        """timer property returns the DurationTimer after attach_timer()."""
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)

        task_bucket = MagicMock()
        create_cancel_sub = MagicMock(return_value=MagicMock())
        on_cancel = MagicMock()

        cfg.attach_timer(
            task_bucket=task_bucket,
            owner_id="test_owner",
            create_cancel_sub=create_cancel_sub,
            on_cancel=on_cancel,
        )

        timer = cfg.timer
        assert timer is not None
        assert timer is cfg._timer

    def test_timer_property_raises_before_attach(self) -> None:
        """timer property raises AssertionError when _timer is None."""
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)
        with pytest.raises(AssertionError):
            _ = cfg.timer

    def test_attach_timer_raises_if_already_attached(self) -> None:
        """attach_timer() raises if called a second time (timer already attached)."""
        cfg = DurationConfig(entity_id="light.kitchen", duration=5.0)

        task_bucket = MagicMock()
        create_cancel_sub = MagicMock(return_value=MagicMock())
        on_cancel = MagicMock()

        cfg.attach_timer(
            task_bucket=task_bucket,
            owner_id="test_owner",
            create_cancel_sub=create_cancel_sub,
            on_cancel=on_cancel,
        )

        with pytest.raises(AssertionError):
            cfg.attach_timer(
                task_bucket=task_bucket,
                owner_id="test_owner",
                create_cancel_sub=create_cancel_sub,
                on_cancel=on_cancel,
            )

    def test_attach_timer_passes_fields_to_duration_timer(self) -> None:
        """attach_timer() passes duration, entity_id, and hold_predicate to DurationTimer."""
        pred = MagicMock()
        cfg = DurationConfig(
            entity_id="binary_sensor.motion",
            duration=10.0,
            hold_predicate=pred,
        )

        task_bucket = MagicMock()
        create_cancel_sub = MagicMock(return_value=MagicMock())
        on_cancel = MagicMock()

        cfg.attach_timer(
            task_bucket=task_bucket,
            owner_id="test_owner",
            create_cancel_sub=create_cancel_sub,
            on_cancel=on_cancel,
        )

        timer = cfg._timer
        assert timer is not None
        assert timer.duration == 10.0
        assert timer.entity_id == "binary_sensor.motion"
        assert timer.predicates is pred
