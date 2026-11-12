"""Registration methods put their selection filters in ``scope`` and the caller's in ``predicate`` (spec 151 D1, D2).

Only a rejection by a ``predicate`` filter is a near-miss, so these pin which side each filter lands on.
"""

import logging
import typing

import pytest

from hassette.event_handling import predicates as P
from hassette.testing import create_state_change_event
from tests.support.helpers import create_attr_change_event

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus


async def handler() -> None:
    pass


def scope_types(listener: typing.Any) -> list[type]:
    return [type(pred) for pred in (listener.scope.predicates if listener.scope is not None else ())]


def filter_types(listener: typing.Any) -> list[type]:
    return [type(pred) for pred in listener.filters]


async def test_state_change_default_change_filter_is_scope(bus: "Bus") -> None:
    sub = await bus.on_state_change("light.kitchen", handler=handler, changed_to="on", name="default_changed")

    assert scope_types(sub.listener) == [P.EntityMatches, P.StateDidChange]
    assert filter_types(sub.listener) == [P.StateTo]


async def test_state_change_default_still_filters_unchanged_states(bus: "Bus") -> None:
    sub = await bus.on_state_change("light.kitchen", handler=handler, name="default_still_filters")

    assert not sub.listener.matches(create_state_change_event(entity_id="light.kitchen", old_value="on", new_value="on"))
    assert sub.listener.matches(create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on"))


async def test_state_change_explicit_changed_true_is_a_filter(bus: "Bus") -> None:
    sub = await bus.on_state_change("light.kitchen", handler=handler, changed=True, name="explicit_changed")

    assert scope_types(sub.listener) == [P.EntityMatches]
    assert filter_types(sub.listener) == [P.StateDidChange]


async def test_state_change_comparison_is_a_filter(bus: "Bus") -> None:
    sub = await bus.on_state_change(
        "sensor.temp", handler=handler, changed=lambda old, new: new > old, name="comparison_changed"
    )

    assert scope_types(sub.listener) == [P.EntityMatches]
    assert filter_types(sub.listener) == [P.StateComparison]


async def test_state_change_changed_false_has_no_change_filter(bus: "Bus") -> None:
    sub = await bus.on_state_change("light.kitchen", handler=handler, changed=False, name="no_change_filter")

    assert scope_types(sub.listener) == [P.EntityMatches]
    assert filter_types(sub.listener) == []


async def test_where_children_are_separate_filters(bus: "Bus") -> None:
    sub = await bus.on_state_change(
        "light.kitchen",
        handler=handler,
        changed_from="off",
        where=[P.EntityMatches("light.kitchen"), P.StateTo("on")],
        name="where_children",
    )

    assert filter_types(sub.listener) == [P.StateFrom, P.EntityMatches, P.StateTo]


async def test_attribute_change_default_is_scope_and_does_not_warn(
    bus: "Bus", caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        sub = await bus.on_attribute_change("light.office", "brightness", handler=handler, name="attr_default")

    assert scope_types(sub.listener) == [P.EntityMatches, P.AttrDidChange]
    assert filter_types(sub.listener) == []
    assert "changed=False" not in caplog.text
    assert not sub.listener.matches(create_attr_change_event(old_attr_value=10, new_attr_value=10))
    assert sub.listener.matches(create_attr_change_event(old_attr_value=10, new_attr_value=20))


async def test_attribute_change_explicit_changed_false_still_warns(
    bus: "Bus", caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        await bus.on_attribute_change("light.office", "brightness", handler=handler, changed=False, name="attr_false")

    assert "changed=False" in caplog.text


async def test_call_service_domain_and_service_are_scope(bus: "Bus") -> None:
    sub = await bus.on_call_service(
        "light", "turn_on", handler=handler, where={"entity_id": "light.kitchen"}, name="call_service_scope"
    )

    assert scope_types(sub.listener) == [P.DomainMatches, P.ServiceMatches]
    assert filter_types(sub.listener) == [P.ServiceDataWhere]


async def test_on_topic_has_no_scope(bus: "Bus") -> None:
    sub = await bus.on(topic="custom.topic", handler=handler, where=P.StateTo("on"), name="raw_on")

    assert sub.listener.scope is None
    assert filter_types(sub.listener) == [P.StateTo]


async def test_registered_description_covers_scope_and_filters(bus: "Bus") -> None:
    sub = await bus.on_state_change("light.kitchen", handler=handler, changed_to="on", name="description")
    registration = bus.bus_service.build_registration(sub.listener)

    assert registration.human_description is not None
    assert "light.kitchen" in registration.human_description
    assert "on" in registration.human_description
