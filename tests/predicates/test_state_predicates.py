# pyright: reportInvalidTypeArguments=none, reportArgumentType=none
from types import SimpleNamespace
from typing import Any

from hassette.const.misc import NOT_PROVIDED
from hassette.core.resources.bus.predicates import AttrChanged, EntityMatches, StateChanged
from hassette.core.resources.bus.predicates.event import CallServiceEventWrapper, KeyValueMatches
from hassette.core.resources.bus.predicates.state import check_from_to


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
