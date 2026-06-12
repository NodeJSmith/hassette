"""Tests for Bus registration methods converted to def -> Coroutine[Any, Any, T].

Covers:
    FR#3  — await returns Subscription with db_id set
    FR#4  — no HassetteForgottenAwaitWarning or native coroutine warning when awaited
    FR#9  — every public registration method is a plain def (not async def)
    FR#10 — forgotten await on a delegate emits HassetteForgottenAwaitWarning
    AC#2  — awaited method returns Subscription; no warning
            (db_id coverage: test_bus_contract.py::test_db_id_set_immediately_after_on_returns)
    AC#8  — return annotation resolves to collections.abc.Coroutine (fragment, pre-full-set)
    Source threading — ListenerIdentity.source_location populated after conversion
    Fix 1 — name=None raises ListenerNameRequiredError at call time, before awaiting
"""

import gc
import inspect
import warnings

import pytest

from hassette.bus.bus import Bus
from hassette.bus.listeners import Subscription
from hassette.core.await_guard import RegistrationHandle
from hassette.exceptions import HassetteForgottenAwaitWarning, ListenerNameRequiredError

from .conftest import mock_add_listener


async def handler(event: object) -> None:
    pass


# ---------------------------------------------------------------------------
# FR#9 — public registration methods are plain def, not async def
# ---------------------------------------------------------------------------

_PUBLIC_REGISTRATION_METHODS = [
    "on",
    "on_state_change",
    "on_attribute_change",
    "on_call_service",
    "add_listener",
    "on_service_registered",
    "on_component_loaded",
    "on_hassette_service_status",
    "on_app_state_changed",
    "on_homeassistant_restart",
    "on_homeassistant_start",
    "on_homeassistant_stop",
    "on_websocket_connected",
    "on_websocket_disconnected",
    "on_app_running",
    "on_app_stopping",
    "on_hassette_service_failed",
    "on_hassette_service_crashed",
    "on_hassette_service_started",
]


@pytest.mark.parametrize("method_name", _PUBLIC_REGISTRATION_METHODS)
def test_registration_method_is_plain_def(method_name: str) -> None:
    """FR#9: every public bus registration method must be a plain def, not async def."""
    method = getattr(Bus, method_name)
    assert not inspect.iscoroutinefunction(method), (
        f"Bus.{method_name} must be a plain def (not async def) after T02 conversion, "
        f"but inspect.iscoroutinefunction returned True."
    )


@pytest.mark.parametrize("method_name", _PUBLIC_REGISTRATION_METHODS)
def test_registration_method_return_annotation_is_coroutine(method_name: str) -> None:
    """AC#8 fragment: return annotation's __origin__ must be collections.abc.Coroutine.

    Uses get_type_hints with include_extras=False and the Bus module's globals so
    TYPE_CHECKING-guarded param annotations (HandlerType, etc.) don't block resolution
    of the *return* annotation. We only need to resolve 'return'.
    """
    import collections.abc
    import sys

    method = getattr(Bus, method_name)

    # Resolve only the return annotation — avoid resolving TYPE_CHECKING-guarded
    # param annotations that aren't available at test collection time.
    raw_annotations = getattr(method, "__annotations__", {})
    return_annotation = raw_annotations.get("return")
    assert return_annotation is not None, f"Bus.{method_name} has no return annotation"

    # If it's a string (forward ref), evaluate it in the bus module's namespace.
    if isinstance(return_annotation, str):
        bus_module = sys.modules[Bus.__module__]
        module_globals = vars(bus_module)
        try:
            return_hint = eval(return_annotation, module_globals)  # noqa: S307 — resolving module annotation
        except Exception as exc:
            raise AssertionError(
                f"Bus.{method_name} return annotation {return_annotation!r} could not be resolved: {exc}"
            ) from exc
    else:
        return_hint = return_annotation

    origin = getattr(return_hint, "__origin__", None)
    assert origin is collections.abc.Coroutine, (
        f"Bus.{method_name} return annotation __origin__ must be collections.abc.Coroutine, "
        f"got {origin!r}. Narrowing to Awaitable or a concrete type silently kills Pyright's "
        f"reportUnusedCoroutine. See design/071 AC#8."
    )


# ---------------------------------------------------------------------------
# AC#2 — await returns Subscription with db_id; no warnings emitted
# ---------------------------------------------------------------------------


async def test_await_on_returns_subscription(bus: "Bus") -> None:
    """AC#2: awaiting Bus.on() returns a Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on(topic="test.topic", handler=handler, name="await_test")
        assert isinstance(sub, Subscription)


async def test_await_on_state_change_returns_subscription(bus: "Bus") -> None:
    """AC#2 (on_state_change): await returns Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_state_change("light.kitchen", handler=handler, name="osc_test")
        assert isinstance(sub, Subscription)


async def test_await_on_attribute_change_returns_subscription(bus: "Bus") -> None:
    """AC#2 (on_attribute_change): await returns Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_attribute_change("light.kitchen", "brightness", handler=handler, name="oac_test")
        assert isinstance(sub, Subscription)


async def test_await_on_call_service_returns_subscription(bus: "Bus") -> None:
    """AC#2 (on_call_service): await returns Subscription, no warning emitted."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_call_service(handler=handler, name="ocs_test")
        assert isinstance(sub, Subscription)


async def test_await_delegate_on_homeassistant_restart(bus: "Bus") -> None:
    """AC#2 (delegate): awaiting on_homeassistant_restart returns Subscription, no warning."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_homeassistant_restart(handler=handler, name="ha_restart_test")
        assert isinstance(sub, Subscription)


async def test_await_delegate_on_app_running(bus: "Bus") -> None:
    """AC#2 (two-hop delegate): awaiting on_app_running returns Subscription, no warning."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_app_running(handler=handler, name="app_running_test")
        assert isinstance(sub, Subscription)


async def test_await_delegate_on_hassette_service_failed(bus: "Bus") -> None:
    """AC#2 (two-hop delegate): awaiting on_hassette_service_failed returns Subscription, no warning."""
    with mock_add_listener(bus):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            sub = await bus.on_hassette_service_failed(handler=handler, name="svc_failed_test")
        assert isinstance(sub, Subscription)


# ---------------------------------------------------------------------------
# FR#3 — returned handle IS a RegistrationHandle / collections.abc.Coroutine
# ---------------------------------------------------------------------------


async def test_on_returns_registration_handle(bus: "Bus") -> None:
    """FR#3: Bus.on() returns a RegistrationHandle before it is awaited."""
    with mock_add_listener(bus):
        handle = bus.on(topic="test.topic", handler=handler, name="handle_test")
        assert isinstance(handle, RegistrationHandle)
        # Protocol properties (iscoroutine, send, throw, close) covered in tests/unit/core/test_await_guard.py.
        # Close the handle to suppress HassetteForgottenAwaitWarning in the test.
        handle.close()


# ---------------------------------------------------------------------------
# FR#10 — forgotten await on a delegate also emits HassetteForgottenAwaitWarning
# ---------------------------------------------------------------------------


def test_forgotten_await_on_primary_warns(bus: "Bus") -> None:
    """FR#1 / FR#10: dropping un-awaited Bus.on() handle emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on(topic="test.topic", handler=handler, name="forgot_primary")
        del _
        gc.collect()


def test_forgotten_await_on_delegate_warns(bus: "Bus") -> None:
    """FR#10: dropping un-awaited delegate handle emits HassetteForgottenAwaitWarning."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on_homeassistant_restart(handler=handler, name="forgot_delegate")
        del _
        gc.collect()


def test_forgotten_await_on_two_hop_delegate_warns(bus: "Bus") -> None:
    """FR#10: two-hop delegate (on_app_running -> on_app_state_changed -> _subscribe) warns."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on_app_running(handler=handler, name="forgot_two_hop")
        del _
        gc.collect()


def test_forgotten_await_on_hassette_service_failed_warns(bus: "Bus") -> None:
    """FR#10: two-hop delegate on_hassette_service_failed -> on_hassette_service_status warns."""
    with mock_add_listener(bus), pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.on_hassette_service_failed(handler=handler, name="forgot_svc_failed")
        del _
        gc.collect()


# ---------------------------------------------------------------------------
# Source threading — ListenerIdentity.source_location is non-empty
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Fix 1 — name=None raises ListenerNameRequiredError at call time (not on await)
# ---------------------------------------------------------------------------


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
