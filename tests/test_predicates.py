import asyncio
from types import SimpleNamespace
from typing import Any

from hassette.const.misc import NOT_PROVIDED
from hassette.core.resources.bus.predicates import AttrChanged, EntityMatches, Guard, StateChanged
from hassette.core.resources.bus.predicates.base import (
    AllOf,
    AnyOf,
    Not,
    ensure_iterable,
    normalize_where,
)
from hassette.core.resources.bus.predicates.event import CallServiceEventWrapper, KeyValueMatches
from hassette.core.resources.bus.predicates.state import check_from_to


async def test_allof_waits_for_all_predicates() -> None:
    """AllOf evaluates every predicate and only succeeds when all succeed."""
    event = SimpleNamespace(flag=True)

    async def async_predicate(evt: Any) -> bool:
        await asyncio.sleep(0)
        return evt.flag

    predicate = AllOf((lambda _: True, async_predicate))
    assert await predicate(event) is True


async def test_anyof_passes_when_any_predicate_matches() -> None:
    """AnyOf resolves true as soon as one predicate passes."""
    event = SimpleNamespace(value=2)
    predicate = AnyOf((lambda evt: evt.value == 2, lambda evt: evt.value == 3))
    assert await predicate(event) is True


async def test_not_inverts_predicate_result() -> None:
    """Not negates the wrapped predicate."""
    event = SimpleNamespace(active=False)
    predicate = Not(lambda evt: evt.active)
    assert await predicate(event) is True


async def test_guard_wraps_callable() -> None:
    """Guard wraps arbitrary callables and supports async evaluation."""

    async def async_checker(evt: Any) -> bool:
        await asyncio.sleep(0)
        return evt.status == "ok"

    guard = Guard(async_checker)
    event = SimpleNamespace(status="ok")
    assert await guard(event) is True


def test_normalize_where_handles_sequences() -> None:
    """normalize_where consolidates iterables into AllOf."""
    predicate = normalize_where([lambda _: True, lambda _: False])
    assert isinstance(predicate, AllOf)


def test_ensure_iterable_flattens_nested_collections() -> None:
    """ensure_iterable flattens nested AllOf/AnyOf containers."""
    nested = AllOf((lambda _: True, lambda _: True))
    flattened = list(ensure_iterable([nested, lambda _: False]))
    assert len(flattened) == 3


def _make_state_event(old_value: Any, new_value: Any) -> Any:
    def make_state(value: Any, attrs: dict[str, Any] | None = None):
        if value is NOT_PROVIDED:
            return None
        attributes = SimpleNamespace(model_dump=lambda: attrs or {})
        return SimpleNamespace(value=value, attributes=attributes)

    payload = SimpleNamespace(
        data=SimpleNamespace(
            entity_id="sensor.kitchen",
            old_state=make_state(old_value),
            new_state=make_state(new_value),
        ),
        domain="sensor",
    )
    return SimpleNamespace(payload=payload)


def test_state_changed_matches_from_to() -> None:
    """StateChanged honours from/to comparisons."""
    event = _make_state_event("off", "on")
    predicate = StateChanged(from_="off", to="on")
    assert predicate(event) is True


def test_attr_changed_detects_attribute_changes() -> None:
    """AttrChanged monitors specific attribute transitions."""
    old_state = SimpleNamespace(model_dump=lambda: {"brightness": 100})
    new_state = SimpleNamespace(model_dump=lambda: {"brightness": 200})
    payload = SimpleNamespace(
        data=SimpleNamespace(
            entity_id="light.office",
            old_state=SimpleNamespace(attributes=old_state),
            new_state=SimpleNamespace(attributes=new_state),
        )
    )
    event = SimpleNamespace(payload=payload)
    predicate = AttrChanged("brightness", from_=100, to=200)
    assert predicate(event) is True


def test_entity_matches_supports_globs() -> None:
    """EntityMatches accepts both exact and glob patterns."""
    event = _make_state_event("old", "new")
    pattern_predicate = EntityMatches("sensor.*")
    assert pattern_predicate(event) is True


def test_check_from_to_validates_combo() -> None:
    """check_from_to enforces change semantics with optional callables."""
    assert check_from_to("off", "on", "off", "on") is True
    assert check_from_to(lambda v: v < 10, lambda v: v > 10, 5, 15) is True
    assert check_from_to("off", "on", "off", "off") is False


def test_key_value_matches_supports_special_cases() -> None:
    """KeyValueMatches recognises NOT_PROVIDED, globs, and callables."""
    matcher_presence = KeyValueMatches("entity_id")
    assert matcher_presence({"entity_id": "light.office"}) is True

    matcher_glob = KeyValueMatches("entity_id", "light.*")
    assert matcher_glob({"entity_id": "light.office"}) is True

    matcher_callable = KeyValueMatches("brightness", lambda v: v > 200)
    assert matcher_callable({"brightness": 255})


def test_call_service_event_wrapper_allows_composite_predicates() -> None:
    """CallServiceEventWrapper evaluates predicates against service_data."""
    wrapper = CallServiceEventWrapper(
        (
            KeyValueMatches("entity_id", "light.*"),
            KeyValueMatches("brightness", lambda v: v >= 100),
        )
    )
    event = SimpleNamespace(
        payload=SimpleNamespace(data=SimpleNamespace(service_data={"entity_id": "light.kitchen", "brightness": 150}))
    )
    assert wrapper(event) is True
