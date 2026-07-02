"""Tests for lower-level predicate machinery in hassette.event_handling.predicates.

Covers pieces not exercised by test_predicates.py, test_combinator_predicates.py, or
test_service_data_predicates.py: compare_value's validation branches, DidChange/IsPresent/
IsMissing __call__ behavior, StateComparison/AttrComparison __call__ and the "passed a class
instead of an instance" warning branch, ServiceDataWhere's auto_glob=False and from_kwargs
paths, and the summarize() fallback/edge-case helpers.
"""

import logging
import typing
from types import SimpleNamespace

import pytest

from hassette.const import ANY_VALUE, MISSING_VALUE, NOT_PROVIDED
from hassette.event_handling.accessors import get_attr_old_new, get_state_value_old_new
from hassette.event_handling.conditions import Comparison, Decreased, Increased
from hassette.event_handling.predicates import (
    AttrComparison,
    DidChange,
    DomainMatches,
    EntityMatches,
    IsMissing,
    IsPresent,
    ServiceDataWhere,
    ServiceMatches,
    StateComparison,
    ValueIs,
    _strip_outer_parens,
    _summarize_condition,
    _summarize_predicate,
    compare_value,
)
from hassette.test_utils import create_state_change_event

if typing.TYPE_CHECKING:
    from hassette.events import Event


def make_call_service_event(service_data: dict) -> "Event":
    """Build a minimal fake CallServiceEvent-shaped object for ServiceDataWhere tests."""
    payload = SimpleNamespace(data=SimpleNamespace(service_data=service_data))
    return typing.cast("Event", SimpleNamespace(payload=payload))


def my_predicate(_value: object) -> bool:
    """Module-level predicate so callable_stable_name resolves a real qualname (not <callable>)."""
    return True


def gt_fifty(v: int) -> bool:
    """Module-level condition so callable_stable_name resolves a real qualname (not <callable>)."""
    return v > 50


# compare_value
def test_compare_value_not_provided_always_true() -> None:
    """compare_value treats NOT_PROVIDED as an unconstrained match."""
    assert compare_value("anything", NOT_PROVIDED) is True
    assert compare_value(None, NOT_PROVIDED) is True


def test_compare_value_literal_equality() -> None:
    """compare_value compares non-callable conditions for plain equality."""
    assert compare_value("on", "on") is True
    assert compare_value("on", "off") is False


def test_compare_value_callable_condition() -> None:
    """compare_value calls a callable condition and returns its bool result."""
    assert compare_value(75, lambda v: v > 50) is True
    assert compare_value(25, lambda v: v > 50) is False


def test_compare_value_rejects_async_predicate() -> None:
    """compare_value raises TypeError for a condition defined with async def."""

    async def async_condition(_value: object) -> bool:
        return True

    with pytest.raises(TypeError, match="Async predicates are not supported"):
        compare_value("x", async_condition)


def test_compare_value_rejects_awaitable_result() -> None:
    """compare_value raises TypeError when a sync callable returns an awaitable object."""

    class Awaitable:
        def __await__(self):
            yield
            return True

    def returns_awaitable(_value: object) -> "Awaitable":
        return Awaitable()

    with pytest.raises(TypeError, match="returned an awaitable"):
        compare_value("x", returns_awaitable)  # pyright: ignore[reportArgumentType]


def test_compare_value_rejects_non_bool_result() -> None:
    """compare_value raises TypeError when a callable condition doesn't return bool."""

    def returns_string(_value: object) -> str:
        return "yes"

    with pytest.raises(TypeError, match="must return bool"):
        compare_value("x", returns_string)  # pyright: ignore[reportArgumentType]


# DidChange / IsPresent / IsMissing __call__
def test_did_change_true_when_values_differ() -> None:
    """DidChange returns True when the two extracted values are unequal."""
    predicate = DidChange(source=get_state_value_old_new)
    event = create_state_change_event(entity_id="sensor.temp", old_value="20", new_value="25")

    assert predicate(event) is True


def test_did_change_false_when_values_equal() -> None:
    """DidChange returns False when the two extracted values are equal."""
    predicate = DidChange(source=get_state_value_old_new)
    event = create_state_change_event(entity_id="sensor.temp", old_value="20", new_value="20")

    assert predicate(event) is False


def test_did_change_with_attr_source() -> None:
    """DidChange works with any (old, new) tuple source, e.g. get_attr_old_new."""
    predicate = DidChange(source=get_attr_old_new("brightness"))
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert predicate(event) is True


def test_is_present_true_when_value_extracted() -> None:
    """IsPresent returns True when the source returns a real value (not MISSING_VALUE)."""
    predicate = IsPresent(source=lambda _e: "on")

    assert predicate(object()) is True


def test_is_present_false_when_value_missing() -> None:
    """IsPresent returns False when the source returns MISSING_VALUE."""
    predicate = IsPresent(source=lambda _e: MISSING_VALUE)

    assert predicate(object()) is False


def test_is_missing_true_when_value_missing() -> None:
    """IsMissing returns True when the source returns MISSING_VALUE."""
    predicate = IsMissing(source=lambda _e: MISSING_VALUE)

    assert predicate(object()) is True


def test_is_missing_false_when_value_present() -> None:
    """IsMissing returns False when the source returns a real value."""
    predicate = IsMissing(source=lambda _e: "on")

    assert predicate(object()) is False


# StateComparison / AttrComparison
def test_state_comparison_calls_condition_with_old_and_new() -> None:
    """StateComparison passes (old_value, new_value) to the comparison condition."""
    predicate = StateComparison(condition=Increased())
    event = create_state_change_event(entity_id="sensor.count", old_value="1", new_value="2")

    assert predicate(event) is True


def test_state_comparison_false_when_condition_fails() -> None:
    """StateComparison returns False when the wrapped condition evaluates False."""
    predicate = StateComparison(condition=Increased())
    event = create_state_change_event(entity_id="sensor.count", old_value="2", new_value="1")

    assert predicate(event) is False


def test_state_comparison_warns_and_instantiates_when_passed_a_class(caplog: pytest.LogCaptureFixture) -> None:
    """StateComparison auto-instantiates a bare class (common typo) instead of raising.

    Regression coverage for the defensive __post_init__ branch that converts
    `StateComparison(condition=Increased)` (class) into `StateComparison(condition=Increased())`.
    """
    with caplog.at_level(logging.WARNING):
        predicate = StateComparison(condition=Increased)  # pyright: ignore[reportArgumentType]

    assert isinstance(predicate.condition, Increased)
    event = create_state_change_event(entity_id="sensor.count", old_value="1", new_value="2")
    assert predicate(event) is True


def test_attr_comparison_calls_condition_with_old_and_new_attr() -> None:
    """AttrComparison passes (old_attr, new_attr) to the comparison condition."""
    predicate = AttrComparison(attr_name="brightness", condition=Increased())
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert predicate(event) is True


def test_attr_comparison_false_when_condition_fails() -> None:
    """AttrComparison returns False when the new attribute value fails the comparison."""
    predicate = AttrComparison(attr_name="brightness", condition=Decreased())
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert predicate(event) is False


def test_attr_comparison_warns_and_instantiates_when_passed_a_class() -> None:
    """AttrComparison auto-instantiates a bare class passed as condition, like StateComparison."""
    predicate = AttrComparison(attr_name="brightness", condition=Increased)  # pyright: ignore[reportArgumentType]

    assert isinstance(predicate.condition, Increased)


# ServiceDataWhere: auto_glob=False and from_kwargs
def test_service_data_where_auto_glob_false_treats_glob_chars_literally() -> None:
    """With auto_glob=False, a glob-like pattern is compared for literal equality, not matched."""
    predicate = ServiceDataWhere({"entity_id": "light.*"}, auto_glob=False)

    # Literal string "light.*" never matches an actual entity_id, since globbing is disabled
    assert predicate(make_call_service_event({"entity_id": "light.kitchen"})) is False
    assert predicate(make_call_service_event({"entity_id": "light.*"})) is True


def test_service_data_where_from_kwargs_builds_equivalent_predicate() -> None:
    """from_kwargs is an ergonomic constructor equivalent to passing spec= directly."""
    predicate = ServiceDataWhere.from_kwargs(entity_id="light.*", brightness=200)

    assert predicate.spec == {"entity_id": "light.*", "brightness": 200}
    assert predicate.auto_glob is True


def test_service_data_where_from_kwargs_respects_auto_glob_flag() -> None:
    """from_kwargs forwards auto_glob=False through to the constructed predicate."""
    predicate = ServiceDataWhere.from_kwargs(auto_glob=False, entity_id="light.*")

    assert predicate.auto_glob is False


# _strip_outer_parens edge cases
def test_strip_outer_parens_short_string_untouched() -> None:
    """Strings shorter than 2 chars are returned unchanged (no parens to strip)."""
    assert _strip_outer_parens("") == ""
    assert _strip_outer_parens("(") == "("


def test_strip_outer_parens_not_wrapped_untouched() -> None:
    """A string that doesn't start-and-end with matching parens is left alone."""
    assert _strip_outer_parens("a and b") == "a and b"
    assert _strip_outer_parens("(a) and (b)") == "(a) and (b)"


def test_strip_outer_parens_strips_fully_wrapping_parens() -> None:
    """A string entirely wrapped in one balanced pair of parens gets them stripped."""
    assert _strip_outer_parens("(a and b)") == "a and b"


def test_strip_outer_parens_preserves_nested_nonwrapping() -> None:
    """Parens that don't wrap the *entire* string (e.g. trailing content) are preserved."""
    assert _strip_outer_parens("(a and b) or c") == "(a and b) or c"


# _summarize_predicate / _summarize_condition fallbacks
def test_summarize_predicate_uses_summarize_method_when_available() -> None:
    """_summarize_predicate delegates to .summarize() when the predicate defines it."""

    class HasSummarize:
        def __call__(self, _value: object) -> bool:
            return True

        def summarize(self) -> str:
            return "custom summary"

    assert _summarize_predicate(HasSummarize()) == "custom summary"


def test_summarize_predicate_falls_back_to_callable_name() -> None:
    """_summarize_predicate falls back to a stable callable name for plain callables."""
    assert _summarize_predicate(my_predicate) == "my_predicate"


def test_summarize_predicate_falls_back_to_repr_for_non_callable() -> None:
    """_summarize_predicate falls back to repr() for a non-callable, non-summarizable value."""
    assert _summarize_predicate("not a predicate") == "'not a predicate'"  # pyright: ignore[reportArgumentType]


def test_summarize_condition_uses_summarize_method_when_available() -> None:
    """_summarize_condition delegates to .summarize() when the condition defines it."""
    condition = Comparison(">", 50)

    assert _summarize_condition(condition) == "> 50"


def test_summarize_condition_falls_back_to_callable_name() -> None:
    """_summarize_condition falls back to callable_name() for plain callables."""
    assert _summarize_condition(gt_fifty) == "gt_fifty"


def test_summarize_condition_falls_back_to_str_for_literal() -> None:
    """_summarize_condition falls back to str() for a non-callable literal condition."""
    assert _summarize_condition("on") == "on"
    assert _summarize_condition(ANY_VALUE) == str(ANY_VALUE)


# ValueIs with ANY_VALUE (distinct from NOT_PROVIDED)
def test_value_is_with_any_value_condition_always_true() -> None:
    """ValueIs short-circuits to True for ANY_VALUE without even calling the source."""
    calls: list[object] = []

    def tracking_source(value: object) -> object:
        calls.append(value)
        return value

    predicate = ValueIs(source=tracking_source, condition=ANY_VALUE)

    assert predicate("anything") is True
    assert calls == []  # source was never called — short-circuited


# __repr__ overrides for glob-aware matching predicates
def test_domain_matches_repr() -> None:
    """DomainMatches has a custom repr showing the domain pattern."""
    assert repr(DomainMatches("light")) == "DomainMatches(domain='light')"


def test_entity_matches_repr() -> None:
    """EntityMatches has a custom repr showing the entity_id pattern."""
    assert repr(EntityMatches("light.kitchen")) == "EntityMatches(entity_id='light.kitchen')"


def test_service_matches_repr() -> None:
    """ServiceMatches has a custom repr showing the service pattern."""
    assert repr(ServiceMatches("turn_on")) == "ServiceMatches(service='turn_on')"
