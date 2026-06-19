"""Tests for Api fire-and-forget methods converted to def -> Coroutine[Any, Any, T].

Covers:
    FR#3  — await returns the same value as today (dict / ServiceResponse / None)
    FR#4  — no HassetteForgottenAwaitWarning or native coroutine warning when awaited
    FR#9  — every converted public fire-and-forget method is a plain def (not async def)
    FR#10 — forgotten await on a delegate (turn_on) emits HassetteForgottenAwaitWarning
    AC#2  — awaited method returns expected type; no warning
"""

import gc
import inspect
import warnings
from unittest.mock import AsyncMock

import pytest

from hassette.api.api import Api
from hassette.core.await_guard import RegistrationHandle
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.models.services import ServiceResponse
from tests.unit.conftest import make_api
from tests.unit.test_forgotten_await_completeness import CANONICAL_PROTECTED


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


# FR#9 — converted public methods are plain def, not async def

# Derived from the canonical single source of truth — see test_forgotten_await_completeness.py.
_CONVERTED_METHODS = sorted(CANONICAL_PROTECTED[Api])


@pytest.mark.parametrize("method_name", _CONVERTED_METHODS)
def test_converted_method_is_plain_def(method_name: str) -> None:
    """FR#9: every converted api fire-and-forget method must be a plain def, not async def."""
    method = getattr(Api, method_name)
    assert not inspect.iscoroutinefunction(method), (
        f"Api.{method_name} must be a plain def (not async def) after T04 conversion, "
        f"but inspect.iscoroutinefunction returned True."
    )


# Annotation-origin guard (AC#8) lives in tests/unit/test_forgotten_await_completeness.py::TestAnnotationOriginGuard.


# AC#2 — await returns expected values; no warnings emitted


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


# FR#3 — returned handle IS a RegistrationHandle before awaiting


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


# FR#10 — forgotten await on a primary AND a delegate emits HassetteForgottenAwaitWarning


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
