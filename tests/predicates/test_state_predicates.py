from types import SimpleNamespace

from hassette.core.resources.bus.predicates import (
    AttrDidChange,
    AttrFrom,
    AttrTo,
    EntityMatches,
    From,
    StateDidChange,
    To,
)


class _Attrs:
    def __init__(self, values: dict[str, object]):
        self._values = values

    def model_dump(self) -> dict[str, object]:
        return self._values


def _state_event(
    *,
    entity_id: str,
    old_value: object,
    new_value: object,
    old_attrs: dict[str, object] | None = None,
    new_attrs: dict[str, object] | None = None,
) -> SimpleNamespace:
    data = SimpleNamespace(
        entity_id=entity_id,
        old_state_value=old_value,
        new_state_value=new_value,
        old_state=SimpleNamespace(attributes=_Attrs(old_attrs or {})),
        new_state=SimpleNamespace(attributes=_Attrs(new_attrs or {})),
    )
    payload = SimpleNamespace(data=data)
    return SimpleNamespace(topic="hass.event.state_changed", payload=payload)


def test_state_did_change_detects_transitions() -> None:
    predicate = StateDidChange()
    event = _state_event(entity_id="sensor.kitchen", old_value="off", new_value="on")
    assert predicate(event) is True


def test_state_did_change_false_when_unchanged() -> None:
    predicate = StateDidChange()
    event = _state_event(entity_id="sensor.kitchen", old_value="idle", new_value="idle")
    assert predicate(event) is False


def test_attr_did_change_detects_attribute_modifications() -> None:
    predicate = AttrDidChange("brightness")
    event = _state_event(
        entity_id="light.office",
        old_value=None,
        new_value=None,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 150},
    )
    assert predicate(event) is True


def test_attr_from_to_predicates_apply_conditions() -> None:
    event = _state_event(
        entity_id="light.office",
        old_value=None,
        new_value=None,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 150},
    )

    attr_from = AttrFrom("brightness", 100)
    attr_to = AttrTo("brightness", 150)

    assert attr_from(event) is True
    assert attr_to(event) is True


def test_from_to_predicates_match_state_values() -> None:
    event = _state_event(entity_id="light.office", old_value="off", new_value="on")

    from_pred = From("off")
    to_pred = To("on")

    assert from_pred(event) is True
    assert to_pred(event) is True


def test_entity_matches_supports_globs() -> None:
    predicate = EntityMatches("sensor.*")
    event = _state_event(entity_id="sensor.kitchen", old_value=None, new_value=None)
    assert predicate(event) is True
