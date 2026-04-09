"""Unit tests for RecordingApi.

Tests cover:
- Write method call recording
- Read method delegation to StateProxy
- EntityNotFoundError for unseeded entities
- Assertion helpers (assert_called, assert_not_called, assert_call_count, get_calls, reset)
- NotImplementedError for unstubbed methods
- mark_ready called in on_initialize
- ApiProtocol conformance (smoke test)
- ApiCall extraction to api_call module
- StrEnum coercion for turn_on, turn_off, toggle_service
- Tailored __getattr__ messages
"""

import asyncio
import threading
from enum import StrEnum
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.conversion import STATE_REGISTRY
from hassette.core.state_proxy import StateProxy
from hassette.exceptions import EntityNotFoundError
from hassette.models.services import ServiceResponse
from hassette.test_utils import ApiCall as ApiCallFromInit
from hassette.test_utils.api_call import ApiCall
from hassette.test_utils.helpers import make_state_dict
from hassette.test_utils.recording_api import ApiProtocol, RecordingApi

# ---------------------------------------------------------------------------
# Test harness helpers
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
    # State registry used by read methods
    hassette.state_registry = STATE_REGISTRY
    return hassette


def _make_recording_api(states: dict | None = None) -> RecordingApi:
    """Create a RecordingApi with an optional pre-seeded StateProxy."""
    hassette = _make_hassette_stub()

    # Build a minimal StateProxy stub (no bus/scheduler needed for read-only use)
    state_proxy = AsyncMock(spec=StateProxy)
    state_proxy.states = states or {}
    state_proxy.is_ready = lambda: True

    api = RecordingApi(hassette, state_proxy=state_proxy)
    return api


# ---------------------------------------------------------------------------
# Subtask 1 + 3: Write method call recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_on_records_call():
    api = _make_recording_api()
    await api.turn_on("light.test", brightness=150)
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "turn_on"
    assert call.args == ("light.test",)
    assert call.kwargs == {"entity_id": "light.test", "domain": "homeassistant", "brightness": 150}


@pytest.mark.asyncio
async def test_call_service_records_target():
    api = _make_recording_api()
    await api.call_service("light", "turn_on", target={"entity_id": "light.x"})
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "call_service"
    # target should appear in kwargs
    assert call.kwargs.get("target") == {"entity_id": "light.x"}


@pytest.mark.asyncio
async def test_call_service_return_response():
    api = _make_recording_api()
    result = await api.call_service("light", "turn_on", target=None, return_response=True)
    assert result is not None
    assert isinstance(result, ServiceResponse)


@pytest.mark.asyncio
async def test_call_service_no_return_response_returns_none():
    api = _make_recording_api()
    result = await api.call_service("light", "turn_on")
    assert result is None


@pytest.mark.asyncio
async def test_set_state_signature_matches_api():
    api = _make_recording_api()
    result = await api.set_state("sensor.custom", "active", {"battery": 85})
    assert isinstance(result, dict)
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "set_state"
    # All three positional args should be present
    assert "sensor.custom" in call.args
    assert "active" in call.args


@pytest.mark.asyncio
async def test_fire_event_signature():
    api = _make_recording_api()
    result = await api.fire_event("custom_event", {"key": "value"})
    assert isinstance(result, dict)
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "fire_event"
    assert "custom_event" in call.args or call.kwargs.get("event_type") == "custom_event"


@pytest.mark.asyncio
async def test_turn_off_records_call():
    api = _make_recording_api()
    await api.turn_off("switch.fan")
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "turn_off"
    assert call.args == ("switch.fan",)
    assert call.kwargs == {"entity_id": "switch.fan", "domain": "homeassistant"}


@pytest.mark.asyncio
async def test_toggle_service_records_call():
    api = _make_recording_api()
    await api.toggle_service("light.kitchen")
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "toggle_service"
    assert call.args == ("light.kitchen",)
    assert call.kwargs == {"entity_id": "light.kitchen", "domain": "homeassistant"}


# ---------------------------------------------------------------------------
# Subtask 3: Read methods delegate to StateProxy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_state_delegates_to_state_proxy():
    state_dict = make_state_dict(
        entity_id="light.kitchen",
        state="on",
        attributes={"brightness": 200},
    )
    api = _make_recording_api(states={"light.kitchen": state_dict})

    result = await api.get_state("light.kitchen")
    assert result.entity_id == "light.kitchen"
    assert result.value == "on"


@pytest.mark.asyncio
async def test_get_state_raises_entity_not_found():
    api = _make_recording_api(states={})
    with pytest.raises(EntityNotFoundError):
        await api.get_state("light.nonexistent")


@pytest.mark.asyncio
async def test_entity_exists_true_and_false():
    state_dict = make_state_dict(entity_id="light.kitchen", state="on")
    api = _make_recording_api(states={"light.kitchen": state_dict})

    assert await api.entity_exists("light.kitchen") is True
    assert await api.entity_exists("light.missing") is False


@pytest.mark.asyncio
async def test_get_state_or_none_returns_none():
    api = _make_recording_api(states={})
    result = await api.get_state_or_none("light.nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_state_or_none_returns_state_when_seeded():
    state_dict = make_state_dict(entity_id="sensor.temp", state="22.5")
    api = _make_recording_api(states={"sensor.temp": state_dict})

    result = await api.get_state_or_none("sensor.temp")
    assert result is not None
    assert result.entity_id == "sensor.temp"


@pytest.mark.asyncio
async def test_get_states_returns_list_of_base_states():
    state_dict_1 = make_state_dict(entity_id="light.a", state="on")
    state_dict_2 = make_state_dict(entity_id="light.b", state="off")
    api = _make_recording_api(states={"light.a": state_dict_1, "light.b": state_dict_2})

    results = await api.get_states()
    assert len(results) == 2
    entity_ids = {r.entity_id for r in results}
    assert entity_ids == {"light.a", "light.b"}


@pytest.mark.asyncio
async def test_get_entity_delegates_to_state_proxy():
    state_dict = make_state_dict(entity_id="light.kitchen", state="on")
    api = _make_recording_api(states={"light.kitchen": state_dict})

    result = await api.get_entity("light.kitchen")
    assert result.entity_id == "light.kitchen"


@pytest.mark.asyncio
async def test_get_entity_raises_for_missing():
    api = _make_recording_api(states={})
    with pytest.raises(EntityNotFoundError):
        await api.get_entity("light.missing")


@pytest.mark.asyncio
async def test_get_entity_or_none_returns_none():
    api = _make_recording_api(states={})
    result = await api.get_entity_or_none("light.missing")
    assert result is None


# ---------------------------------------------------------------------------
# Subtask 3: Unstubbed methods raise NotImplementedError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unstubbed_method_raises_not_implemented():
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        await api.render_template("{{ states('sensor.temp') }}")
    assert "AppTestHarness.set_state()" in str(exc_info.value)


@pytest.mark.asyncio
async def test_unstubbed_get_history_raises():
    api = _make_recording_api()
    with pytest.raises(NotImplementedError):
        await api.get_history("sensor.temp", "2026-01-01")


# ---------------------------------------------------------------------------
# Subtask 4: Assertion helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assert_called_matching():
    api = _make_recording_api()
    await api.turn_on("light.kitchen")
    api.assert_called("turn_on", entity_id="light.kitchen")


@pytest.mark.asyncio
async def test_assert_called_with_kwargs():
    api = _make_recording_api()
    await api.turn_on("light.kitchen", brightness=150)
    api.assert_called("turn_on", entity_id="light.kitchen", brightness=150)


@pytest.mark.asyncio
async def test_assert_called_fails_when_not_called():
    api = _make_recording_api()
    with pytest.raises(AssertionError):
        api.assert_called("call_service")


@pytest.mark.asyncio
async def test_assert_called_fails_when_kwargs_do_not_match():
    api = _make_recording_api()
    await api.turn_on("light.kitchen")
    with pytest.raises(AssertionError):
        api.assert_called("turn_on", brightness=999)


@pytest.mark.asyncio
async def test_assert_called_rejects_absent_key_matching_none():
    """assert_called must distinguish 'kwarg absent' from 'kwarg=None'.

    When a kwarg key is entirely absent from the recorded call, asserting
    that key equals None must fail — not silently pass because dict.get()
    returns None for missing keys.
    """
    api = _make_recording_api()
    # Manually record a call with no 'brightness' key at all
    api.calls.append(ApiCall(method="test_method", kwargs={"entity_id": "light.x"}))
    # brightness is absent from kwargs — asserting brightness=None must fail
    with pytest.raises(AssertionError):
        api.assert_called("test_method", brightness=None)


@pytest.mark.asyncio
async def test_assert_not_called_passes_when_not_called():
    api = _make_recording_api()
    api.assert_not_called("call_service")  # should not raise


@pytest.mark.asyncio
async def test_assert_not_called_fails_when_called():
    api = _make_recording_api()
    await api.turn_on("light.kitchen")
    with pytest.raises(AssertionError):
        api.assert_not_called("turn_on")


@pytest.mark.asyncio
async def test_assert_call_count():
    api = _make_recording_api()
    await api.turn_on("light.a")
    await api.turn_on("light.b")
    api.assert_call_count("turn_on", 2)


@pytest.mark.asyncio
async def test_assert_call_count_fails_with_wrong_count():
    api = _make_recording_api()
    await api.turn_on("light.a")
    with pytest.raises(AssertionError):
        api.assert_call_count("turn_on", 2)


@pytest.mark.asyncio
async def test_get_calls_all():
    api = _make_recording_api()
    await api.turn_on("light.a")
    await api.turn_off("light.b")
    all_calls = api.get_calls()
    assert len(all_calls) == 2


@pytest.mark.asyncio
async def test_get_calls_filtered():
    api = _make_recording_api()
    await api.turn_on("light.a")
    await api.set_state("sensor.x", "active")
    # turn_on now records directly as "turn_on"; set_state is its own method
    turn_on_calls = api.get_calls("turn_on")
    assert len(turn_on_calls) == 1
    assert turn_on_calls[0].method == "turn_on"
    set_state_calls = api.get_calls("set_state")
    assert len(set_state_calls) == 1


@pytest.mark.asyncio
async def test_reset_clears_calls():
    api = _make_recording_api()
    await api.turn_on("light.a")
    await api.turn_off("light.b")
    assert len(api.calls) == 2
    api.reset()
    assert len(api.calls) == 0


# ---------------------------------------------------------------------------
# Subtask 5: mark_ready in on_initialize / lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_ready_on_initialize():
    """RecordingApi should reach RUNNING status when started."""
    api = _make_recording_api()

    # Call on_initialize directly (simulates the lifecycle hook being called)
    await api.on_initialize()
    assert api.is_ready()


# ---------------------------------------------------------------------------
# Subtask 5: ApiProtocol conformance (smoke test)
# ---------------------------------------------------------------------------


def test_protocol_conformance_smoke():
    """Verify RecordingApi can be cast to ApiProtocol without error (import-time check)."""
    # The module-level assertion fires at import time; this test confirms import succeeds
    # and the cast is valid.
    _: ApiProtocol = cast("ApiProtocol", RecordingApi)


# ---------------------------------------------------------------------------
# Subtask 3: sync attribute is a Mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_attribute_is_mock():
    api = _make_recording_api()
    assert isinstance(api.sync, Mock)


# ---------------------------------------------------------------------------
# ApiCall dataclass
# ---------------------------------------------------------------------------


def test_api_call_dataclass():
    call = ApiCall(method="turn_on", args=("light.x",), kwargs={"brightness": 100})
    assert call.method == "turn_on"
    assert call.args == ("light.x",)
    assert call.kwargs == {"brightness": 100}


# ---------------------------------------------------------------------------
# StrEnum conversion in turn_on
# ---------------------------------------------------------------------------


class _TestEntityId(StrEnum):
    KITCHEN = "light.kitchen"


@pytest.mark.asyncio
async def test_turn_on_converts_strenum_to_str():
    """turn_on converts StrEnum entity_id to str, matching real Api behavior."""
    api = _make_recording_api()
    await api.turn_on(_TestEntityId.KITCHEN)
    call = api.calls[0]
    entity_id = call.kwargs.get("entity_id")
    assert type(entity_id) is str, f"Expected plain str, got {type(entity_id).__name__} (StrEnum not converted)"
    assert entity_id == "light.kitchen"


# ---------------------------------------------------------------------------
# New tests: WP01 additions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_on_accepts_strenum():
    """turn_on stores entity_id as plain str (not StrEnum) in ApiCall.kwargs."""
    api = _make_recording_api()
    await api.turn_on(_TestEntityId.KITCHEN)
    call = api.calls[0]
    assert call.method == "turn_on"
    entity_id = call.kwargs["entity_id"]
    assert type(entity_id) is str
    assert entity_id == "light.kitchen"


@pytest.mark.asyncio
async def test_turn_off_accepts_strenum():
    """turn_off stores entity_id as plain str (not StrEnum) in ApiCall.kwargs."""
    api = _make_recording_api()
    await api.turn_off(_TestEntityId.KITCHEN)
    call = api.calls[0]
    assert call.method == "turn_off"
    entity_id = call.kwargs["entity_id"]
    assert type(entity_id) is str
    assert entity_id == "light.kitchen"


@pytest.mark.asyncio
async def test_toggle_service_accepts_strenum():
    """toggle_service stores entity_id as plain str (not StrEnum) in ApiCall.kwargs."""
    api = _make_recording_api()
    await api.toggle_service(_TestEntityId.KITCHEN)
    call = api.calls[0]
    assert call.method == "toggle_service"
    entity_id = call.kwargs["entity_id"]
    assert type(entity_id) is str
    assert entity_id == "light.kitchen"


@pytest.mark.asyncio
async def test_call_service_still_records_as_call_service():
    """call_service continues to record as method='call_service' unchanged."""
    api = _make_recording_api()
    await api.call_service("light", "turn_on", target={"entity_id": "light.x"})
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "call_service"
    assert call.kwargs["domain"] == "light"
    assert call.kwargs["service"] == "turn_on"
    assert call.kwargs["target"] == {"entity_id": "light.x"}


@pytest.mark.asyncio
async def test_getattr_tailored_message_for_state_conversion():
    """__getattr__ gives tailored message for get_state_value, get_state_value_typed, get_attribute."""
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        await api.get_state_value("sensor.temp")
    assert "Call `await self.api.get_state(entity_id)`" in str(exc_info.value)


@pytest.mark.asyncio
async def test_getattr_default_message_for_other_methods():
    """__getattr__ gives generic seed-state guidance for non-state-conversion methods."""
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        api.__getattr__("some_unimplemented_method")
    assert "Seed state via AppTestHarness.set_state()" in str(exc_info.value)


def test_apicall_import_from_api_call_module():
    """ApiCall from hassette.test_utils.api_call is the same class as hassette.test_utils.ApiCall."""
    assert ApiCall is ApiCallFromInit
