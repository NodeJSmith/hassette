"""Unit tests for _RecordingSyncFacade.

Tests verify that each write and read method on the sync facade produces the
same ApiCall shapes as the corresponding async method on RecordingApi, and
that the two sides share the same calls list.
"""

import asyncio
import inspect
import threading
import types
from enum import StrEnum
from unittest.mock import AsyncMock

import pytest

from hassette.conversion import STATE_REGISTRY
from hassette.core.state_proxy import StateProxy
from hassette.exceptions import EntityNotFoundError
from hassette.models.entities.light import LightEntity
from hassette.models.services import ServiceResponse
from hassette.test_utils.helpers import make_state_dict
from hassette.test_utils.recording_api import RecordingApi
from hassette.test_utils.sync_facade import _STUB_MSG_GENERIC, _STUB_MSG_STATE_CONVERSION, _RecordingSyncFacade

# ---------------------------------------------------------------------------
# Test harness helpers (mirroring test_recording_api.py pattern)
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


def _make_recording_api(states: dict | None = None) -> RecordingApi:
    """Create a RecordingApi with an optional pre-seeded StateProxy."""
    hassette = _make_hassette_stub()
    state_proxy = AsyncMock(spec=StateProxy)
    state_proxy.states = states or {}
    state_proxy.is_ready = lambda: True
    api = RecordingApi(hassette, state_proxy=state_proxy)
    return api


# ---------------------------------------------------------------------------
# Sanity: sync attribute is a _RecordingSyncFacade instance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_api_sync_is_recording_sync_facade():
    """RecordingApi.sync must be a _RecordingSyncFacade instance (not a Mock)."""
    api = _make_recording_api()
    assert isinstance(api.sync, _RecordingSyncFacade)


# ---------------------------------------------------------------------------
# Write method: turn_on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_turn_on_records_with_correct_shape():
    """sync.turn_on records ApiCall with correct method, args, and kwargs."""
    api = _make_recording_api()
    api.sync.turn_on("light.kitchen")
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "turn_on"
    assert call.args == ("light.kitchen",)
    assert call.kwargs == {"entity_id": "light.kitchen", "domain": "homeassistant"}


@pytest.mark.asyncio
async def test_sync_turn_on_coerces_strenum():
    """sync.turn_on coerces StrEnum entity_id to plain str in recorded kwargs."""

    class _EntityId(StrEnum):
        KITCHEN = "light.kitchen"

    api = _make_recording_api()
    api.sync.turn_on(_EntityId.KITCHEN)
    call = api.calls[0]
    entity_id = call.kwargs["entity_id"]
    assert type(entity_id) is str, f"Expected plain str, got {type(entity_id).__name__}"
    assert entity_id == "light.kitchen"


@pytest.mark.asyncio
async def test_sync_turn_on_passes_extra_data():
    """sync.turn_on passes extra kwargs through to recorded ApiCall.kwargs."""
    api = _make_recording_api()
    api.sync.turn_on("light.kitchen", brightness=200)
    call = api.calls[0]
    assert call.kwargs["brightness"] == 200
    assert call.kwargs["entity_id"] == "light.kitchen"
    assert call.kwargs["domain"] == "homeassistant"


# ---------------------------------------------------------------------------
# Write method: turn_off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_turn_off_records_with_correct_shape():
    """sync.turn_off records ApiCall with correct method, args, and kwargs."""
    api = _make_recording_api()
    api.sync.turn_off("switch.fan")
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "turn_off"
    assert call.args == ("switch.fan",)
    assert call.kwargs == {"entity_id": "switch.fan", "domain": "homeassistant"}


# ---------------------------------------------------------------------------
# Write method: toggle_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_toggle_service_records_with_correct_shape():
    """sync.toggle_service records ApiCall with correct method, args, and kwargs."""
    api = _make_recording_api()
    api.sync.toggle_service("light.kitchen")
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "toggle_service"
    assert call.args == ("light.kitchen",)
    assert call.kwargs == {"entity_id": "light.kitchen", "domain": "homeassistant"}


# ---------------------------------------------------------------------------
# Write method: call_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_call_service_records_with_correct_shape():
    """sync.call_service records ApiCall with full kwargs dict."""
    api = _make_recording_api()
    api.sync.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "call_service"
    assert call.args == ("light", "turn_on")
    assert call.kwargs == {
        "domain": "light",
        "service": "turn_on",
        "target": {"entity_id": "light.kitchen"},
        "return_response": False,
    }


@pytest.mark.asyncio
async def test_sync_call_service_returns_service_response_when_requested():
    """sync.call_service returns ServiceResponse with null context when return_response=True."""
    api = _make_recording_api()
    result = api.sync.call_service("light", "turn_on", return_response=True)
    assert isinstance(result, ServiceResponse)


@pytest.mark.asyncio
async def test_sync_call_service_returns_none_by_default():
    """sync.call_service returns None when return_response=False (default)."""
    api = _make_recording_api()
    result = api.sync.call_service("light", "turn_on")
    assert result is None


# ---------------------------------------------------------------------------
# Write method: set_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_set_state_records_and_returns_empty_dict():
    """sync.set_state records ApiCall and returns an empty dict."""
    api = _make_recording_api()
    result = api.sync.set_state("sensor.temp", "22.5")
    assert result == {}
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "set_state"
    assert call.args == ("sensor.temp", "22.5")
    assert call.kwargs == {"entity_id": "sensor.temp", "state": "22.5", "attributes": None}


# ---------------------------------------------------------------------------
# Write method: fire_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_fire_event_records_and_returns_empty_dict():
    """sync.fire_event records ApiCall and returns an empty dict."""
    api = _make_recording_api()
    result = api.sync.fire_event("custom_event", {"key": "value"})
    assert result == {}
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call.method == "fire_event"
    assert call.args == ("custom_event",)
    assert call.kwargs == {"event_type": "custom_event", "event_data": {"key": "value"}}


# ---------------------------------------------------------------------------
# Shared calls list between async and sync paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_and_async_share_calls_list():
    """Async and sync write calls append to the same api.calls list."""
    api = _make_recording_api()
    await api.turn_on("light.a")
    api.sync.turn_on("light.b")
    assert len(api.calls) == 2
    assert api.calls[0].method == "turn_on"
    assert api.calls[1].method == "turn_on"


# ---------------------------------------------------------------------------
# Read method: get_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_get_state_delegates_to_state_proxy():
    """sync.get_state returns the typed state for a seeded entity."""
    state_dict = make_state_dict(entity_id="light.kitchen", state="on", attributes={"brightness": 200})
    api = _make_recording_api(states={"light.kitchen": state_dict})
    result = api.sync.get_state("light.kitchen")
    assert result.entity_id == "light.kitchen"
    assert result.value == "on"


@pytest.mark.asyncio
async def test_sync_get_state_raises_for_unseeded():
    """sync.get_state raises EntityNotFoundError for unseeded entities."""
    api = _make_recording_api(states={})
    with pytest.raises(EntityNotFoundError):
        api.sync.get_state("light.nonexistent")


# ---------------------------------------------------------------------------
# Read method: get_states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_get_states_returns_all_seeded_entities():
    """sync.get_states returns typed states for all seeded entities."""
    state_a = make_state_dict(entity_id="light.a", state="on")
    state_b = make_state_dict(entity_id="light.b", state="off")
    api = _make_recording_api(states={"light.a": state_a, "light.b": state_b})
    results = api.sync.get_states()
    assert len(results) == 2
    entity_ids = {r.entity_id for r in results}
    assert entity_ids == {"light.a", "light.b"}


# Note: sync.get_entity / sync.get_entity_or_none require an explicit BaseEntity
# subclass model (matching the real Api signature). The "registry-converted typed
# state, no specific entity model" use case is served by sync.get_state above.


# ---------------------------------------------------------------------------
# Read method: entity_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_entity_exists_returns_bool():
    """sync.entity_exists returns True for seeded entities and False otherwise."""
    state_dict = make_state_dict(entity_id="light.kitchen", state="on")
    api = _make_recording_api(states={"light.kitchen": state_dict})
    assert api.sync.entity_exists("light.kitchen") is True
    assert api.sync.entity_exists("light.missing") is False


# ---------------------------------------------------------------------------
# Read method: get_state_or_none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_get_state_or_none_returns_none_for_unseeded():
    """sync.get_state_or_none returns None (not an exception) for unseeded entities."""
    api = _make_recording_api(states={})
    result = api.sync.get_state_or_none("light.missing")
    assert result is None


# ---------------------------------------------------------------------------
# __getattr__ fallback behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_getattr_raises_notimplementederror_with_default_message_for_unknown_method():
    """Accessing an unknown public method on sync raises NotImplementedError via __getattr__ with seed-state message.

    Marked ``@pytest.mark.asyncio`` explicitly (rather than relying on the global
    ``asyncio_mode = "auto"`` setting) so the test survives a future switch to
    ``asyncio_mode = "strict"``. The function is ``async`` because
    ``_make_hassette_stub()`` calls ``asyncio.get_running_loop()`` during
    construction, which requires an active event loop.
    """
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        api.sync.some_unknown_method()
    assert str(exc_info.value) == _STUB_MSG_GENERIC.format(name="some_unknown_method")


# ---------------------------------------------------------------------------
# F4: dict shallow-copy at record time (sync side)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_call_service_target_dict_is_shallow_copied():
    """sync.call_service records a copy of target; mutating the original does not change the recording."""
    api = _make_recording_api()
    target = {"entity_id": "light.kitchen"}
    api.sync.call_service("light", "turn_on", target=target)
    # Mutate the original dict after the call
    target["entity_id"] = "light.other"
    recorded_target = api.calls[0].kwargs["target"]
    assert recorded_target == {"entity_id": "light.kitchen"}, (
        "Recorded target was mutated — sync.call_service must shallow-copy target at record time"
    )


@pytest.mark.asyncio
async def test_sync_private_attributes_raise_attribute_error():
    """Accessing a private attribute on sync raises AttributeError, not NotImplementedError.

    Marked ``@pytest.mark.asyncio`` explicitly (rather than relying on the global
    ``asyncio_mode = "auto"`` setting) so the test survives a future switch to
    ``asyncio_mode = "strict"``. The function is ``async`` because
    ``_make_hassette_stub()`` calls ``asyncio.get_running_loop()`` during
    construction, which requires an active event loop.
    """
    api = _make_recording_api()
    with pytest.raises(AttributeError):
        _ = api.sync._something_private


# ---------------------------------------------------------------------------
# Explicit stub methods raise NotImplementedError (not AttributeError)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_get_state_value_raises_not_implemented():
    """sync.get_state_value raises NotImplementedError with tailored message."""
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        api.sync.get_state_value("sensor.temp")
    assert str(exc_info.value) == _STUB_MSG_STATE_CONVERSION.format(name="get_state_value")


@pytest.mark.asyncio
async def test_sync_get_state_value_typed_raises_not_implemented():
    """sync.get_state_value_typed raises NotImplementedError with tailored message."""
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        api.sync.get_state_value_typed("sensor.temp")
    assert str(exc_info.value) == _STUB_MSG_STATE_CONVERSION.format(name="get_state_value_typed")


@pytest.mark.asyncio
async def test_sync_get_attribute_raises_not_implemented():
    """sync.get_attribute raises NotImplementedError with tailored message."""
    api = _make_recording_api()
    with pytest.raises(NotImplementedError) as exc_info:
        api.sync.get_attribute("sensor.temp", "unit_of_measurement")
    assert str(exc_info.value) == _STUB_MSG_STATE_CONVERSION.format(name="get_attribute")


# ---------------------------------------------------------------------------
# Runtime smoke test: body-copied methods must not return coroutines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_body_copied_methods_are_sync():
    """Every body-copied method on _RecordingSyncFacade must return a plain value, not a coroutine.

    Iterates every body-copied method, invokes with stub args, and asserts the
    return value is not a CoroutineType or AsyncGeneratorType. Closes leaked
    coroutines to suppress RuntimeWarning: coroutine was never awaited.

    Body-copied methods (keep in sync with the generator's output):
    call_service, entity_exists, fire_event, get_entity, get_entity_or_none,
    get_state, get_state_or_none, get_states, set_state, toggle_service,
    turn_off, turn_on
    """
    # Seed both a sensor (for get_state-style calls) and a light (for get_entity
    # calls that require a real BaseEntity subclass).
    sensor_state = make_state_dict(entity_id="sensor.test", state="on", attributes={})
    light_state = make_state_dict(entity_id="light.test", state="on", attributes={"brightness": 200})
    api = _make_recording_api(states={"sensor.test": sensor_state, "light.test": light_state})
    facade = api.sync

    # Each entry is (method_name, positional_args, keyword_args)
    invocations: list[tuple[str, tuple, dict]] = [
        ("call_service", ("light", "turn_on"), {}),
        ("entity_exists", ("sensor.test",), {}),
        ("fire_event", ("custom_event",), {}),
        ("get_entity", ("light.test", LightEntity), {}),
        ("get_entity_or_none", ("light.test", LightEntity), {}),
        ("get_state", ("sensor.test",), {}),
        ("get_state_or_none", ("sensor.test",), {}),
        ("get_states", (), {}),
        ("set_state", ("sensor.test", "off"), {}),
        ("toggle_service", ("sensor.test",), {}),
        ("turn_off", ("sensor.test",), {}),
        ("turn_on", ("sensor.test",), {}),
    ]

    # Drift guard: the set of methods we invoke above must exactly match the set of
    # body-copied methods on the live generated class. Without this, adding a new
    # body-copied method to RecordingApi would silently escape the smoke test — giving
    # false confidence that a newly-body-copied method returning a coroutine would be
    # caught. Body-copied methods are identified by the ABSENCE of the generator's
    # standard stub template. The generator emits stubs as either
    # ``raise NotImplementedError(_STUB_MSG_GENERIC.format(...))`` or
    # ``raise NotImplementedError(_STUB_MSG_STATE_CONVERSION.format(...))``; any method
    # whose source contains neither marker has a real (body-copied) implementation.
    body_copied_on_class: set[str] = set()
    for method_name, member in inspect.getmembers(_RecordingSyncFacade, predicate=inspect.isfunction):
        if method_name.startswith("_"):
            continue
        src = inspect.getsource(member)
        if "_STUB_MSG_GENERIC" not in src and "_STUB_MSG_STATE_CONVERSION" not in src:
            body_copied_on_class.add(method_name)

    invoked_names = {name for name, _, _ in invocations}
    assert invoked_names == body_copied_on_class, (
        f"Smoke test invocation list drifted from the generated _RecordingSyncFacade class.\n"
        f"  In facade but not invoked: {sorted(body_copied_on_class - invoked_names)}\n"
        f"  Invoked but not in facade: {sorted(invoked_names - body_copied_on_class)}\n"
        f"Update `invocations` in this test to match the generator's current output."
    )

    for method_name, args, kwargs in invocations:
        method = getattr(facade, method_name)
        result = method(*args, **kwargs)
        if isinstance(result, (types.CoroutineType, types.AsyncGeneratorType)):
            if isinstance(result, types.CoroutineType):
                result.close()  # suppress "coroutine was never awaited" warning
            raise AssertionError(
                f"{method_name}() returned a {type(result).__name__} — body-copy produced hidden async call"
            )
