"""Tests for Api fire-and-forget methods converted to def -> Coroutine[Any, Any, T].

Covers:
    FR#3  — await returns the same value as today (dict / ServiceResponse / None)
    FR#4  — no HassetteForgottenAwaitWarning or native coroutine warning when awaited
    FR#9  — every converted public fire-and-forget method is a plain def (not async def)
    FR#10 — forgotten await on a delegate (turn_on) emits HassetteForgottenAwaitWarning
    AC#2  — awaited method returns expected type; no warning
    AC#8  — return annotation resolves to collections.abc.Coroutine (fragment, pre-full-set)
"""

import collections.abc
import gc
import inspect
import logging
import sys
import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.api.api import Api
from hassette.core.await_guard import RegistrationHandle
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.models.services import ServiceResponse

# ---------------------------------------------------------------------------
# Helpers — build a minimal Api with mocked ws layer
# ---------------------------------------------------------------------------


def make_api() -> Api:
    """Create an Api instance with mocked WebSocket and REST services.

    Stubs out:
    - ws_send_and_wait → returns {} (enough for call_service/fire_event)
    - ws_send_json     → returns None
    - post_rest_request → returns a mock response (for set_state)
    - entity_exists    → returns False (simplifies set_state test)
    """
    hassette = MagicMock()
    hassette.config.logging.api = "INFO"
    hassette.config.forgotten_await_behavior = None

    api = Api.__new__(Api)
    api.hassette = hassette
    api._unique_name = "test_api"
    api._error_handler = None
    api.logger = logging.getLogger("hassette.test.api")

    mock_parent = MagicMock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.unique_name = "test_app.0"
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestApp"
    mock_parent.app_config = MagicMock()
    mock_parent.app_config.forgotten_await_behavior = None
    api.parent = mock_parent

    # Stub the ws layer
    api.ws_send_and_wait = AsyncMock(return_value={})
    api.ws_send_json = AsyncMock(return_value=None)

    # Stub REST layer for set_state
    mock_response = AsyncMock()
    mock_response.json = AsyncMock(return_value={"state": "on", "entity_id": "light.test"})
    api.post_rest_request = AsyncMock(return_value=mock_response)
    api.entity_exists = AsyncMock(return_value=False)

    return api


# ---------------------------------------------------------------------------
# FR#9 — converted public methods are plain def, not async def
# ---------------------------------------------------------------------------

_CONVERTED_METHODS = [
    "call_service",
    "fire_event",
    "set_state",
    "turn_on",
    "turn_off",
    "toggle_service",
]


@pytest.mark.parametrize("method_name", _CONVERTED_METHODS)
def test_converted_method_is_plain_def(method_name: str) -> None:
    """FR#9: every converted api fire-and-forget method must be a plain def, not async def."""
    method = getattr(Api, method_name)
    assert not inspect.iscoroutinefunction(method), (
        f"Api.{method_name} must be a plain def (not async def) after T04 conversion, "
        f"but inspect.iscoroutinefunction returned True."
    )


@pytest.mark.parametrize("method_name", _CONVERTED_METHODS)
def test_converted_method_return_annotation_is_coroutine(method_name: str) -> None:
    """AC#8 fragment: return annotation's __origin__ must be collections.abc.Coroutine."""
    method = getattr(Api, method_name)

    raw_annotations = getattr(method, "__annotations__", {})
    return_annotation = raw_annotations.get("return")
    assert return_annotation is not None, f"Api.{method_name} has no return annotation"

    if isinstance(return_annotation, str):
        api_module = sys.modules[Api.__module__]
        module_globals = vars(api_module)
        try:
            return_hint = eval(return_annotation, module_globals)  # noqa: S307 — resolving module annotation
        except Exception as exc:
            raise AssertionError(
                f"Api.{method_name} return annotation {return_annotation!r} could not be resolved: {exc}"
            ) from exc
    else:
        return_hint = return_annotation

    origin = getattr(return_hint, "__origin__", None)
    assert origin is collections.abc.Coroutine, (
        f"Api.{method_name} return annotation __origin__ must be collections.abc.Coroutine, "
        f"got {origin!r}. Narrowing to Awaitable or a concrete type silently kills Pyright's "
        f"reportUnusedCoroutine. See design/071 AC#8."
    )


# ---------------------------------------------------------------------------
# AC#2 — await returns expected values; no warnings emitted
# ---------------------------------------------------------------------------


async def test_await_call_service_returns_none() -> None:
    """AC#2 (call_service, no return_response): await returns None, no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.call_service("light", "turn_on")
    assert result is None


async def test_await_call_service_with_return_response_returns_service_response() -> None:
    """AC#2 (call_service, return_response=True): await returns ServiceResponse, no warning."""
    api = make_api()
    # ServiceResponse(**resp) is called directly — needs a context key (all optional fields)
    api.ws_send_and_wait = AsyncMock(return_value={"context": {"id": "abc"}})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.call_service("light", "turn_on", target=None, return_response=True)
    assert isinstance(result, ServiceResponse)


async def test_await_fire_event_returns_dict() -> None:
    """AC#2 (fire_event): await returns dict, no warning."""
    api = make_api()
    response_data = {"context": {"id": "abc"}}
    api.ws_send_and_wait = AsyncMock(return_value=response_data)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.fire_event("custom_event", {"key": "value"})
    assert isinstance(result, dict)
    assert result == response_data


async def test_await_set_state_returns_dict() -> None:
    """AC#2 (set_state): await returns dict, no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.set_state("light.test", "on")
    assert isinstance(result, dict)


async def test_await_turn_on_returns_none() -> None:
    """AC#2 (turn_on, delegate): await returns None, no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.turn_on("light.kitchen")
    assert result is None


async def test_await_turn_off_returns_none() -> None:
    """AC#2 (turn_off, delegate): await returns None, no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.turn_off("light.kitchen")
    assert result is None


async def test_await_toggle_service_returns_none() -> None:
    """AC#2 (toggle_service, delegate): await returns None, no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.toggle_service("switch.fan")
    assert result is None


# ---------------------------------------------------------------------------
# FR#3 — returned handle IS a RegistrationHandle before awaiting
# ---------------------------------------------------------------------------


def test_call_service_returns_registration_handle() -> None:
    """FR#3: Api.call_service() returns a RegistrationHandle before it is awaited."""
    api = make_api()
    handle = api.call_service("light", "turn_on")
    assert isinstance(handle, RegistrationHandle)
    handle.close()


def test_fire_event_returns_registration_handle() -> None:
    """FR#3: Api.fire_event() returns a RegistrationHandle before it is awaited."""
    api = make_api()
    handle = api.fire_event("custom_event")
    assert isinstance(handle, RegistrationHandle)
    handle.close()


def test_set_state_returns_registration_handle() -> None:
    """FR#3: Api.set_state() returns a RegistrationHandle before it is awaited."""
    api = make_api()
    handle = api.set_state("light.test", "on")
    assert isinstance(handle, RegistrationHandle)
    handle.close()


def test_turn_on_returns_registration_handle() -> None:
    """FR#3: Api.turn_on() returns a RegistrationHandle before it is awaited."""
    api = make_api()
    handle = api.turn_on("light.kitchen")
    assert isinstance(handle, RegistrationHandle)
    handle.close()


def test_turn_off_returns_registration_handle() -> None:
    """FR#3: Api.turn_off() returns a RegistrationHandle before it is awaited."""
    api = make_api()
    handle = api.turn_off("light.kitchen")
    assert isinstance(handle, RegistrationHandle)
    handle.close()


def test_toggle_service_returns_registration_handle() -> None:
    """FR#3: Api.toggle_service() returns a RegistrationHandle before it is awaited."""
    api = make_api()
    handle = api.toggle_service("switch.fan")
    assert isinstance(handle, RegistrationHandle)
    handle.close()


# ---------------------------------------------------------------------------
# FR#10 — forgotten await on a primary AND a delegate emits HassetteForgottenAwaitWarning
# ---------------------------------------------------------------------------


def test_forgotten_await_on_call_service_warns() -> None:
    """FR#1 / FR#10: dropping un-awaited Api.call_service() handle emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = api.call_service("light", "turn_on")
        del _
        gc.collect()


def test_forgotten_await_on_fire_event_warns() -> None:
    """FR#10: dropping un-awaited Api.fire_event() handle emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = api.fire_event("custom_event")
        del _
        gc.collect()


def test_forgotten_await_on_set_state_warns() -> None:
    """FR#10: dropping un-awaited Api.set_state() handle emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = api.set_state("light.test", "on")
        del _
        gc.collect()


def test_forgotten_await_on_turn_on_warns() -> None:
    """FR#10: dropping un-awaited delegate Api.turn_on() emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = api.turn_on("light.kitchen")
        del _
        gc.collect()


def test_forgotten_await_on_turn_off_warns() -> None:
    """FR#10: dropping un-awaited delegate Api.turn_off() emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = api.turn_off("light.kitchen")
        del _
        gc.collect()


def test_forgotten_await_on_toggle_service_warns() -> None:
    """FR#10: dropping un-awaited delegate Api.toggle_service() emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = api.toggle_service("switch.fan")
        del _
        gc.collect()
