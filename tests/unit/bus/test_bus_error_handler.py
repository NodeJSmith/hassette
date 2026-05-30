"""Unit tests for Bus error handler registration.

Tests:
- Bus.on_error() stores handler on _error_handler
- _error_handler is reset on_initialize() (not __init__)
- on_error= in Options flows through all convenience wrappers
- Per-listener on_error= stored on Listener.error_handler
- Listener.error_handler defaults to None
- on_error() replaces a previously registered handler
"""

import typing
from unittest.mock import AsyncMock

import pytest

from hassette.bus.listeners import Subscription

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus


async def handler(event) -> None:
    pass


def test_on_error_stores_handler(bus: "Bus") -> None:
    """Bus.on_error(handler) stores the handler on _error_handler."""
    mock_handler = AsyncMock()
    bus.on_error(mock_handler)
    assert bus._error_handler is mock_handler


def test_on_error_replaces_previous_handler(bus: "Bus") -> None:
    """Bus.on_error() replaces any previously registered handler."""
    first_handler = AsyncMock()
    second_handler = AsyncMock()
    bus.on_error(first_handler)
    bus.on_error(second_handler)
    assert bus._error_handler is second_handler
    assert bus._error_handler is not first_handler


async def test_on_error_reset_on_initialize(bus: "Bus") -> None:
    """_error_handler is reset to None when on_initialize() is called."""
    mock_handler = AsyncMock()
    bus.on_error(mock_handler)
    assert bus._error_handler is mock_handler

    await bus.on_initialize()

    assert bus._error_handler is None


async def test_per_listener_on_error_stored_on_listener(bus: "Bus") -> None:
    """on_error= passed to Bus.on() is stored on listener.error_handler."""
    mock_handler = AsyncMock()
    with mock_add_listener(bus):
        subscription = await bus.on(topic="test.topic", handler=handler, on_error=mock_handler, name="err_test")
        assert isinstance(subscription, Subscription)
        assert subscription.listener.invoker.error_handler is mock_handler


async def test_listener_error_handler_default_none(bus: "Bus") -> None:
    """Listeners created without on_error= have error_handler=None."""
    with mock_add_listener(bus):
        subscription = await bus.on(topic="test.topic", handler=handler, name="no_err_test")
        assert subscription.listener.invoker.error_handler is None


async def test_on_error_raw_callable_stored_not_normalized(bus: "Bus") -> None:
    """The raw callable is stored on listener.error_handler, not a normalized wrapper."""
    mock_handler = AsyncMock()
    with mock_add_listener(bus):
        subscription = await bus.on(topic="test.topic", handler=handler, on_error=mock_handler, name="raw_err_test")
        assert subscription.listener.invoker.error_handler is mock_handler


WRAPPER_ARGS: list[tuple[str, tuple, dict]] = [
    ("on_state_change", ("light.kitchen",), {"handler": handler, "name": "kitchen_light"}),
    ("on_attribute_change", ("sensor.battery", "battery_level"), {"handler": handler, "name": "battery_attr"}),
    ("on_call_service", (), {"handler": handler, "name": "svc_call"}),
    ("on_homeassistant_restart", (), {"handler": handler, "name": "ha_restart"}),
    ("on_homeassistant_start", (), {"handler": handler, "name": "ha_start"}),
    ("on_homeassistant_stop", (), {"handler": handler, "name": "ha_stop"}),
    ("on_websocket_connected", (), {"handler": handler, "name": "ws_conn"}),
    ("on_websocket_disconnected", (), {"handler": handler, "name": "ws_disc"}),
    ("on_app_running", (), {"handler": handler, "name": "app_run"}),
    ("on_app_stopping", (), {"handler": handler, "name": "app_stop"}),
    ("on_component_loaded", (), {"handler": handler, "name": "comp_load"}),
    ("on_service_registered", (), {"handler": handler, "name": "svc_reg"}),
    ("on_hassette_service_status", (), {"handler": handler, "name": "svc_status"}),
    ("on_hassette_service_failed", (), {"handler": handler, "name": "svc_fail"}),
    ("on_hassette_service_crashed", (), {"handler": handler, "name": "svc_crash"}),
    ("on_hassette_service_started", (), {"handler": handler, "name": "svc_start"}),
    ("on_app_state_changed", (), {"handler": handler, "name": "app_state"}),
]


@pytest.mark.parametrize(("wrapper_name", "args", "kwargs"), WRAPPER_ARGS, ids=[w[0] for w in WRAPPER_ARGS])
async def test_on_error_in_options_flows_through_all_wrappers(
    bus: "Bus",
    wrapper_name: str,
    args: tuple,
    kwargs: dict,
) -> None:
    """on_error= passed to each convenience wrapper is stored on listener.error_handler."""
    mock_error_handler = AsyncMock()
    with mock_add_listener(bus):
        wrapper = getattr(bus, wrapper_name)
        subscription = await wrapper(*args, **kwargs, on_error=mock_error_handler)
        assert isinstance(subscription, Subscription), f"{wrapper_name} must return a Subscription"
        assert subscription.listener.invoker.error_handler is mock_error_handler, (
            f"{wrapper_name}: expected error_handler to be set, got {subscription.listener.invoker.error_handler!r}"
        )
