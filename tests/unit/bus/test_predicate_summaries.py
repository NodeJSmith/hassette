"""summarize() golden tests for every predicate type, plus the &, |, and ~ composition operators."""

from hassette.event_handling.accessors import (
    get_entity_id,
    get_state_value_new,
    get_state_value_old,
    get_state_value_old_new,
)
from hassette.event_handling.conditions import Comparison, CrossedAbove, Glob, Increased, IsIn
from hassette.event_handling.predicates import (
    AllOf,
    AnyOf,
    AttrComparison,
    AttrDidChange,
    AttrFrom,
    AttrTo,
    DidChange,
    DomainMatches,
    EntityMatches,
    Guard,
    IsMissing,
    IsPresent,
    Not,
    ServiceDataWhere,
    ServiceMatches,
    StateComparison,
    StateDidChange,
    StateFrom,
    StateTo,
    ValueIs,
    summarize_top_level,
)
from hassette.testing import (
    create_state_change_event,
)


def test_value_is_summarize_literal_condition() -> None:
    """ValueIs.summarize() returns literal condition value and source name for non-callable conditions."""
    pred = ValueIs(source=get_state_value_new, condition="on")
    result = pred.summarize()
    assert "on" in result
    assert "get_state_value_new" in result


def test_value_is_summarize_callable_condition() -> None:
    """ValueIs.summarize() returns 'custom condition from <source>' for callable conditions."""
    pred = ValueIs(source=get_state_value_new, condition=lambda v: isinstance(v, int) and v > 50)
    result = pred.summarize()
    assert result.startswith("custom condition from")
    assert "get_state_value_new" in result


def test_value_is_summarize_distinguishes_sources() -> None:
    """ValueIs with same condition but different sources produces distinct summarize() strings."""
    pred_new = ValueIs(source=get_state_value_new, condition="on")
    pred_old = ValueIs(source=get_state_value_old, condition="on")
    assert pred_new.summarize() != pred_old.summarize()


# These are stability contract tests. When summarize() output changes, these
# tests fail loudly, signalling a migration may be needed to avoid orphaning
# historical rows that rely on human_description for natural key matching.


def test_predicate_summarize_golden_entity_matches() -> None:
    assert EntityMatches("light.kitchen").summarize() == "entity light.kitchen"


def test_predicate_summarize_golden_domain_matches() -> None:
    assert DomainMatches("light").summarize() == "domain light"


def test_predicate_summarize_golden_service_matches() -> None:
    assert ServiceMatches("turn_on").summarize() == "service turn_on"


def test_predicate_summarize_golden_state_did_change() -> None:
    assert StateDidChange().summarize() == "state changed"


def test_predicate_summarize_golden_attr_did_change() -> None:
    assert AttrDidChange(attr_name="brightness").summarize() == "attr brightness changed"


def test_predicate_summarize_golden_state_to() -> None:
    assert StateTo("on").summarize() == "\u2192 on"


def test_predicate_summarize_golden_state_from() -> None:
    assert StateFrom("off").summarize() == "from off"


def test_predicate_summarize_golden_attr_to() -> None:
    assert AttrTo(attr_name="brightness", condition=255).summarize() == "attr brightness \u2192 255"


def test_predicate_summarize_golden_attr_from() -> None:
    assert AttrFrom(attr_name="brightness", condition=100).summarize() == "attr brightness from 100"


def test_predicate_summarize_golden_state_comparison() -> None:
    assert StateComparison(condition=Increased()).summarize() == "state increased"


def test_predicate_summarize_golden_state_comparison_with_comparison() -> None:
    assert StateComparison(condition=Comparison(">", 50)).summarize() == "state > 50"  # pyright: ignore[reportArgumentType]


def test_predicate_summarize_golden_state_comparison_crossed_above() -> None:
    assert StateComparison(condition=CrossedAbove(25)).summarize() == "state crossed above 25"


def test_predicate_summarize_golden_attr_comparison() -> None:
    assert AttrComparison(attr_name="brightness", condition=Increased()).summarize() == "attr brightness increased"


def test_predicate_summarize_golden_attr_comparison_with_comparison() -> None:
    pred = AttrComparison(attr_name="brightness", condition=Comparison(">=", 200))  # pyright: ignore[reportArgumentType]
    assert pred.summarize() == "attr brightness >= 200"


def test_predicate_summarize_golden_value_is_literal() -> None:
    """ValueIs with literal condition — exact format: 'value is <condition> from <source>'."""
    assert ValueIs(source=get_state_value_new, condition="on").summarize() == "value is on from get_state_value_new"


def test_predicate_summarize_golden_value_is_callable() -> None:
    """ValueIs with callable condition — exact format: 'custom condition from <source>'."""
    pred = ValueIs(source=get_state_value_new, condition=lambda v: isinstance(v, int) and v > 50)
    assert pred.summarize() == "custom condition from get_state_value_new"


def test_predicate_summarize_golden_value_is_condition_object() -> None:
    """ValueIs with a condition object — uses the condition's own summary."""
    pred = ValueIs(source=get_entity_id, condition=Glob("light.*"))
    assert pred.summarize() == "value matches light.* from get_entity_id"


def test_predicate_summarize_golden_value_is_literal_with_summarize_attr() -> None:
    """A non-callable literal with a ``summarize`` attribute renders as a literal, not as a condition object."""

    class Literal:
        summarize = "not a method"

        def __str__(self) -> str:
            return "lit"

    pred = ValueIs(source=get_entity_id, condition=Literal())
    assert pred.summarize() == "value is lit from get_entity_id"


def test_predicate_summarize_golden_guard() -> None:
    assert Guard(lambda _e: True).summarize() == "custom condition"


def test_predicate_summarize_golden_all_of() -> None:
    pred = AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))
    assert pred.summarize() == "(entity light.kitchen and \u2192 on)"


def test_predicate_summarize_golden_all_of_single() -> None:
    pred = AllOf(predicates=(StateTo("on"),))
    assert pred.summarize() == "\u2192 on"


def test_predicate_summarize_golden_any_of() -> None:
    pred = AnyOf(predicates=(StateTo("on"), StateTo("off")))
    assert pred.summarize() == "(\u2192 on or \u2192 off)"


def test_predicate_summarize_golden_any_of_single() -> None:
    pred = AnyOf(predicates=(StateTo("on"),))
    assert pred.summarize() == "\u2192 on"


def test_predicate_summarize_golden_not() -> None:
    assert Not(predicate=StateTo("on")).summarize() == "not \u2192 on"


def test_predicate_summarize_golden_is_present() -> None:
    assert IsPresent(source=get_state_value_new).summarize() == "is present"


def test_predicate_summarize_golden_is_missing() -> None:
    assert IsMissing(source=get_state_value_new).summarize() == "is missing"


def test_predicate_summarize_golden_did_change() -> None:
    assert DidChange(source=get_state_value_old_new).summarize() == "changed"


def test_predicate_summarize_golden_service_data_where() -> None:
    pred = ServiceDataWhere(spec={"entity_id": "light.kitchen"})
    assert pred.summarize() == "entity_id = light.kitchen"


def test_predicate_summarize_golden_service_data_where_callable_condition() -> None:
    """ServiceDataWhere with callable condition uses callable_name() — not memory address."""
    pred = ServiceDataWhere(spec={"brightness": lambda v: isinstance(v, int) and v > 100, "entity_id": "light.kitchen"})
    result = pred.summarize()
    assert "0x" not in result
    assert "brightness = <callable>" in result
    assert "entity_id = light.kitchen" in result


def test_predicate_summarize_golden_service_data_where_multi_key() -> None:
    pred = ServiceDataWhere(spec={"entity_id": "light.kitchen", "brightness": 255, "transition": 2})
    assert pred.summarize() == "entity_id = light.kitchen, brightness = 255, transition = 2"


def test_predicate_summarize_golden_service_data_where_with_condition_object() -> None:
    pred = ServiceDataWhere(spec={"entity_id": IsIn(["light.kitchen", "light.living"])})
    assert pred.summarize() == "entity_id = in [light.kitchen, light.living]"


def test_predicate_summarize_golden_service_data_where_with_glob() -> None:
    pred = ServiceDataWhere(spec={"entity_id": "light.*"})
    assert pred.summarize() == "entity_id = light.*"


def test_predicate_summarize_allof_realistic_combo() -> None:
    pred = AllOf(
        predicates=(
            EntityMatches("sensor.temperature"),
            StateDidChange(),
            StateTo("on"),
        )
    )
    assert pred.summarize() == "(entity sensor.temperature and state changed and → on)"


def test_predicate_summarize_anyof_many_predicates() -> None:
    pred = AnyOf(
        predicates=(
            StateTo("on"),
            StateTo("off"),
            StateTo("unavailable"),
        )
    )
    assert pred.summarize() == "(→ on or → off or → unavailable)"


def test_predicate_summarize_allof_with_state_comparison() -> None:
    pred = AllOf(
        predicates=(
            EntityMatches("zone.home"),
            StateComparison(condition=Increased()),
        )
    )
    assert pred.summarize() == "(entity zone.home and state increased)"


def test_predicate_summarize_nested_allof_containing_anyof() -> None:
    pred = AllOf(
        predicates=(
            EntityMatches("light.kitchen"),
            AnyOf(predicates=(StateTo("on"), StateTo("off"))),
        )
    )
    assert pred.summarize() == "(entity light.kitchen and (→ on or → off))"


def test_predicate_summarize_not_wrapping_allof() -> None:
    inner = AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))
    pred = Not(predicate=inner)
    assert pred.summarize() == "not (entity light.kitchen and → on)"


def test_predicate_summarize_allof_with_attr_comparison_and_condition() -> None:
    pred = AllOf(
        predicates=(
            EntityMatches("light.office"),
            AttrComparison(attr_name="brightness", condition=Comparison(">=", 200)),  # pyright: ignore[reportArgumentType]
        )
    )
    assert pred.summarize() == "(entity light.office and attr brightness >= 200)"


def test_predicate_summarize_top_level_strips_outer_parens() -> None:
    pred = AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))
    assert summarize_top_level(pred) == "entity light.kitchen and → on"


def test_predicate_summarize_top_level_preserves_inner_parens() -> None:
    pred = AllOf(
        predicates=(
            EntityMatches("light.kitchen"),
            AnyOf(predicates=(StateTo("on"), StateTo("off"))),
        )
    )
    assert summarize_top_level(pred) == "entity light.kitchen and (→ on or → off)"


def test_predicate_summarize_top_level_no_parens_passthrough() -> None:
    pred = StateTo("on")
    assert summarize_top_level(pred) == "→ on"


# Operator composition on concrete predicate types
def test_operators_on_concrete_predicates_match_explicit_combinators() -> None:
    combined = EntityMatches("light.kitchen") & StateTo("on")
    assert combined == AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))

    either = StateTo("on") | StateTo("off")
    assert either == AnyOf(predicates=(StateTo("on"), StateTo("off")))

    assert ~StateTo("on") == Not(predicate=StateTo("on"))


def test_operator_composed_predicate_evaluates() -> None:
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert (EntityMatches("light.kitchen") & StateTo("on"))(event) is True
    assert (EntityMatches("light.office") & StateTo("on"))(event) is False
    assert (EntityMatches("light.office") | StateTo("on"))(event) is True
    assert (~StateTo("on"))(event) is False


def test_operator_summarize_matches_explicit_combinators() -> None:
    assert (EntityMatches("light.kitchen") & StateTo("on")).summarize() == "(entity light.kitchen and → on)"
    assert (StateTo("on") | StateTo("off") | StateTo("unavailable")).summarize() == "(→ on or → off or → unavailable)"
    assert (~AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))).summarize() == (
        "not (entity light.kitchen and → on)"
    )
    assert summarize_top_level(EntityMatches("light.kitchen") & StateTo("on")) == "entity light.kitchen and → on"
