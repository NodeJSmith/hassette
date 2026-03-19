"""Tests for predicate summarize() methods."""

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
)


class TestGuardSummarize:
    def test_guard_summarize(self) -> None:
        pred = Guard(lambda _e: True)
        assert pred.summarize() == "custom condition"


class TestAllOfSummarize:
    def test_allof_summarize(self) -> None:
        pred = AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))
        assert pred.summarize() == "entity light.kitchen and \u2192 on"


class TestAnyOfSummarize:
    def test_anyof_summarize(self) -> None:
        pred = AnyOf(predicates=(StateTo("on"), StateTo("off")))
        assert pred.summarize() == "\u2192 on or \u2192 off"


class TestNotSummarize:
    def test_not_summarize(self) -> None:
        pred = Not(predicate=StateTo("on"))
        assert pred.summarize() == "not \u2192 on"


class TestEntityMatchesSummarize:
    def test_entity_matches_summarize(self) -> None:
        pred = EntityMatches("light.kitchen")
        assert pred.summarize() == "entity light.kitchen"


class TestStateToSummarize:
    def test_state_to_summarize(self) -> None:
        pred = StateTo("on")
        assert pred.summarize() == "\u2192 on"


class TestStateFromSummarize:
    def test_state_from_summarize(self) -> None:
        pred = StateFrom("off")
        assert pred.summarize() == "from off"


class TestStateComparisonSummarize:
    def test_state_comparison_summarize(self) -> None:
        from hassette.event_handling.conditions import Increased

        pred = StateComparison(condition=Increased())
        assert pred.summarize() == "state Increased()"


class TestDomainMatchesSummarize:
    def test_domain_matches_summarize(self) -> None:
        pred = DomainMatches("light")
        assert pred.summarize() == "domain light"


class TestServiceMatchesSummarize:
    def test_service_matches_summarize(self) -> None:
        pred = ServiceMatches("light.turn_on")
        assert pred.summarize() == "service light.turn_on"


class TestDidChangeSummarize:
    def test_did_change_summarize(self) -> None:
        from hassette.event_handling.accessors import get_state_value_old_new

        pred = DidChange(source=get_state_value_old_new)
        assert pred.summarize() == "changed"


class TestIsPresentSummarize:
    def test_is_present_summarize(self) -> None:
        from hassette.event_handling.accessors import get_state_value_new

        pred = IsPresent(source=get_state_value_new)
        assert pred.summarize() == "is present"


class TestIsMissingSummarize:
    def test_is_missing_summarize(self) -> None:
        from hassette.event_handling.accessors import get_state_value_new

        pred = IsMissing(source=get_state_value_new)
        assert pred.summarize() == "is missing"


class TestAttrFromSummarize:
    def test_attr_from_summarize(self) -> None:
        pred = AttrFrom(attr_name="brightness", condition=100)
        assert pred.summarize() == "attr brightness from 100"


class TestAttrToSummarize:
    def test_attr_to_summarize(self) -> None:
        pred = AttrTo(attr_name="brightness", condition=255)
        assert pred.summarize() == "attr brightness \u2192 255"


class TestAttrComparisonSummarize:
    def test_attr_comparison_summarize(self) -> None:
        from hassette.event_handling.conditions import Increased

        pred = AttrComparison(attr_name="brightness", condition=Increased())
        assert pred.summarize() == "attr brightness Increased()"


class TestStateDidChangeSummarize:
    def test_state_did_change_summarize(self) -> None:
        pred = StateDidChange()
        assert pred.summarize() == "state changed"


class TestAttrDidChangeSummarize:
    def test_attr_did_change_summarize(self) -> None:
        pred = AttrDidChange(attr_name="brightness")
        assert pred.summarize() == "attr brightness changed"


class TestServiceDataWhereSummarize:
    def test_service_data_where_summarize(self) -> None:
        pred = ServiceDataWhere(spec={"entity_id": "light.kitchen"})
        assert pred.summarize() == "service data where entity_id = light.kitchen"

    def test_service_data_where_multiple_fields(self) -> None:
        pred = ServiceDataWhere(spec={"entity_id": "light.kitchen", "brightness": 255})
        assert pred.summarize() == "service data where entity_id = light.kitchen, brightness = 255"


class TestValueIsSummarize:
    def test_value_is_summarize(self) -> None:
        from hassette.event_handling.accessors import get_entity_id
        from hassette.event_handling.predicates import ValueIs

        pred = ValueIs(source=get_entity_id, condition="light.kitchen")
        assert pred.summarize() == "custom condition"
