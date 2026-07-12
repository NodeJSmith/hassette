"""Tests for Bus registration methods converted to def -> Coroutine[Any, Any, T].

Covers:
    - Awaiting returns Subscription with db_id set
    - No HassetteForgottenAwaitWarning or native coroutine warning when awaited
    - Every public registration method is a plain def (not async def)
    - Forgotten await on a delegate emits HassetteForgottenAwaitWarning
    - Awaited method returns Subscription; no warning
      (db_id coverage: test_bus_contract.py::test_db_id_set_immediately_after_on_returns)
    - ListenerIdentity.source_location populated after conversion
    - omitted name= raises TypeError at call time; name="" raises ListenerNameRequiredError, before awaiting
"""

import gc
import inspect
import warnings

import pytest

from hassette.bus.bus import Bus
from hassette.bus.listeners import Subscription
from hassette.exceptions import HassetteForgottenAwaitWarning, ListenerNameRequiredError
from hassette.utils.await_guard import RegistrationHandle
from tests.unit.test_forgotten_await_completeness import CANONICAL_PROTECTED

from .conftest import mock_add_listener

# Derived from the canonical single source of truth — see test_forgotten_await_completeness.py.
_PUBLIC_REGISTRATION_METHODS = sorted(CANONICAL_PROTECTED[Bus])


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


async def handler(event: object) -> None:
    pass


# public registration methods are plain def, not async def


@pytest.mark.parametrize("method_name", _PUBLIC_REGISTRATION_METHODS)
def test_registration_method_is_plain_def(method_name: str) -> None:
    """Every public bus registration method must be a plain def, not async def."""
    method = getattr(Bus, method_name)
    assert not inspect.iscoroutinefunction(method), (
        f"Bus.{method_name} must be a plain def (not async def) after coroutine-handle conversion, "
        f"but inspect.iscoroutinefunction returned True."
    )


# Annotation-origin guard lives in tests/unit/test_forgotten_await_completeness.py::TestAnnotationOriginGuard.


# await returns Subscription with db_id; no warnings emitted


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda b: b.on(topic="test.topic", handler=handler, name="t"), id="on"),
        pytest.param(lambda b: b.on_state_change("light.kitchen", handler=handler, name="t"), id="on_state_change"),
        pytest.param(
            lambda b: b.on_attribute_change("light.kitchen", "brightness", handler=handler, name="t"),
            id="on_attribute_change",
        ),
        pytest.param(lambda b: b.on_call_service(handler=handler, name="t"), id="on_call_service"),
        pytest.param(lambda b: b.on_homeassistant_restart(handler=handler, name="t"), id="on_homeassistant_restart"),
        pytest.param(lambda b: b.on_app_running(handler=handler, name="t"), id="on_app_running"),
        pytest.param(
            lambda b: b.on_hassette_service_failed(handler=handler, name="t"),
            id="on_hassette_service_failed",
        ),
    ],
)
async def test_await_returns_subscription(bus: "Bus", call) -> None:
    """Awaiting any registration method returns a Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await call(bus)
        assert isinstance(sub, Subscription)


# returned handle IS a RegistrationHandle / collections.abc.Coroutine


async def test_on_returns_registration_handle(bus: "Bus") -> None:
    """Bus.on() returns a RegistrationHandle before it is awaited."""
    with mock_add_listener(bus):
        handle = bus.on(topic="test.topic", handler=handler, name="handle_test")
        assert isinstance(handle, RegistrationHandle)
        # Protocol properties (iscoroutine, send, throw, close) covered in tests/unit/utils/test_await_guard.py.
        # Close the handle to suppress HassetteForgottenAwaitWarning in the test.
        handle.close()


# forgotten await on a delegate also emits HassetteForgottenAwaitWarning


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda b: b.on(topic="test.topic", handler=handler, name="t"), id="on"),
        pytest.param(lambda b: b.on_homeassistant_restart(handler=handler, name="t"), id="on_homeassistant_restart"),
        pytest.param(lambda b: b.on_app_running(handler=handler, name="t"), id="on_app_running"),
        pytest.param(
            lambda b: b.on_hassette_service_failed(handler=handler, name="t"),
            id="on_hassette_service_failed",
        ),
    ],
)
def test_forgotten_await_warns(bus: "Bus", call) -> None:
    """Dropping un-awaited handle emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = call(bus)
        del _
        gc.collect()


# Source threading — ListenerIdentity.source_location is non-empty


async def test_source_location_threaded_to_listener(bus: "Bus") -> None:
    """Source location captured in public def is populated on ListenerIdentity."""
    with mock_add_listener(bus):
        sub = await bus.on(topic="test.source", handler=handler, name="src_test")
        # source_location should be a non-empty "file:lineno" string
        assert sub.listener.identity.source_location, (
            "ListenerIdentity.source_location must be non-empty after conversion — "
            "the source capture must be threaded from the public def into _on_internal."
        )
        assert ":" in sub.listener.identity.source_location, (
            f"source_location should be 'file:lineno', got {sub.listener.identity.source_location!r}"
        )


async def test_source_location_threaded_via_on_state_change(bus: "Bus") -> None:
    """on_state_change threads source_location into _subscribe -> _on_internal -> ListenerIdentity."""
    with mock_add_listener(bus):
        sub = await bus.on_state_change("sensor.temp", handler=handler, name="src_osc")
        assert sub.listener.identity.source_location, "source_location must be non-empty"


# Fix 1 — omitted name= raises TypeError at call time; name="" raises ListenerNameRequiredError


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda bus: bus.on(topic="test.topic", handler=handler), id="on"),  # pyright: ignore[reportCallIssue]
        pytest.param(
            lambda bus: bus.on_state_change("light.kitchen", handler=handler),  # pyright: ignore[reportCallIssue]
            id="on_state_change",
        ),
        pytest.param(
            lambda bus: bus.on_attribute_change(  # pyright: ignore[reportCallIssue]
                "light.kitchen", "brightness", handler=handler
            ),
            id="on_attribute_change",
        ),
        pytest.param(
            lambda bus: bus.on_call_service(domain="light", handler=handler),  # pyright: ignore[reportCallIssue]
            id="on_call_service",
        ),
        pytest.param(
            lambda bus: bus.on_component_loaded(handler=handler),  # pyright: ignore[reportCallIssue]
            id="on_component_loaded",
        ),
        pytest.param(
            lambda bus: bus.on_service_registered(handler=handler),  # pyright: ignore[reportCallIssue]
            id="on_service_registered",
        ),
        pytest.param(
            lambda bus: bus.on_hassette_service_status(handler=handler),  # pyright: ignore[reportCallIssue]
            id="on_hassette_service_status",
        ),
        pytest.param(
            lambda bus: bus.on_app_state_changed(handler=handler),  # pyright: ignore[reportCallIssue]
            id="on_app_state_changed",
        ),
    ],
)
def test_primary_omitted_name_raises_type_error_at_call_time(bus: "Bus", call) -> None:
    """Every Shape A primary without name= raises TypeError at call time (name has no default).

    The error must be synchronous — no awaiting needed to see it, no handle is
    constructed, and no HassetteForgottenAwaitWarning leaks.
    """
    with mock_add_listener(bus), warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        with pytest.raises(TypeError):
            call(bus)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda bus: bus.on(topic="test.topic", handler=handler, name=""), id="on"),
        pytest.param(lambda bus: bus.on_state_change("light.kitchen", handler=handler, name=""), id="on_state_change"),
        pytest.param(
            lambda bus: bus.on_attribute_change("light.kitchen", "brightness", handler=handler, name=""),
            id="on_attribute_change",
        ),
        pytest.param(lambda bus: bus.on_call_service(domain="light", handler=handler, name=""), id="on_call_service"),
        pytest.param(lambda bus: bus.on_component_loaded(handler=handler, name=""), id="on_component_loaded"),
        pytest.param(lambda bus: bus.on_service_registered(handler=handler, name=""), id="on_service_registered"),
        pytest.param(
            lambda bus: bus.on_hassette_service_status(handler=handler, name=""), id="on_hassette_service_status"
        ),
        pytest.param(lambda bus: bus.on_app_state_changed(handler=handler, name=""), id="on_app_state_changed"),
    ],
)
def test_primary_empty_name_raises_listener_name_required_at_call_time(bus: "Bus", call) -> None:
    """Every Shape A primary with name="" raises ListenerNameRequiredError at call time.

    The error must be synchronous — no awaiting needed to see it, no handle is
    constructed, and no HassetteForgottenAwaitWarning leaks.
    """
    with mock_add_listener(bus), warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        with pytest.raises(ListenerNameRequiredError):
            call(bus)
