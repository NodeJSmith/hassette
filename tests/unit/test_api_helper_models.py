"""Unit tests for the ``models/helpers`` package and ``CounterState``.

These tests exercise the Pydantic validation contract for the 8 helper CRUD
domains plus the new ``CounterState``:

- ``{Domain}Record`` allows extra fields (defensive HA drift posture).
- ``Update{Domain}Params`` accepts an empty dict and ignores extra fields
  (round-trip compatibility).
- ``Create{Domain}Params`` omits unset optional fields from
  ``model_dump(exclude_unset=True)`` and preserves explicit falsy values.
- ``CreateInputDatetimeParams`` enforces ``has_date or has_time``.
- ``CounterState`` resolves through the state registry and round-trips a
  realistic state dict.
"""

import pytest
from pydantic import ValidationError

from hassette import STATE_REGISTRY
from hassette.models.helpers import (
    CounterRecord,
    CreateCounterParams,
    CreateInputBooleanParams,
    CreateInputButtonParams,
    CreateInputDatetimeParams,
    CreateInputNumberParams,
    CreateInputSelectParams,
    CreateInputTextParams,
    CreateTimerParams,
    InputBooleanRecord,
    InputButtonRecord,
    InputDatetimeRecord,
    InputNumberRecord,
    InputSelectRecord,
    InputTextRecord,
    TimerRecord,
    UpdateCounterParams,
    UpdateInputBooleanParams,
    UpdateInputButtonParams,
    UpdateInputDatetimeParams,
    UpdateInputNumberParams,
    UpdateInputSelectParams,
    UpdateInputTextParams,
    UpdateTimerParams,
)
from hassette.models.states import CounterState
from hassette.models.states.counter import CounterAttributes


class TestInputBooleanModels:
    def test_record_allows_extra_fields(self):
        record = InputBooleanRecord.model_validate(
            {"id": "vacation_mode", "name": "Vacation Mode", "unknown_future_field": 123}
        )
        assert record.id == "vacation_mode"
        assert record.name == "Vacation Mode"
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == 123

    def test_update_accepts_empty_dict(self):
        params = UpdateInputBooleanParams()
        assert params.model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateInputBooleanParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_exclude_unset_omits_untouched_fields(self):
        params = CreateInputBooleanParams(name="x")
        assert params.model_dump(exclude_unset=True) == {"name": "x"}

    def test_create_exclude_unset_preserves_false(self):
        params = CreateInputBooleanParams(name="x", initial=False)
        dumped = params.model_dump(exclude_unset=True)
        assert dumped == {"name": "x", "initial": False}

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateInputBooleanParams(name="x", inital=True)


class TestInputNumberModels:
    def test_record_allows_extra_fields(self):
        record = InputNumberRecord.model_validate(
            {
                "id": "temperature",
                "name": "Temperature",
                "min": 0,
                "max": 100,
                "unknown_future_field": "foo",
            }
        )
        assert record.min == 0
        assert record.max == 100
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == "foo"

    def test_update_accepts_empty_dict(self):
        assert UpdateInputNumberParams().model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateInputNumberParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_exclude_unset_omits_untouched_fields(self):
        params = CreateInputNumberParams(name="x", min=0, max=10)
        assert params.model_dump(exclude_unset=True) == {"name": "x", "min": 0, "max": 10}

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateInputNumberParams(name="x", min=0, max=10, mini=0)


class TestInputTextModels:
    def test_record_allows_extra_fields(self):
        record = InputTextRecord.model_validate({"id": "note", "name": "Note", "unknown_future_field": 42})
        assert record.name == "Note"
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == 42

    def test_update_accepts_empty_dict(self):
        assert UpdateInputTextParams().model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateInputTextParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_exclude_unset_omits_untouched_fields(self):
        params = CreateInputTextParams(name="x")
        assert params.model_dump(exclude_unset=True) == {"name": "x"}

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateInputTextParams(name="x", maximum=100)


class TestInputSelectModels:
    def test_record_allows_extra_fields(self):
        record = InputSelectRecord.model_validate(
            {
                "id": "mode",
                "name": "Mode",
                "options": ["a", "b"],
                "unknown_future_field": True,
            }
        )
        assert record.options == ["a", "b"]
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] is True

    def test_update_accepts_empty_dict(self):
        assert UpdateInputSelectParams().model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateInputSelectParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_exclude_unset_omits_untouched_fields(self):
        params = CreateInputSelectParams(name="x", options=["a", "b"])
        assert params.model_dump(exclude_unset=True) == {"name": "x", "options": ["a", "b"]}

    def test_create_requires_options(self):
        with pytest.raises(ValidationError):
            CreateInputSelectParams(name="x")

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateInputSelectParams(name="x", optionss=["a"])


class TestInputDatetimeModels:
    def test_record_allows_extra_fields(self):
        record = InputDatetimeRecord.model_validate(
            {
                "id": "start",
                "name": "Start",
                "has_date": True,
                "has_time": False,
                "unknown_future_field": "x",
            }
        )
        assert record.has_date is True
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == "x"

    def test_update_accepts_empty_dict(self):
        assert UpdateInputDatetimeParams().model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateInputDatetimeParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_exclude_unset_omits_untouched_fields(self):
        params = CreateInputDatetimeParams(name="x", has_date=True)
        dumped = params.model_dump(exclude_unset=True)
        assert dumped == {"name": "x", "has_date": True}

    def test_create_input_datetime_requires_date_or_time(self):
        with pytest.raises(ValidationError) as excinfo:
            CreateInputDatetimeParams(name="x", has_date=False, has_time=False)
        message = str(excinfo.value)
        assert "has_date" in message
        assert "has_time" in message

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateInputDatetimeParams(name="x", hasdate=True)


class TestInputButtonModels:
    def test_record_allows_extra_fields(self):
        record = InputButtonRecord.model_validate({"id": "press", "name": "Press Me", "unknown_future_field": 1})
        assert record.name == "Press Me"
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == 1

    def test_update_accepts_empty_dict(self):
        assert UpdateInputButtonParams().model_dump(exclude_unset=True) == {}

    def test_create_minimum_fields(self):
        params = CreateInputButtonParams(name="Press")
        assert params.model_dump(exclude_unset=True) == {"name": "Press"}

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateInputButtonParams(name="Press", unknown_field="x")


class TestCounterModels:
    def test_record_allows_extra_fields(self):
        record = CounterRecord.model_validate(
            {
                "id": "count",
                "name": "Count",
                "minimum": 0,
                "maximum": 10,
                "unknown_future_field": "x",
            }
        )
        assert record.minimum == 0
        assert record.maximum == 10
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == "x"

    def test_update_accepts_empty_dict(self):
        assert UpdateCounterParams().model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateCounterParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_exclude_unset_omits_untouched_fields(self):
        params = CreateCounterParams(name="x")
        assert params.model_dump(exclude_unset=True) == {"name": "x"}

    def test_create_exclude_unset_preserves_zero(self):
        params = CreateCounterParams(name="x", initial=0)
        dumped = params.model_dump(exclude_unset=True)
        assert dumped == {"name": "x", "initial": 0}

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError.

        ``counter`` uses ``minimum``/``maximum``, so passing ``min`` is a
        common misspelling that must be rejected.
        """
        with pytest.raises(ValidationError):
            CreateCounterParams(name="x", min=0)


class TestTimerModels:
    def test_record_allows_extra_fields(self):
        record = TimerRecord.model_validate(
            {
                "id": "brew",
                "name": "Brew",
                "duration": "00:05:00",
                "unknown_future_field": 1,
            }
        )
        assert record.duration == "00:05:00"
        assert record.model_extra is not None
        assert record.model_extra["unknown_future_field"] == 1

    def test_update_accepts_empty_dict(self):
        assert UpdateTimerParams().model_dump(exclude_unset=True) == {}

    def test_update_ignores_extra_fields(self):
        params = UpdateTimerParams(**{"unknown_future_field": 1})
        assert "unknown_future_field" not in params.model_dump()

    def test_create_accepts_duration_hhmmss(self):
        params = CreateTimerParams(name="x", duration="00:05:00")
        dumped = params.model_dump(exclude_unset=True)
        assert dumped == {"name": "x", "duration": "00:05:00"}

    def test_create_rejects_unknown_fields(self):
        """Create*Params has extra='forbid' — misspelled kwargs raise ValidationError."""
        with pytest.raises(ValidationError):
            CreateTimerParams(name="x", duraton="00:01:00")


class TestCounterState:
    def test_counter_state_registry_resolves(self):
        assert STATE_REGISTRY.resolve(domain="counter") is CounterState

    def test_counter_state_model_validate(self):
        state_dict = {
            "entity_id": "counter.test",
            "state": "5",
            "attributes": {
                "initial": 0,
                "step": 1,
                "minimum": 0,
                "maximum": 10,
                "editable": True,
            },
            "last_changed": "2026-04-10T00:00:00+00:00",
            "last_updated": "2026-04-10T00:00:00+00:00",
            "context": {"id": "abc", "parent_id": None, "user_id": None},
        }
        state = CounterState.model_validate(state_dict)
        assert state.entity_id == "counter.test"
        assert state.domain == "counter"
        assert state.value == 5
        assert isinstance(state.attributes, CounterAttributes)
        assert state.attributes.initial == 0
        assert state.attributes.step == 1
        assert state.attributes.minimum == 0
        assert state.attributes.maximum == 10
