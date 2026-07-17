"""Tests for RecordingApi helper CRUD methods and AppTestHarness.seed_helper.

Covers:
- seed_helper round-trip (seed → list)
- seed_helper rejects unknown record type
- create → list round-trip (slug transformation, collision auto-suffix)
- update raises FailedMessageError on missing id, mutates on hit
- delete raises FailedMessageError on missing id, removes on hit
- reset clears helper_definitions
- create records an ApiCall
- counter action methods record an ApiCall
"""

import pytest
from pydantic import BaseModel

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.exceptions import FailedMessageError
from hassette.models.helpers import (
    CounterRecord,
    CreateCounterParams,
    CreateInputBooleanParams,
    CreateInputSelectParams,
    InputBooleanRecord,
    InputButtonRecord,
    InputDatetimeRecord,
    InputNumberRecord,
    InputSelectRecord,
    InputTextRecord,
    TimerRecord,
    UpdateInputBooleanParams,
)
from hassette.test_utils.app_harness import AppTestHarness
from hassette.test_utils.factories import make_recording_api
from hassette.test_utils.recording_api import RECORD_TYPE_TO_DOMAIN, slugify_helper_name


class _HarnessConfig(AppConfig):
    """Minimal AppConfig for harness tests in this module."""


class _HarnessApp(App[_HarnessConfig]):
    """Minimal App subclass used to exercise AppTestHarness.seed_helper paths."""

    async def on_initialize(self) -> None:
        pass


async def test_seed_helper_then_list_returns_seeded_record():
    api = make_recording_api()
    record = InputBooleanRecord(id="vacation_mode", name="Vacation Mode")
    api.helpers.helper_definitions["input_boolean"]["vacation_mode"] = record

    result = await api.helpers.list("input_boolean")
    assert len(result) == 1
    assert result[0].id == "vacation_mode"
    assert result[0].name == "Vacation Mode"


def test_seed_helper_rejects_unknown_type():
    """RECORD_TYPE_TO_DOMAIN does not contain arbitrary BaseModel subclasses."""

    class UnknownRecord(BaseModel):
        id: str
        name: str

    unknown = UnknownRecord(id="foo", name="Foo")

    with pytest.raises(KeyError):
        _ = RECORD_TYPE_TO_DOMAIN[type(unknown)]  # pyright: ignore[reportArgumentType]


async def test_seed_helper_type_map_covers_all_imports():
    """Smoke-test that RECORD_TYPE_TO_DOMAIN has all 8 expected record types."""
    expected = {
        InputBooleanRecord,
        InputNumberRecord,
        InputTextRecord,
        InputSelectRecord,
        InputDatetimeRecord,
        InputButtonRecord,
        CounterRecord,
        TimerRecord,
    }
    assert set(RECORD_TYPE_TO_DOMAIN.keys()) == expected


async def test_create_input_boolean_adds_to_list():
    api = make_recording_api()
    record = await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))
    result = await api.helpers.list("input_boolean")
    assert len(result) == 1
    assert result[0].id == record.id
    assert result[0].name == "vacation_mode"


async def test_create_input_boolean_slugifies_name():
    api = make_recording_api()
    record = await api.helpers.create(CreateInputBooleanParams(name="Vacation Mode"))
    assert record.id == "vacation_mode"


async def test_create_input_boolean_auto_suffixes_collision():
    api = make_recording_api()
    first = await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))
    second = await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))

    assert first.id == "vacation_mode"
    assert second.id == "vacation_mode_2"

    all_records = await api.helpers.list("input_boolean")
    assert len(all_records) == 2


async def test_update_input_boolean_raises_on_missing_id():
    api = make_recording_api()

    with pytest.raises(FailedMessageError) as exc_info:
        await api.helpers.update("nonexistent", UpdateInputBooleanParams(initial=True))

    assert exc_info.value.code == "not_found"
    assert "input_boolean" in str(exc_info.value)


async def test_update_input_boolean_mutates_seed():
    api = make_recording_api()
    record = await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))
    updated = await api.helpers.update(record.id, UpdateInputBooleanParams(initial=True))

    assert updated.initial is True
    assert updated.id == record.id

    listed = await api.helpers.list("input_boolean")
    assert len(listed) == 1
    assert listed[0].initial is True


async def test_delete_input_boolean_raises_on_missing_id():
    api = make_recording_api()

    with pytest.raises(FailedMessageError) as exc_info:
        await api.helpers.delete("input_boolean", "nonexistent")

    assert exc_info.value.code == "not_found"


async def test_delete_input_boolean_removes_from_list():
    api = make_recording_api()
    record = await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))
    await api.helpers.delete("input_boolean", record.id)

    result = await api.helpers.list("input_boolean")
    assert result == []


async def test_reset_clears_helper_definitions():
    api = make_recording_api()
    # Seed across multiple domains
    await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))
    await api.helpers.create(CreateCounterParams(name="my_counter"))
    api.helpers.helper_definitions["timer"]["manual_timer"] = TimerRecord(id="manual_timer", name="Manual Timer")

    api.reset()

    assert await api.helpers.list("input_boolean") == []
    assert await api.helpers.list("counter") == []
    assert await api.helpers.list("timer") == []
    assert api.calls == []


async def test_create_records_api_call():
    api = make_recording_api()
    await api.helpers.create(CreateInputBooleanParams(name="vacation_mode"))

    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "create_input_boolean"
    assert call.kwargs["name"] == "vacation_mode"


async def test_counter_action_records_api_call_increment():
    """Increment delegates to call_service (matches HelperClient's real implementation)."""
    api = make_recording_api()
    await api.helpers.increment("counter.foo")

    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "call_service"
    assert call.kwargs["domain"] == "counter"
    assert call.kwargs["service"] == "increment"
    assert call.kwargs["target"] == {"entity_id": "counter.foo"}


async def test_counter_action_records_api_call_decrement():
    api = make_recording_api()
    await api.helpers.decrement("counter.bar")

    call = api.calls[0]
    assert call.method == "call_service"
    assert call.kwargs["domain"] == "counter"
    assert call.kwargs["service"] == "decrement"
    assert call.kwargs["target"] == {"entity_id": "counter.bar"}


async def test_counter_action_records_api_call_reset():
    api = make_recording_api()
    await api.helpers.reset("counter.baz")

    call = api.calls[0]
    assert call.method == "call_service"
    assert call.kwargs["domain"] == "counter"
    assert call.kwargs["service"] == "reset"
    assert call.kwargs["target"] == {"entity_id": "counter.baz"}


def test_slugify_helper_name_fallback_for_empty_slug():
    """Cover all three branches of slugify_helper_name.

    - Non-empty inputs that slugify to "" fall back to "unknown" (matching HA).
    - ``""`` and ``None`` inputs return ``""`` directly (no fallback).
    - Otherwise the python-slugify output is returned as-is.
    """
    assert slugify_helper_name("%%") == "unknown"
    assert slugify_helper_name("!!!") == "unknown"
    assert slugify_helper_name("") == ""
    assert slugify_helper_name(None) == ""
    assert slugify_helper_name("Vacation Mode") == "vacation_mode"


async def test_list_returns_isolated_copies():
    """Mutating records returned by list_* must not affect the stored state."""
    api = make_recording_api()
    api.helpers.helper_definitions["input_boolean"]["x"] = InputBooleanRecord(id="x", name="Original")

    returned = (await api.helpers.list("input_boolean"))[0]
    returned.name = "Mutated"

    refetched = (await api.helpers.list("input_boolean"))[0]
    assert refetched.name == "Original"


async def test_list_isolation_preserves_nested_collections():
    """InputSelectRecord.options must be deep-copied on list/create returns.

    Shallow ``model_copy()`` would alias ``options: list[str]`` between the
    stored record and the returned copy, so a caller appending to the
    returned record would silently corrupt harness state. Verify both the
    list_* path (pre-seeded record) and the create_* path (newly-created
    record) return isolated copies.
    """
    api = make_recording_api()

    api.helpers.helper_definitions["input_select"]["mode"] = InputSelectRecord(
        id="mode", name="Mode", options=["a", "b"]
    )

    listed = (await api.helpers.list("input_select"))[0]
    listed.options.append("MUTATED")

    refetched = (await api.helpers.list("input_select"))[0]
    assert refetched.options == ["a", "b"]

    created = await api.helpers.create(CreateInputSelectParams(name="Another", options=["x", "y"]))
    created.options.append("ALSO_MUTATED")

    fetched_after_create = next(r for r in await api.helpers.list("input_select") if r.id == created.id)
    assert fetched_after_create.options == ["x", "y"]


async def test_seed_helper_rejects_duplicate_id():
    """seed_helper raises ValueError when seeding a duplicate id in the same domain."""
    async with AppTestHarness(_HarnessApp, config={}) as harness:
        harness.seed_helper(InputBooleanRecord(id="vacation_mode", name="First"))

        def seed_duplicate() -> None:
            harness.seed_helper(InputBooleanRecord(id="vacation_mode", name="Second"))

        with pytest.raises(ValueError, match="already seeded"):
            seed_duplicate()


async def test_harness_seed_helper_rejects_unknown_record_type():
    """seed_helper raises ValueError (not KeyError) when given an unregistered BaseModel."""

    class UnknownRecord(BaseModel):
        id: str
        name: str

    async with AppTestHarness(_HarnessApp, config={}) as harness:
        unknown = UnknownRecord(id="foo", name="Foo")

        def seed_unknown() -> None:
            harness.seed_helper(unknown)

        with pytest.raises(ValueError, match="Unknown helper record type") as exc_info:
            seed_unknown()

    message = str(exc_info.value)
    assert "UnknownRecord" in message
    assert "InputBooleanRecord" in message


async def test_seed_helper_isolates_caller_mutations():
    """seed_helper deep-copies the record so later caller-side mutations don't leak."""
    async with AppTestHarness(_HarnessApp, config={}) as harness:
        caller_record = InputSelectRecord(id="mode", name="Mode", options=["a", "b"])
        harness.seed_helper(caller_record)

        # Mutate the caller-side record after seeding — scalar and nested list.
        caller_record.name = "Mutated"
        caller_record.options.append("c")

        # The harness store should be untouched.
        listed = await harness.api_recorder.helpers.list("input_select")
        assert len(listed) == 1
        assert listed[0].name == "Mode"
        assert listed[0].options == ["a", "b"]
