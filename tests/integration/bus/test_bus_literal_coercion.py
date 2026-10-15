"""Integration tests for literal coercion on ``changed_from=`` / ``changed_to=`` through real bus registration.

A bool or number literal coerces the raw Home Assistant string before comparing; a string literal compares
exactly. ``tests/unit/bus/test_literal_coercion.py`` covers the predicates directly; these tests prove the
``on_state_change`` / ``on_attribute_change`` kwargs actually route through them.
"""

from typing import TYPE_CHECKING, Any

import pytest

from hassette.testing import HassetteHarness
from tests.integration.bus.helpers import send_state_change
from tests.support.helpers import create_attr_change_event

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus

ENTITY = "switch.fan"


@pytest.mark.parametrize(
    ("kwargs", "old", "new", "should_fire"),
    [
        pytest.param({"changed_to": True}, "off", "on", True, id="to_true_off_to_on"),
        pytest.param({"changed_to": True}, "on", "off", False, id="to_true_on_to_off"),
        pytest.param({"changed_to": False}, "on", "off", True, id="to_false_on_to_off"),
        pytest.param({"changed_to": False}, "off", "on", False, id="to_false_off_to_on"),
        pytest.param({"changed_from": True}, "on", "off", True, id="from_true_on_to_off"),
        pytest.param({"changed_from": True}, "off", "on", False, id="from_true_off_to_on"),
        pytest.param({"changed_to": 20}, "19.5", "20.0", True, id="to_int_matches_decimal_string"),
        pytest.param({"changed_to": 20}, "20.0", "21.5", False, id="to_int_no_match"),
        pytest.param({"changed_to": "on"}, "off", "on", True, id="to_str_exact_match"),
        pytest.param({"changed_to": "true"}, "off", "on", False, id="to_str_not_coerced"),
        pytest.param({"changed_to": True}, "on", "unavailable", False, id="to_true_unconvertible"),
    ],
)
async def test_on_state_change_literal_kwargs(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
    kwargs: dict[str, Any],
    old: str,
    new: str,
    should_fire: bool,
) -> None:
    """Bool/number literals coerce the raw state before comparing; string literals compare exactly."""
    harness, _, bus = bus_harness
    calls: list[object] = []

    async def handler() -> None:
        calls.append(object())

    await bus.on_state_change(ENTITY, handler=handler, name="literal_state", **kwargs)
    await send_state_change(harness, ENTITY, old, new)

    assert bool(calls) is should_fire


@pytest.mark.parametrize(
    ("kwargs", "old_attr", "new_attr", "should_fire"),
    [
        pytest.param({"changed_to": 200}, "100", "200.0", True, id="to_int_matches_string_attr"),
        pytest.param({"changed_to": 200}, "200.0", "100", False, id="to_int_no_match"),
        pytest.param({"changed_from": True}, "on", "off", True, id="from_true_string_attr"),
        pytest.param({"changed_to": "200"}, "100", "200.0", False, id="to_str_not_coerced"),
    ],
)
async def test_on_attribute_change_literal_kwargs(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
    kwargs: dict[str, Any],
    old_attr: str,
    new_attr: str,
    should_fire: bool,
) -> None:
    """Literal coercion applies to attribute values the same way it applies to state values."""
    harness, hassette, bus = bus_harness
    calls: list[object] = []

    async def handler() -> None:
        calls.append(object())

    await bus.on_attribute_change("light.office", "brightness", handler=handler, name="literal_attr", **kwargs)
    await hassette.send_event(create_attr_change_event(old_attr, new_attr))
    await harness.bus_service.await_dispatch_idle()

    assert bool(calls) is should_fire
