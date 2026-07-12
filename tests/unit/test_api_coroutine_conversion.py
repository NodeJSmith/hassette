"""Tests for Api fire-and-forget methods converted to def -> Coroutine[Any, Any, T].

Covers:
    - Await returns the same value as before conversion (dict / ServiceResponse / None)
    - No HassetteForgottenAwaitWarning or native coroutine warning when awaited
    - Every converted public fire-and-forget method is a plain def (not async def)
    - Forgotten await on a delegate (turn_on) emits HassetteForgottenAwaitWarning
    - Awaited method returns expected type; no warning
"""

import gc
import inspect
import warnings
from unittest.mock import AsyncMock

import pytest

from hassette.api.api import Api
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.models.services import ServiceResponse
from hassette.utils.await_guard import RegistrationHandle
from tests.unit.conftest import make_api
from tests.unit.test_forgotten_await_completeness import CANONICAL_PROTECTED

# Derived from the canonical single source of truth — see test_forgotten_await_completeness.py.
_CONVERTED_METHODS = sorted(CANONICAL_PROTECTED[Api])
_API_METHODS = [
    pytest.param(lambda a: a.call_service("light", "turn_on"), id="call_service"),
    pytest.param(lambda a: a.fire_event("custom_event"), id="fire_event"),
    pytest.param(lambda a: a.set_state("light.test", "on"), id="set_state"),
    pytest.param(lambda a: a.turn_on("light.kitchen"), id="turn_on"),
    pytest.param(lambda a: a.turn_off("light.kitchen"), id="turn_off"),
    pytest.param(lambda a: a.toggle_service("switch.fan"), id="toggle_service"),
]


@pytest.fixture(autouse=True)
def drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


# Converted public methods are plain def, not async def


@pytest.mark.parametrize("method_name", _CONVERTED_METHODS)
def test_converted_method_is_plain_def(method_name: str) -> None:
    """Every converted api fire-and-forget method must be a plain def, not async def."""
    method = getattr(Api, method_name)
    assert not inspect.iscoroutinefunction(method), (
        f"Api.{method_name} must be a plain def (not async def) after conversion, "
        f"but inspect.iscoroutinefunction returned True."
    )


# Annotation-origin guard lives in tests/unit/test_forgotten_await_completeness.py::TestAnnotationOriginGuard.


# Awaiting returns expected values; no warnings emitted


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda a: a.call_service("light", "turn_on"), id="call_service"),
        pytest.param(lambda a: a.turn_on("light.kitchen"), id="turn_on"),
        pytest.param(lambda a: a.turn_off("light.kitchen"), id="turn_off"),
        pytest.param(lambda a: a.toggle_service("switch.fan"), id="toggle_service"),
    ],
)
async def test_await_returns_none(call) -> None:
    """Awaiting methods that return None emits no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await call(api)
    assert result is None


async def test_await_call_service_with_return_response_returns_service_response() -> None:
    """Awaiting call_service() with return_response=True returns ServiceResponse, no warning."""
    api = make_api()
    # ServiceResponse(**resp) is called directly — needs a context key (all optional fields)
    api.ws_send_and_wait = AsyncMock(return_value={"context": {"id": "abc"}})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.call_service("light", "turn_on", target=None, return_response=True)
    assert isinstance(result, ServiceResponse)


async def test_await_fire_event_returns_dict() -> None:
    """Awaiting fire_event() returns a dict, no warning."""
    api = make_api()
    response_data = {"context": {"id": "abc"}}
    api.ws_send_and_wait = AsyncMock(return_value=response_data)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.fire_event("custom_event", {"key": "value"})
    assert isinstance(result, dict)
    assert result == response_data


async def test_await_set_state_returns_dict() -> None:
    """Awaiting set_state() returns a dict, no warning."""
    api = make_api()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = await api.set_state("light.test", "on")
    assert isinstance(result, dict)


# Returned handle is a RegistrationHandle before awaiting


@pytest.mark.parametrize("call", _API_METHODS)
def test_returns_registration_handle(call) -> None:
    """Api methods return a RegistrationHandle before awaiting."""
    api = make_api()
    handle = call(api)
    assert isinstance(handle, RegistrationHandle)
    handle.close()


# Forgotten await on a primary AND a delegate emits HassetteForgottenAwaitWarning


@pytest.mark.parametrize("call", _API_METHODS)
def test_forgotten_await_warns(call) -> None:
    """Dropping un-awaited Api handle emits HassetteForgottenAwaitWarning."""
    api = make_api()
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = call(api)
        del _
        gc.collect()
