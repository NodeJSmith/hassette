from types import SimpleNamespace

from hassette.const.misc import NOT_PROVIDED
from hassette.core.resources.bus.predicates import AllOf, AnyOf, Guard, Not
from hassette.core.resources.bus.predicates.utils import compare_value, ensure_tuple, normalize_where


def test_allof_requires_all_predicates_true() -> None:
    predicate = AllOf((lambda _: True, lambda _: True))
    assert predicate(SimpleNamespace()) is True


def test_allof_returns_false_when_any_predicate_fails() -> None:
    predicate = AllOf((lambda _: True, lambda _: False))
    assert predicate(SimpleNamespace()) is False


def test_anyof_succeeds_when_any_predicate_matches() -> None:
    predicate = AnyOf((lambda _: False, lambda _: True))
    assert predicate(SimpleNamespace()) is True


def test_anyof_returns_false_when_all_predicates_fail() -> None:
    predicate = AnyOf((lambda _: False, lambda _: False))
    assert predicate(SimpleNamespace()) is False


def test_not_inverts_predicate_result() -> None:
    predicate = Not(lambda _: True)
    assert predicate(SimpleNamespace()) is False


def test_guard_wraps_callable_and_executes_it() -> None:
    sentinel = object()
    guard = Guard(lambda event: event is sentinel)
    assert guard(sentinel) is True
    assert guard(object()) is False


def test_normalize_where_returns_allof_for_sequences() -> None:
    predicate = normalize_where([lambda _: True, lambda _: True])
    assert isinstance(predicate, AllOf)


def test_normalize_where_returns_single_predicate() -> None:
    def single() -> bool:
        return True

    predicate = normalize_where(single)
    assert predicate is single


def test_ensure_tuple_flattens_nested_sequences() -> None:
    predicates = ensure_tuple([lambda _: True, (lambda _: False, lambda _: True)])
    assert len(predicates) == 3


def test_compare_value_supports_membership_for_lists() -> None:
    assert compare_value("light.kitchen", ["light.kitchen", "light.hall"]) is True
    assert compare_value("light.kitchen", ["light.lounge"]) is False


def test_compare_value_allows_not_provided_sentinel() -> None:
    assert compare_value(NOT_PROVIDED, "anything") is True
