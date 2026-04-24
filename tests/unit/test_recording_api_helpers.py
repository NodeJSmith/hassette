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

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.conversion import STATE_REGISTRY
from hassette.core.state_proxy import StateProxy
from hassette.exceptions import FailedMessageError
from hassette.models.helpers import (
    CounterRecord,
    CreateCounterParams,
    CreateInputBooleanParams,
    CreateInputSelectParams,
    InputBooleanRecord,
    InputSelectRecord,
    TimerRecord,
    UpdateInputBooleanParams,
)
from hassette.test_utils.app_harness import AppTestHarness
from hassette.test_utils.recording_api import _RECORD_TYPE_TO_DOMAIN, RecordingApi, _slugify_helper_name


class _HarnessConfig(AppConfig):
    """Minimal AppConfig for harness tests in this module."""


class _HarnessApp(App[_HarnessConfig]):
    """Minimal App subclass used to exercise AppTestHarness.seed_helper paths."""

    async def on_initialize(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Test harness helpers (mirrors test_recording_api.py pattern)
# ---------------------------------------------------------------------------


def _make_hassette_stub() -> AsyncMock:
    """Minimal stub satisfying Resource.__init__ and TaskBucket.spawn."""
    hassette = AsyncMock()
    hassette.config.log_level = "DEBUG"
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.resource_shutdown_timeout_seconds = 1
    hassette.config.task_cancellation_timeout_seconds = 1
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.dev_mode = False
    hassette.event_streams_closed = False
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_running_loop()
    hassette.state_registry = STATE_REGISTRY
    return hassette


def _make_recording_api() -> RecordingApi:
    """Create a RecordingApi with an empty StateProxy."""
    hassette = _make_hassette_stub()
    state_proxy = AsyncMock(spec=StateProxy)
    state_proxy.states = {}
    state_proxy.is_ready = lambda: True
    return RecordingApi(hassette, state_proxy=state_proxy)


# ---------------------------------------------------------------------------
# seed_helper round-trip
# ---------------------------------------------------------------------------


async def test_seed_helper_then_list_returns_seeded_record():
    api = _make_recording_api()
    record = InputBooleanRecord(id="vacation_mode", name="Vacation Mode")
    api.helper_definitions["input_boolean"]["vacation_mode"] = record

    result = await api.list_input_booleans()
    assert len(result) == 1
    assert result[0].id == "vacation_mode"
    assert result[0].name == "Vacation Mode"


def test_seed_helper_rejects_unknown_type():
    """_RECORD_TYPE_TO_DOMAIN does not contain arbitrary BaseModel subclasses."""

    class UnknownRecord(BaseModel):
        id: str
        name: str

    unknown = UnknownRecord(id="foo", name="Foo")

    with pytest.raises(KeyError):
        _ = _RECORD_TYPE_TO_DOMAIN[type(unknown)]  # pyright: ignore[reportArgumentType]


# Actually test seed_helper via AppTestHarness — but to keep unit tests simple,
# test the ValueError path by calling the dict directly
async def test_seed_helper_type_map_covers_all_imports():
    """Smoke-test that _RECORD_TYPE_TO_DOMAIN has all 8 expected record types."""
    from hassette.models.helpers import (
        InputBooleanRecord,
        InputButtonRecord,
        InputDatetimeRecord,
        InputNumberRecord,
        InputSelectRecord,
        InputTextRecord,
        TimerRecord,
    )

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
    assert set(_RECORD_TYPE_TO_DOMAIN.keys()) == expected


# ---------------------------------------------------------------------------
# create_input_boolean — list round-trip, slug, collision
# ---------------------------------------------------------------------------


async def test_create_input_boolean_adds_to_list():
    api = _make_recording_api()
    record = await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))
    result = await api.list_input_booleans()
    assert len(result) == 1
    assert result[0].id == record.id
    assert result[0].name == "vacation_mode"


async def test_create_input_boolean_slugifies_name():
    api = _make_recording_api()
    record = await api.create_input_boolean(CreateInputBooleanParams(name="Vacation Mode"))
    assert record.id == "vacation_mode"


async def test_create_input_boolean_auto_suffixes_collision():
    api = _make_recording_api()
    first = await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))
    second = await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))

    assert first.id == "vacation_mode"
    assert second.id == "vacation_mode_2"

    all_records = await api.list_input_booleans()
    assert len(all_records) == 2


# ---------------------------------------------------------------------------
# update_input_boolean — missing id raises, mutation works
# ---------------------------------------------------------------------------


async def test_update_input_boolean_raises_on_missing_id():
    api = _make_recording_api()

    with pytest.raises(FailedMessageError) as exc_info:
        await api.update_input_boolean("nonexistent", UpdateInputBooleanParams(initial=True))

    assert exc_info.value.code == "not_found"
    assert "input_boolean" in str(exc_info.value)


async def test_update_input_boolean_mutates_seed():
    api = _make_recording_api()
    record = await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))
    updated = await api.update_input_boolean(record.id, UpdateInputBooleanParams(initial=True))

    assert updated.initial is True
    assert updated.id == record.id

    listed = await api.list_input_booleans()
    assert len(listed) == 1
    assert listed[0].initial is True


# ---------------------------------------------------------------------------
# delete_input_boolean — missing id raises, removal works
# ---------------------------------------------------------------------------


async def test_delete_input_boolean_raises_on_missing_id():
    api = _make_recording_api()

    with pytest.raises(FailedMessageError) as exc_info:
        await api.delete_input_boolean("nonexistent")

    assert exc_info.value.code == "not_found"


async def test_delete_input_boolean_removes_from_list():
    api = _make_recording_api()
    record = await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))
    await api.delete_input_boolean(record.id)

    result = await api.list_input_booleans()
    assert result == []


# ---------------------------------------------------------------------------
# reset clears helper_definitions
# ---------------------------------------------------------------------------


async def test_reset_clears_helper_definitions():
    api = _make_recording_api()
    # Seed across multiple domains
    await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))
    await api.create_counter(CreateCounterParams(name="my_counter"))
    api.helper_definitions["timer"]["manual_timer"] = TimerRecord(id="manual_timer", name="Manual Timer")

    api.reset()

    assert await api.list_input_booleans() == []
    assert await api.list_counters() == []
    assert await api.list_timers() == []
    assert api.calls == []


# ---------------------------------------------------------------------------
# create records ApiCall
# ---------------------------------------------------------------------------


async def test_create_records_api_call():
    api = _make_recording_api()
    await api.create_input_boolean(CreateInputBooleanParams(name="vacation_mode"))

    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "create_input_boolean"
    assert call.kwargs["name"] == "vacation_mode"


# ---------------------------------------------------------------------------
# counter action methods record ApiCall
# ---------------------------------------------------------------------------


async def test_counter_action_records_api_call_increment():
    api = _make_recording_api()
    await api.increment_counter("counter.foo")

    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "increment_counter"
    assert call.kwargs["entity_id"] == "counter.foo"


async def test_counter_action_records_api_call_decrement():
    api = _make_recording_api()
    await api.decrement_counter("counter.bar")

    call = api.calls[0]
    assert call.method == "decrement_counter"
    assert call.kwargs["entity_id"] == "counter.bar"


async def test_counter_action_records_api_call_reset():
    api = _make_recording_api()
    await api.reset_counter("counter.baz")

    call = api.calls[0]
    assert call.method == "reset_counter"
    assert call.kwargs["entity_id"] == "counter.baz"


# ---------------------------------------------------------------------------
# _slugify_helper_name — HA-aligned fallback for empty slugs
# ---------------------------------------------------------------------------


def test_slugify_helper_name_fallback_for_empty_slug():
    """Cover all three branches of _slugify_helper_name.

    - Non-empty inputs that slugify to "" fall back to "unknown" (matching HA).
    - ``""`` and ``None`` inputs return ``""`` directly (no fallback).
    - Otherwise the python-slugify output is returned as-is.
    """
    assert _slugify_helper_name("%%") == "unknown"
    assert _slugify_helper_name("!!!") == "unknown"
    assert _slugify_helper_name("") == ""
    assert _slugify_helper_name(None) == ""
    assert _slugify_helper_name("Vacation Mode") == "vacation_mode"


# ---------------------------------------------------------------------------
# list_* returns isolated copies (mutation on returned list items does not
# alter the stored helper_definitions state).
# ---------------------------------------------------------------------------


async def test_list_returns_isolated_copies():
    """Mutating records returned by list_* must not affect the stored state."""
    api = _make_recording_api()
    api.helper_definitions["input_boolean"]["x"] = InputBooleanRecord(id="x", name="Original")

    returned = (await api.list_input_booleans())[0]
    returned.name = "Mutated"

    refetched = (await api.list_input_booleans())[0]
    assert refetched.name == "Original"


async def test_list_isolation_preserves_nested_collections():
    """InputSelectRecord.options must be deep-copied on list/create returns.

    Shallow ``model_copy()`` would alias ``options: list[str]`` between the
    stored record and the returned copy, so a caller appending to the
    returned record would silently corrupt harness state. Verify both the
    list_* path (pre-seeded record) and the create_* path (newly-created
    record) return isolated copies.
    """
    api = _make_recording_api()

    # --- list_* path ---
    api.helper_definitions["input_select"]["mode"] = InputSelectRecord(id="mode", name="Mode", options=["a", "b"])

    listed = (await api.list_input_selects())[0]
    listed.options.append("MUTATED")

    refetched = (await api.list_input_selects())[0]
    assert refetched.options == ["a", "b"]

    # --- create_* path ---
    created = await api.create_input_select(CreateInputSelectParams(name="Another", options=["x", "y"]))
    created.options.append("ALSO_MUTATED")

    fetched_after_create = next(r for r in await api.list_input_selects() if r.id == created.id)
    assert fetched_after_create.options == ["x", "y"]


# ---------------------------------------------------------------------------
# seed_helper — duplicate id guard and ValueError path via public API
# ---------------------------------------------------------------------------


async def test_seed_helper_rejects_duplicate_id():
    """seed_helper raises ValueError when seeding a duplicate id in the same domain."""
    async with AppTestHarness(_HarnessApp, config={}) as harness:
        harness.seed_helper(InputBooleanRecord(id="vacation_mode", name="First"))

        def _seed_duplicate() -> None:
            harness.seed_helper(InputBooleanRecord(id="vacation_mode", name="Second"))

        with pytest.raises(ValueError, match="already seeded"):
            _seed_duplicate()


async def test_harness_seed_helper_rejects_unknown_record_type():
    """seed_helper raises ValueError (not KeyError) when given an unregistered BaseModel."""

    class UnknownRecord(BaseModel):
        id: str
        name: str

    async with AppTestHarness(_HarnessApp, config={}) as harness:
        unknown = UnknownRecord(id="foo", name="Foo")

        def _seed_unknown() -> None:
            harness.seed_helper(unknown)

        with pytest.raises(ValueError, match="Unknown helper record type") as exc_info:
            _seed_unknown()

    message = str(exc_info.value)
    assert "UnknownRecord" in message
    assert "InputBooleanRecord" in message


async def test_seed_helper_isolates_caller_mutations():
    """seed_helper deep-copies the record so later caller-side mutations don't leak."""
    from hassette.models.helpers import InputSelectRecord

    async with AppTestHarness(_HarnessApp, config={}) as harness:
        caller_record = InputSelectRecord(id="mode", name="Mode", options=["a", "b"])
        harness.seed_helper(caller_record)

        # Mutate the caller-side record after seeding — scalar and nested list.
        caller_record.name = "Mutated"
        caller_record.options.append("c")

        # The harness store should be untouched.
        listed = await harness.api_recorder.list_input_selects()
        assert len(listed) == 1
        assert listed[0].name == "Mode"
        assert listed[0].options == ["a", "b"]
