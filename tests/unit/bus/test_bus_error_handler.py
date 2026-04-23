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
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.bus.listeners import Subscription

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig
    from hassette.bus.bus import Bus
    from hassette.test_utils.harness import HassetteHarness


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def hassette_with_bus(
    hassette_harness: "typing.Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "typing.AsyncIterator[Hassette]":
    """Function-scoped bus harness for isolation between tests."""
    async with hassette_harness(test_config).with_bus() as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource with a mock parent that has an app_key."""
    b = hassette_with_bus._bus  # pyright: ignore[reportReturnType]
    mock_parent = Mock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.unique_name = "test_app.0"
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestApp"
    b.parent = mock_parent
    return b  # pyright: ignore[reportReturnType]


# ---------------------------------------------------------------------------
# Handler used across tests
# ---------------------------------------------------------------------------


async def _handler(event) -> None:
    pass


# ---------------------------------------------------------------------------
# Tests — Bus.on_error() method
# ---------------------------------------------------------------------------


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


@pytest.mark.asyncio
async def test_on_error_reset_on_initialize(bus: "Bus") -> None:
    """_error_handler is reset to None when on_initialize() is called."""
    mock_handler = AsyncMock()
    bus.on_error(mock_handler)
    assert bus._error_handler is mock_handler

    # Simulate re-initialization (hot-reload safety)
    await bus.on_initialize()

    assert bus._error_handler is None


# ---------------------------------------------------------------------------
# Tests — per-listener on_error= stored on Listener
# ---------------------------------------------------------------------------


def test_per_listener_on_error_stored_on_listener(bus: "Bus") -> None:
    """on_error= passed to Bus.on() is stored on listener.error_handler."""
    mock_handler = AsyncMock()
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        subscription = bus.on(
            topic="test.topic",
            handler=_handler,
            on_error=mock_handler,
        )
        assert isinstance(subscription, Subscription)
        assert subscription.listener.error_handler is mock_handler
    finally:
        bus.bus_service.add_listener = original_add


def test_listener_error_handler_default_none(bus: "Bus") -> None:
    """Listeners created without on_error= have error_handler=None."""
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        subscription = bus.on(
            topic="test.topic",
            handler=_handler,
        )
        assert subscription.listener.error_handler is None
    finally:
        bus.bus_service.add_listener = original_add


def test_on_error_raw_callable_stored_not_normalized(bus: "Bus") -> None:
    """The raw callable is stored on listener.error_handler, not a normalized wrapper."""
    mock_handler = AsyncMock()
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        subscription = bus.on(
            topic="test.topic",
            handler=_handler,
            on_error=mock_handler,
        )
        # Must be the exact same object, not a wrapper
        assert subscription.listener.error_handler is mock_handler
    finally:
        bus.bus_service.add_listener = original_add


# ---------------------------------------------------------------------------
# Tests — on_error flows through all convenience wrappers
# ---------------------------------------------------------------------------

WRAPPER_ARGS: list[tuple[str, tuple, dict]] = [
    ("on_state_change", ("light.kitchen",), {"handler": _handler}),
    ("on_attribute_change", ("sensor.battery", "battery_level"), {"handler": _handler}),
    ("on_call_service", (), {"handler": _handler}),
    ("on_homeassistant_restart", (), {"handler": _handler}),
    ("on_homeassistant_start", (), {"handler": _handler}),
    ("on_homeassistant_stop", (), {"handler": _handler}),
    ("on_websocket_connected", (), {"handler": _handler}),
    ("on_websocket_disconnected", (), {"handler": _handler}),
    ("on_app_running", (), {"handler": _handler}),
    ("on_app_stopping", (), {"handler": _handler}),
    ("on_component_loaded", (), {"handler": _handler}),
    ("on_service_registered", (), {"handler": _handler}),
    ("on_hassette_service_status", (), {"handler": _handler}),
    ("on_hassette_service_failed", (), {"handler": _handler}),
    ("on_hassette_service_crashed", (), {"handler": _handler}),
    ("on_hassette_service_started", (), {"handler": _handler}),
    ("on_app_state_changed", (), {"handler": _handler}),
]


@pytest.mark.parametrize(("wrapper_name", "args", "kwargs"), WRAPPER_ARGS, ids=[w[0] for w in WRAPPER_ARGS])
def test_on_error_in_options_flows_through_all_wrappers(
    bus: "Bus",
    wrapper_name: str,
    args: tuple,
    kwargs: dict,
) -> None:
    """on_error= passed to each convenience wrapper is stored on listener.error_handler."""
    mock_error_handler = AsyncMock()
    add_listener_mock = Mock()
    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = add_listener_mock
    try:
        wrapper = getattr(bus, wrapper_name)
        subscription = wrapper(*args, **kwargs, on_error=mock_error_handler)
        assert isinstance(subscription, Subscription), f"{wrapper_name} must return a Subscription"
        assert subscription.listener.error_handler is mock_error_handler, (
            f"{wrapper_name}: expected error_handler to be set, got {subscription.listener.error_handler!r}"
        )
    finally:
        bus.bus_service.add_listener = original_add
