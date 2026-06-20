"""Tests for Bus registration methods converted to def -> Coroutine[Any, Any, T].

Covers:
    - Awaiting returns Subscription with db_id set
    - No HassetteForgottenAwaitWarning or native coroutine warning when awaited
    - Every public registration method is a plain def (not async def)
    - Forgotten await on a delegate emits HassetteForgottenAwaitWarning
    - Awaited method returns Subscription; no warning
      (db_id coverage: test_bus_contract.py::test_db_id_set_immediately_after_on_returns)
    - ListenerIdentity.source_location populated after conversion
    - name=None raises ListenerNameRequiredError at call time, before awaiting
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


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


async def handler(event: object) -> None:
    pass


# public registration methods are plain def, not async def

# Derived from the canonical single source of truth — see test_forgotten_await_completeness.py.
_PUBLIC_REGISTRATION_METHODS = sorted(CANONICAL_PROTECTED[Bus])


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


async def test_await_on_returns_subscription(bus: "Bus") -> None:
    """Awaiting Bus.on() returns a Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on(topic="test.topic", handler=handler, name="await_test")
        assert isinstance(sub, Subscription)


async def test_await_on_state_change_returns_subscription(bus: "Bus") -> None:
    """on_state_change: await returns Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_state_change("light.kitchen", handler=handler, name="osc_test")
        assert isinstance(sub, Subscription)


async def test_await_on_attribute_change_returns_subscription(bus: "Bus") -> None:
    """on_attribute_change: await returns Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_attribute_change("light.kitchen", "brightness", handler=handler, name="oac_test")
        assert isinstance(sub, Subscription)


async def test_await_on_call_service_returns_subscription(bus: "Bus") -> None:
    """on_call_service: await returns Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_call_service(handler=handler, name="ocs_test")
        assert isinstance(sub, Subscription)


async def test_await_delegate_on_homeassistant_restart(bus: "Bus") -> None:
    """Awaiting on_homeassistant_restart returns Subscription, no warning."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_homeassistant_restart(handler=handler, name="ha_restart_test")
        assert isinstance(sub, Subscription)


async def test_await_delegate_on_app_running(bus: "Bus") -> None:
    """Awaiting on_app_running returns Subscription, no warning."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_app_running(handler=handler, name="app_running_test")
        assert isinstance(sub, Subscription)


async def test_await_delegate_on_hassette_service_failed(bus: "Bus") -> None:
    """Awaiting on_hassette_service_failed returns Subscription, no warning."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_hassette_service_failed(handler=handler, name="svc_failed_test")
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


def test_forgotten_await_on_primary_warns(bus: "Bus") -> None:
    """Dropping un-awaited Bus.on() handle emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning, match="Coroutine from 'on' was"):
        _ = bus.on(topic="test.topic", handler=handler, name="forgot_primary")
        del _
        gc.collect()


def test_forgotten_await_on_delegate_warns(bus: "Bus") -> None:
    """Dropping un-awaited delegate handle emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on_homeassistant_restart(handler=handler, name="forgot_delegate")
        del _
        gc.collect()


def test_forgotten_await_on_two_hop_delegate_warns(bus: "Bus") -> None:
    """Two-hop delegate (on_app_running -> on_app_state_changed -> _subscribe) emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on_app_running(handler=handler, name="forgot_two_hop")
        del _
        gc.collect()


def test_forgotten_await_on_hassette_service_failed_warns(bus: "Bus") -> None:
    """Two-hop delegate on_hassette_service_failed -> on_hassette_service_status emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on_hassette_service_failed(handler=handler, name="forgot_svc_failed")
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


# Fix 1 — name=None raises ListenerNameRequiredError at call time (not on await)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda bus: bus.on(topic="test.topic", handler=handler), id="on"),
        pytest.param(lambda bus: bus.on_state_change("light.kitchen", handler=handler), id="on_state_change"),
        pytest.param(
            lambda bus: bus.on_attribute_change("light.kitchen", "brightness", handler=handler),
            id="on_attribute_change",
        ),
        pytest.param(lambda bus: bus.on_call_service(domain="light", handler=handler), id="on_call_service"),
        pytest.param(lambda bus: bus.on_component_loaded(handler=handler), id="on_component_loaded"),
        pytest.param(lambda bus: bus.on_service_registered(handler=handler), id="on_service_registered"),
        pytest.param(lambda bus: bus.on_hassette_service_status(handler=handler), id="on_hassette_service_status"),
        pytest.param(lambda bus: bus.on_app_state_changed(handler=handler), id="on_app_state_changed"),
    ],
)
def test_primary_missing_name_raises_at_call_time(bus: "Bus", call) -> None:
    """Every Shape A primary without name= raises ListenerNameRequiredError at call time.

    The error must be synchronous — no awaiting needed to see it, no handle is
    constructed, and no HassetteForgottenAwaitWarning leaks.
    """
    with mock_add_listener(bus), warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        with pytest.raises(ListenerNameRequiredError):
            call(bus)
