import typing
from types import SimpleNamespace

from hassette.const.misc import NOT_PROVIDED
from hassette.core.resources.bus.predicates import ServiceDataWhere


def _make_event(service_data: dict[str, typing.Any]) -> SimpleNamespace:
    payload = SimpleNamespace(data=SimpleNamespace(service_data=service_data))
    return SimpleNamespace(payload=payload)


def test_service_data_where_matches_list_values() -> None:
    predicate = ServiceDataWhere({"entity_id": "light.kitchen"})

    matching_event = _make_event({"entity_id": ["light.kitchen"]})
    non_matching_event = _make_event({"entity_id": ["light.other"]})

    assert predicate(matching_event) is True
    assert predicate(non_matching_event) is False


def test_service_data_where_not_provided_requires_presence() -> None:
    predicate = ServiceDataWhere({"required": NOT_PROVIDED})

    assert predicate(_make_event({"required": 0})) is True
    assert predicate(_make_event({})) is False


def test_service_data_where_typing_any_requires_presence() -> None:
    predicate = ServiceDataWhere({"required": NOT_PROVIDED})

    assert predicate(_make_event({"required": "value"})) is True
    assert predicate(_make_event({})) is False
