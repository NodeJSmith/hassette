import typing
from types import SimpleNamespace

from hassette import predicates as P
from hassette.events import Event


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
) -> Event:
    data = SimpleNamespace(
        entity_id=entity_id,
        old_state_value=old_value,
        new_state_value=new_value,
        old_state=SimpleNamespace(attributes=_Attrs(old_attrs or {})),
        new_state=SimpleNamespace(attributes=_Attrs(new_attrs or {})),
    )
    payload = SimpleNamespace(data=data)
    return typing.cast("Event", SimpleNamespace(topic="hass.event.state_changed", payload=payload))


def test_state_did_change_detects_transitions() -> None:
    """Test that StateDidChange predicate detects when state values change."""
    predicate = P.StateDidChange()
    event = _state_event(entity_id="sensor.kitchen", old_value="off", new_value="on")
    assert predicate(event) is True


def test_state_did_change_false_when_unchanged() -> None:
    """Test that StateDidChange predicate returns False when state values are unchanged."""
    predicate = P.StateDidChange()
    event = _state_event(entity_id="sensor.kitchen", old_value="idle", new_value="idle")
    assert predicate(event) is False


def test_attr_did_change_detects_attribute_modifications() -> None:
    """Test that AttrDidChange predicate detects when specified attributes change."""
    predicate = P.AttrDidChange("brightness")
    event = _state_event(
        entity_id="light.office",
        old_value=None,
        new_value=None,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 150},
    )
    assert predicate(event) is True


def test_attr_from_to_predicates_apply_conditions() -> None:
    """Test that AttrFrom and AttrTo predicates correctly match old and new attribute values."""
    event = _state_event(
        entity_id="light.office",
        old_value=None,
        new_value=None,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 150},
    )

    attr_from = P.AttrFrom("brightness", 100)
    attr_to = P.AttrTo("brightness", 150)

    assert attr_from(event) is True
    assert attr_to(event) is True


def test_from_to_predicates_match_state_values() -> None:
    """Test that StateFrom and StateTo predicates correctly match old and new state values."""
    event = _state_event(entity_id="light.office", old_value="off", new_value="on")

    from_pred = P.StateFrom("off")
    to_pred = P.StateTo("on")

    assert from_pred(event) is True
    assert to_pred(event) is True


def test_entity_matches_supports_globs() -> None:
    """Test that EntityMatches predicate supports glob pattern matching."""
    predicate = P.EntityMatches("sensor.*")
    event = _state_event(entity_id="sensor.kitchen", old_value=None, new_value=None)
    assert predicate(event) is True


def test_entity_matches_exact_match() -> None:
    """Test that EntityMatches predicate supports exact entity ID matching."""
    predicate = P.EntityMatches("sensor.kitchen")

    # Exact match
    event = _state_event(entity_id="sensor.kitchen", old_value=None, new_value=None)
    assert predicate(event) is True

    # No match
    event = _state_event(entity_id="sensor.living", old_value=None, new_value=None)
    assert predicate(event) is False


def test_attr_did_change_false_when_unchanged() -> None:
    """Test that AttrDidChange returns False when specified attribute is unchanged."""
    predicate = P.AttrDidChange("brightness")
    event = _state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 100},
    )
    assert predicate(event) is False


def test_attr_from_to_with_callable_conditions() -> None:
    """Test that AttrFrom and AttrTo predicates work with callable conditions."""
    event = _state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    def gt_50(value: int) -> bool:
        return value > 50

    def gt_150(value: int) -> bool:
        return value > 150

    attr_from = P.AttrFrom("brightness", gt_50)
    attr_to = P.AttrTo("brightness", gt_150)

    assert attr_from(event) is True
    assert attr_to(event) is True


def test_from_to_with_callable_conditions() -> None:
    """Test that StateFrom and StateTo predicates work with callable conditions."""
    event = _state_event(entity_id="sensor.temp", old_value=20, new_value=25)

    def gt_15(value: int) -> bool:
        return value > 15

    def gt_20(value: int) -> bool:
        return value > 20

    from_pred = P.StateFrom(gt_15)
    to_pred = P.StateTo(gt_20)

    assert from_pred(event) is True
    assert to_pred(event) is True
