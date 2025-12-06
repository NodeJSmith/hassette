"""Tests for dependency injection extractors and type annotation handling."""

import inspect
from collections import defaultdict
from decimal import Decimal
from types import NoneType
from typing import Annotated, Any

import pytest
from whenever import Time, ZonedDateTime

from hassette import MISSING_VALUE
from hassette import dependencies as D
from hassette.bus.listeners import convert_params
from hassette.context import get_state_registry
from hassette.dependencies.extraction import (
    extract_from_annotated,
    extract_from_event_type,
    extract_from_signature,
    has_dependency_injection,
    is_annotated_type,
    is_event_type,
    validate_di_signature,
)
from hassette.events import CallServiceEvent, Event, RawStateChangeEvent, TypedStateChangeEvent
from hassette.exceptions import InvalidDependencyInjectionSignatureError, InvalidDependencyReturnTypeError
from hassette.models import states
from hassette.utils.type_utils import get_typed_signature


@pytest.mark.usefixtures("with_state_registry")
class TestTypeDetection:
    """Test type detection functions for DI annotations."""

    def test_is_annotated_type_with_annotated(self):
        """Test that Annotated types are correctly identified."""
        annotation = Annotated[str, "metadata"]
        assert is_annotated_type(annotation) is True

    def test_is_annotated_type_with_plain_type(self):
        """Test that plain types are not identified as Annotated."""
        assert is_annotated_type(str) is False
        assert is_annotated_type(int) is False
        assert is_annotated_type(Event) is False

    def test_is_event_type_with_event_class(self):
        """Test detection of Event class."""
        assert is_event_type(Event) is True

    def test_is_event_type_with_event_subclass(self):
        """Test detection of Event subclasses."""
        assert is_event_type(RawStateChangeEvent) is True
        assert is_event_type(CallServiceEvent) is True

    def test_is_event_type_with_non_event(self):
        """Test that non-Event types return False."""
        assert is_event_type(str) is False
        assert is_event_type(int) is False
        assert is_event_type(dict) is False

    def test_is_event_type_with_empty_parameter(self):
        """Test that empty parameter annotation returns False."""
        assert is_event_type(inspect.Parameter.empty) is False


@pytest.mark.usefixtures("with_state_registry")
class TestParameterizedExtractors:
    """Test parameterized extractor classes (AttrNew, AttrOld, AttrOldAndNew)."""

    def test_attr_new_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test AttrNew extracts attribute from new state."""
        # Find an event with friendly_name in new_state
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and "friendly_name" in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None, "No events with friendly_name found"

        param_details_dict = D.AttrNew("friendly_name")
        result = param_details_dict.extractor(event)
        assert result is not None
        assert result == event.payload.data.new_state.get("attributes", {}).get("friendly_name")

    def test_attr_new_extractor_missing_attribute(self, state_change_events: list[RawStateChangeEvent]):
        """Test AttrNew returns MISSING_VALUE for missing attribute."""
        # Find an event where new_state does not have 'non_existent_attr'
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state
                and "non_existent_attr" not in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None, "No suitable event found"

        param_details_dict = D.AttrNew("non_existent_attr")

        result = param_details_dict.extractor(event)

        assert result is MISSING_VALUE

    def test_attr_old_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test AttrOld extracts attribute from old state."""
        # Find an event with old_state and friendly_name
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state and "friendly_name" in e.payload.data.old_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None, "No events with old_state and friendly_name found"

        param_details_dict = D.AttrOld("friendly_name")
        result = param_details_dict.extractor(event)
        assert result is not None
        assert result == event.payload.data.old_state.get("attributes", {}).get("friendly_name")

    def test_attr_old_and_new_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test AttrOldAndNew extracts attribute from both states."""
        # Find event with both states having friendly_name
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state
                and e.payload.data.new_state
                and "friendly_name" in e.payload.data.old_state.get("attributes", {})
                and "friendly_name" in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None, "No suitable event found"

        param_details_dict = D.AttrOldAndNew("friendly_name")
        old_val, new_val = param_details_dict.extractor(event)
        assert old_val == event.payload.data.old_state.get("attributes", {}).get("friendly_name")
        assert new_val == event.payload.data.new_state.get("attributes", {}).get("friendly_name")

    def test_attr_new_with_different_types(self, state_change_events: list[RawStateChangeEvent]):
        """Test AttrNew with different attribute types."""
        # Test with editable (boolean)
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and "editable" in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )

        if not event:
            raise AssertionError("No events with 'editable' attribute found")

        param_details_dict = D.AttrNew("editable")
        result = param_details_dict.extractor(event)
        assert isinstance(result, bool)


@pytest.mark.usefixtures("with_state_registry")
class TestTypeAliasExtractors:
    """Test pre-defined type alias extractors (EntityId, Domain, etc.)."""

    def test_entity_id_extractor(self, all_events: list[Event]):
        """Test EntityId type alias extracts entity_id."""

        # get an event of each type
        event_types = defaultdict(list)
        for event in all_events:
            if "automation_reloaded" in event.topic:
                continue
            event_types[type(event)].append(event)

        for event_type, events in event_types.items():
            # call service event *can* have entity_id in service_data dict, but is not guaranteed
            # to - we want to skip those without it for this test
            if event_type is CallServiceEvent:
                events = [e for e in events if e.payload.data.service_data]

            for event in events:
                # Extract the callable from the Annotated type
                _, annotation_details = extract_from_annotated(D.EntityId)
                result = annotation_details.extractor(event)

                # check only for "not MISSING_VALUE", as we get entity_id from a few different places
                # and the test shouldn't need to be aware of that
                assert result is not MISSING_VALUE, f"EntityId extractor returned MISSING_VALUE for event: {event}"

    def test_entity_id_with_call_service_event_with_empty_data_returns_missing_value(self, other_events: list[Event]):
        """Test MaybeEntityId extractor returns MISSING_VALUE for CallServiceEvent with empty service_data."""
        call_service_event = next(
            (e for e in other_events if isinstance(e, CallServiceEvent) and not e.payload.data.service_data), None
        )
        assert call_service_event is not None, "No CallServiceEvent with empty service_data found in test data"

        _, annotation_details = extract_from_annotated(D.MaybeEntityId)
        result = annotation_details.extractor(call_service_event)

        assert result is MISSING_VALUE, (
            "MaybeEntityId extractor should return MISSING_VALUE for CallServiceEvent with empty service_data, "
            f"got: {result}"
        )

    def test_domain_extractor(self, all_events: list[Event]):
        """Test Domain type alias extracts domain from any Event."""

        # get an event of each type
        event_types = defaultdict(list)
        for event in all_events:
            if "automation_reloaded" in event.topic:
                continue
            event_types[type(event)].append(event)

        for events in event_types.values():
            for event in events:
                # Extract the callable from the Annotated type
                _, annotation_details = extract_from_annotated(D.Domain)
                result = annotation_details.extractor(event)

                # check only for "not MISSING_VALUE", as we get domain from a few different places
                # and the test shouldn't need to be aware of that
                assert result is not MISSING_VALUE, f"Domain extractor returned MISSING_VALUE for event: {event}"

    def test_state_value_new_extractor(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test StateValueNew type alias extracts state value."""

        for event in state_change_events_with_new_state:
            domain = event.payload.data.domain

            state_value_type = get_state_registry().get_value_type_for_domain(domain)

            _, annotation_details = extract_from_annotated(D.StateValueNew[state_value_type.python_type])
            result: states.BaseState = annotation_details.extractor(event)
            converted_result = annotation_details.converter(result, state_value_type.python_type)

            if event.payload.data.new_state:
                assert converted_result == event.payload.data.new_state_value

    def test_state_value_old_extractor(self, state_change_events_with_old_state: list[RawStateChangeEvent]):
        """Test StateValueOld type alias extracts old state value."""

        for event in state_change_events_with_old_state:
            domain = event.payload.data.domain
            state_value_type = get_state_registry().get_value_type_for_domain(domain)

            _, annotation_details = extract_from_annotated(D.StateValueOld[state_value_type.python_type])
            result: states.BaseState = annotation_details.extractor(event)
            converted_result = annotation_details.converter(result, state_value_type.python_type)

            assert converted_result == event.payload.data.old_state_value

    def test_service_data_extractor(self, other_events: list[Event]):
        """Test ServiceData type alias extracts service data from CallServiceEvent."""
        call_service_event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert call_service_event is not None, "No CallServiceEvent found in test data"

        _, annotation_details = extract_from_annotated(D.ServiceData)
        result = annotation_details.extractor(call_service_event)

        assert isinstance(result, dict)
        assert result == call_service_event.payload.data.service_data

    def test_event_context_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test EventContext type alias extracts context."""
        event = state_change_events[0]

        _, annotation_details = extract_from_annotated(D.EventContext)
        result = annotation_details.extractor(event)

        assert isinstance(result, dict)
        assert "id" in result


@pytest.mark.usefixtures("with_state_registry")
class TestExtractFromAnnotated:
    """Test extract_from_annotated function."""

    def test_extract_with_callable_metadata_warns(self):
        """Test that using bare callable in Annotated issues deprecation warning and returns correct extractor."""

        def my_extractor(_event):
            return "extracted"

        annotation = Annotated[str, my_extractor]

        with pytest.warns(DeprecationWarning, match="Using bare callables in Annotated is deprecated"):
            param_details_dict = extract_from_annotated(annotation)

        assert param_details_dict is not None
        base_type, annotation_details = param_details_dict
        assert base_type is str
        assert annotation_details.extractor is my_extractor

    def test_extract_with_non_callable_metadata(self):
        """Test that non-callable metadata returns None."""
        annotation = Annotated[str, "not_callable"]
        param_details_dict = extract_from_annotated(annotation)

        assert param_details_dict is None

    def test_extract_with_non_annotated(self):
        """Test that non-Annotated types return None."""
        assert extract_from_annotated(str) is None
        assert extract_from_annotated(int) is None


@pytest.mark.usefixtures("with_state_registry")
class TestExtractFromEventType:
    """Test extract_from_event_type function."""

    def test_extract_with_event_class(self):
        """Test extraction with Event class returns identity function."""
        event_type, annotation_details = extract_from_event_type(Event)

        assert event_type is not None

        assert event_type is Event

        # Test that extractor is identity function
        mock_event = Event(topic="test", payload={})
        assert annotation_details.extractor(mock_event) is mock_event

    def test_extract_with_state_change_event(self):
        """Test extraction with RawStateChangeEvent subclass."""
        event_type, _annotation_details = extract_from_event_type(RawStateChangeEvent)

        assert event_type is not None
        assert event_type is RawStateChangeEvent

    def test_extract_with_non_event(self):
        """Test that non-Event types return None."""
        assert extract_from_event_type(str) is None
        assert extract_from_event_type(dict) is None


@pytest.mark.usefixtures("with_state_registry")
class TestSignatureExtraction:
    """Test signature extraction and validation."""

    def test_extract_from_signature_with_annotation(self, state_change_events: list[RawStateChangeEvent]):
        """Test extracting parameters with Annotation from signature."""

        def handler(
            new_state: D.StateNew[states.LightState],
            friendly_name: Annotated[str, D.AttrNew("friendly_name")],
        ):
            pass

        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)

        assert len(param_details_dict) == 2
        assert "new_state" in param_details_dict
        assert "friendly_name" in param_details_dict

        new_state_type, annotation_details = param_details_dict["new_state"]
        new_state_extractor = annotation_details.extractor
        assert new_state_type is states.LightState
        # Verify the extractor is wrapped (due to StateNew being required)
        # Check that it still extracts correctly by testing with a real event
        test_event = next(
            e for e in state_change_events if e.payload.data.new_state is not None and e.payload.data.domain == "light"
        )
        extracted_state = new_state_extractor(test_event)
        assert extracted_state is not None
        assert extracted_state == test_event.payload.data.new_state

    def test_extract_from_signature_with_event_type(self):
        """Test extracting Event-typed parameters from signature."""

        def handler(event: RawStateChangeEvent):
            pass

        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)

        assert len(param_details_dict) == 1
        assert "event" in param_details_dict

        event_type, _annotation_details = param_details_dict["event"]
        assert event_type is RawStateChangeEvent

    def test_extract_from_signature_mixed_params(self):
        """Test extracting with mix of DI and regular params."""

        def handler(
            event: RawStateChangeEvent,
            new_state: D.StateNew[states.LightState],
            regular_param: str,
            entity_id: D.EntityId,
        ):
            pass

        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)

        # Only annotated/DI params should be extracted
        assert len(param_details_dict) == 3
        assert "event" in param_details_dict
        assert "new_state" in param_details_dict
        assert "entity_id" in param_details_dict
        assert "regular_param" not in param_details_dict

    def test_extract_from_signature_with_kwargs(self):
        """Test that **kwargs is allowed."""

        def handler(
            new_state: D.StateNew[states.LightState],
            **kwargs,
        ):
            pass

        signature = get_typed_signature(handler)
        # Should not raise
        param_details_dict = extract_from_signature(signature)
        assert "new_state" in param_details_dict

    def test_has_dependency_injection_true(self):
        """Test has_dependency_injection returns True for DI signatures."""

        def handler(new_state: D.StateNew[states.LightState]):
            pass

        signature = get_typed_signature(handler)
        assert has_dependency_injection(signature) is True

    def test_has_dependency_injection_false(self):
        """Test has_dependency_injection returns False for plain signatures."""

        def handler(some_param: str):
            pass

        signature = get_typed_signature(handler)
        assert has_dependency_injection(signature) is False

    def test_has_dependency_injection_with_event_type(self):
        """Test has_dependency_injection returns True for Event-typed params."""

        def handler(event: RawStateChangeEvent):
            pass

        signature = get_typed_signature(handler)
        assert has_dependency_injection(signature) is True

    def test_extract_with_string_annotation(self):
        """Test that string annotations return None."""

        def test_handler(event: "TypedStateChangeEvent"):
            pass

        signature = get_typed_signature(test_handler)

        param_details_dict = extract_from_signature(signature)

        assert "event" in param_details_dict


@pytest.mark.usefixtures("with_state_registry")
class TestSignatureValidation:
    """Test signature validation for DI."""

    def test_validate_di_signature_valid(self):
        """Test that valid DI signatures don't raise."""

        def handler(
            new_state: D.StateNew[states.LightState],
            entity_id: D.EntityId,
            **kwargs,
        ):
            pass

        signature = get_typed_signature(handler)
        # Should not raise
        validate_di_signature(signature)

    def test_validate_di_signature_with_var_positional(self):
        """Test that *args raises ValueError."""

        def handler(
            new_state: D.StateNew[states.LightState],
            *args,
        ):
            pass

        signature = get_typed_signature(handler)
        with pytest.raises(InvalidDependencyInjectionSignatureError):
            validate_di_signature(signature)

    def test_validate_di_signature_with_positional_only(self):
        """Test that positional-only parameters raise ValueError."""

        def handler(
            new_state: D.StateNew[states.LightState],
            positional_only,
            /,
        ):
            pass

        signature = get_typed_signature(handler)
        with pytest.raises(InvalidDependencyInjectionSignatureError):
            validate_di_signature(signature)


@pytest.mark.usefixtures("with_state_registry")
class TestEndToEndDI:
    """End-to-end tests with real event data."""

    def test_extract_multiple_attributes_from_event(self, state_change_events: list[RawStateChangeEvent]):
        """Test extracting multiple pieces of data from same event."""
        # Find suitable event
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and "friendly_name" in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None

        # Define handler signature
        def handler(
            new_state: D.StateNew[states.BaseState],
            entity_id: D.EntityId,
            friendly_name: Annotated[str, D.AttrNew("friendly_name")],
            context: D.EventContext,
        ):
            pass

        # Extract from signature
        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)

        # Apply extractors to event
        extracted_values = {name: details.extractor(event) for name, (_, details) in param_details_dict.items()}

        assert extracted_values["new_state"] == event.payload.data.new_state
        assert extracted_values["entity_id"] == event.payload.data.entity_id
        assert extracted_values["friendly_name"] == event.payload.data.new_state.get("attributes", {}).get(
            "friendly_name"
        )
        assert extracted_values["context"] == event.payload.context

    def test_extract_with_state_change(self, state_change_events: list[RawStateChangeEvent]):
        """Test extraction with event that has both old and new states."""
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state is not None and e.payload.data.new_state is not None
            ),
            None,
        )
        assert event is not None

        def handler(
            old_state: D.StateOld[states.BaseState],
            new_state: D.StateNew[states.BaseState],
            states_tuple: D.StateOldAndNew[states.BaseState],
        ):
            pass

        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)
        extracted_values = {name: details.extractor(event) for name, (_, details) in param_details_dict.items()}

        assert extracted_values["old_state"] == event.payload.data.old_state
        assert extracted_values["new_state"] == event.payload.data.new_state
        assert extracted_values["states_tuple"] == (event.payload.data.old_state, event.payload.data.new_state)

    def test_extract_from_call_service_event(self, other_events: list[Event]):
        """Test extraction from CallServiceEvent."""
        event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert event is not None

        def handler(
            domain: D.Domain,
            service_data: D.ServiceData,
        ):
            pass

        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)
        extracted_values = {name: details.extractor(event) for name, (_, details) in param_details_dict.items()}

        assert extracted_values["domain"] == event.payload.data.domain
        assert extracted_values["service_data"] == event.payload.data.service_data

    def test_mixed_di_strategies_in_one_handler(self, state_change_events: list[RawStateChangeEvent]):
        """Test handler using multiple DI strategies together."""
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and "friendly_name" in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None

        def handler(
            event_param: RawStateChangeEvent,  # Event type (identity)
            new_state: D.StateNew[states.BaseState],  # Annotation TypeAlias
            friendly_name: Annotated[str, D.AttrNew("friendly_name")],  # Parameterized extractor
            entity_id: D.EntityId,  # Type alias with accessor
        ):
            pass

        signature = get_typed_signature(handler)
        param_details_dict = extract_from_signature(signature)

        assert len(param_details_dict) == 4
        extracted_values = {name: details.extractor(event) for name, (_, details) in param_details_dict.items()}

        # All strategies should work together
        assert extracted_values["event_param"] is event
        assert extracted_values["new_state"] == event.payload.data.new_state
        assert extracted_values["friendly_name"] == event.payload.data.new_state.get("attributes", {}).get(
            "friendly_name"
        )
        assert extracted_values["entity_id"] == event.payload.data.entity_id


@pytest.mark.usefixtures("with_state_registry")
class TestMaybeAnnotations:
    """Test Maybe* type aliases that allow None/MISSING_VALUE."""

    def test_maybe_state_new_with_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeStateNew returns None when new_state is None."""
        # Find event where new_state is None (entity removed)
        event = next((e for e in state_change_events if e.payload.data.new_state is None), None)
        assert event is not None, "No event with new_state=None found"

        _, annotation_details = extract_from_annotated(D.MaybeStateNew[states.BaseState])
        result = annotation_details.extractor(event)

        assert result is None

    def test_maybe_state_new_with_value(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeStateNew returns state when present."""
        event = next((e for e in state_change_events if e.payload.data.new_state is not None), None)
        assert event is not None, "No event with new_state found"

        _, annotation_details = extract_from_annotated(D.MaybeStateNew[states.BaseState])
        result = annotation_details.extractor(event)

        assert result is not None
        assert result == event.payload.data.new_state

    def test_maybe_state_old_with_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeStateOld returns None when old_state is None."""
        # Find event where old_state is None (first state)
        event = next((e for e in state_change_events if e.payload.data.old_state is None), None)
        assert event is not None, "No event with old_state=None found"

        _, annotation_details = extract_from_annotated(D.MaybeStateOld[states.BaseState])
        result = annotation_details.extractor(event)

        assert result is None

    def test_maybe_state_old_with_value(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeStateOld returns state when present."""
        event = next((e for e in state_change_events if e.payload.data.old_state is not None), None)
        assert event is not None, "No event with old_state found"

        _, annotation_details = extract_from_annotated(D.MaybeStateOld[states.BaseState])
        result = annotation_details.extractor(event)

        assert result is not None
        assert result == event.payload.data.old_state

    def test_maybe_state_old_and_new_with_partial_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeStateOldAndNew returns tuple with None when old_state is None."""
        event = next((e for e in state_change_events if e.payload.data.old_state is None), None)
        assert event is not None, "No event with old_state=None found"

        _, annotation_details = extract_from_annotated(D.MaybeStateOldAndNew[states.BaseState])
        old_state, _new_state = annotation_details.extractor(event)

        assert old_state is None
        # _new_state might be present or None

    def test_maybe_state_old_and_new_with_both_present(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeStateOldAndNew returns tuple when both present."""
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state is not None and e.payload.data.new_state is not None
            ),
            None,
        )
        assert event is not None, "No event with both states found"

        _, annotation_details = extract_from_annotated(D.MaybeStateOldAndNew[states.BaseState])
        old_state, new_state = annotation_details.extractor(event)

        assert old_state is not None
        assert new_state is not None
        assert old_state == event.payload.data.old_state
        assert new_state == event.payload.data.new_state

    def test_maybe_entity_id_with_value(self, state_change_events: list[RawStateChangeEvent]):
        """Test MaybeEntityId returns entity_id when present."""
        event = state_change_events[0]

        _, annotation_details = extract_from_annotated(D.MaybeEntityId)
        result = annotation_details.extractor(event)

        assert result is not MISSING_VALUE
        assert result == event.payload.data.entity_id

    def test_maybe_domain_with_value(self, other_events: list[Event]):
        """Test MaybeDomain returns domain when present."""
        # Use CallServiceEvent which has domain
        call_service_event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert call_service_event is not None, "No CallServiceEvent found"

        _, annotation_details = extract_from_annotated(D.MaybeDomain)
        result = annotation_details.extractor(call_service_event)

        assert result is not MISSING_VALUE
        assert result == call_service_event.payload.data.domain

    def test_maybe_service_with_value(self, other_events: list[Event]):
        """Test MaybeService returns service name when present."""
        call_service_event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert call_service_event is not None, "No CallServiceEvent found"

        _, annotation_details = extract_from_annotated(D.MaybeService)
        result = annotation_details.extractor(call_service_event)

        assert result is not MISSING_VALUE
        assert result == call_service_event.payload.data.service


@pytest.mark.usefixtures("with_state_registry")
class TestRequiredAnnotations:
    """Test that required (non-Maybe) annotations raise when value is None."""

    def test_state_new_raises_on_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateNew raises InvalidDependencyReturnTypeError when new_state is None."""
        # Find event where new_state is None (entity removed)
        event = next((e for e in state_change_events if e.payload.data.new_state is None), None)
        assert event is not None, "No event with new_state=None found"

        _, annotation_details = extract_from_annotated(D.StateNew[states.BaseState])

        with pytest.raises(InvalidDependencyReturnTypeError):
            annotation_details.extractor(event)

    def test_state_old_raises_on_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateOld raises InvalidDependencyReturnTypeError when old_state is None."""
        # Find event where old_state is None (first state)
        event = next((e for e in state_change_events if e.payload.data.old_state is None), None)
        assert event is not None, "No event with old_state=None found"

        _, annotation_details = extract_from_annotated(D.StateOld[states.BaseState])

        with pytest.raises(InvalidDependencyReturnTypeError):
            annotation_details.extractor(event)

    def test_state_old_and_new_raises_on_partial_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateOldAndNew raises when old_state is None."""
        event = next((e for e in state_change_events if e.payload.data.old_state is None), None)
        assert event is not None, "No event with old_state=None found"

        _, annotation_details = extract_from_annotated(D.StateOldAndNew[states.BaseState])

        with pytest.raises(InvalidDependencyReturnTypeError):
            annotation_details.extractor(event)

    def test_state_old_and_new_raises_on_new_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateOldAndNew raises when new_state is None."""
        event = next((e for e in state_change_events if e.payload.data.new_state is None), None)
        assert event is not None, "No event with new_state=None found"

        _, annotation_details = extract_from_annotated(D.StateOldAndNew[states.BaseState])

        with pytest.raises(InvalidDependencyReturnTypeError):
            annotation_details.extractor(event)

    def test_entity_id_succeeds_with_value(self, state_change_events: list[RawStateChangeEvent]):
        """Test EntityId succeeds when entity_id is present."""
        event = state_change_events[0]

        _, annotation_details = extract_from_annotated(D.EntityId)
        result = annotation_details.extractor(event)

        assert result is not MISSING_VALUE
        assert result == event.payload.data.entity_id

    def test_domain_succeeds_with_value(self, other_events: list[Event]):
        """Test Domain succeeds when domain is extractable."""
        call_service_event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert call_service_event is not None, "No CallServiceEvent found"

        _, annotation_details = extract_from_annotated(D.Domain)
        result = annotation_details.extractor(call_service_event)

        assert result is not MISSING_VALUE
        assert result == call_service_event.payload.data.domain


@pytest.mark.usefixtures("with_state_registry")
class TestDependencyInjectionHandlesTypeConversion:
    """Test that dependency injection handles type conversion correctly."""

    async def test_state_conversion(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test that StateNew converts BaseState to domain-specific state type."""

        for state_change_event in state_change_events_with_new_state:
            model = get_state_registry().get_class_for_domain(state_change_event.payload.data.domain)
            domain = state_change_event.payload.data.domain

            _, annotation_details = extract_from_annotated(D.StateNew[model])
            result = annotation_details.extractor(state_change_event)
            state = annotation_details.converter(result, model)

            assert isinstance(state, model), f"State should be converted to {model.__name__}"
            assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_annotated_as_base_state_stays_base_state(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test that StateNew[BaseState] returns BaseState without conversion."""

        for state_change_event in state_change_events_with_new_state:
            domain = state_change_event.payload.data.domain

            _, annotation_details = extract_from_annotated(D.StateNew[states.BaseState])
            result = annotation_details.extractor(state_change_event)
            state = annotation_details.converter(result, states.BaseState)

            assert isinstance(state, states.BaseState), f"State should be BaseState, got {type(state)}"
            assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_maybe_state_conversion(self, state_change_events: list[RawStateChangeEvent], with_state_registry):
        """Test that MaybeStateNew converts BaseState to domain-specific state type."""

        for state_change_event in state_change_events:
            model = get_state_registry().get_class_for_domain(state_change_event.payload.data.domain)
            domain = state_change_event.payload.data.domain

            def handler(new_state: D.MaybeStateNew[model]):  # ruff: noqa
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            state = kwargs["new_state"]
            if state_change_event.payload.data.new_state is None:
                assert state is None, "State should be None when not present"
            else:
                assert isinstance(state, model), f"State should be converted to {model.__name__}, got {type(state)}"
                assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_maybe_state_as_base_state_stays_base_state(
        self, state_change_events: list[RawStateChangeEvent], with_state_registry
    ):
        """Test that MaybeStateNew[BaseState] returns BaseState without conversion."""

        for state_change_event in state_change_events:
            domain = state_change_event.payload.data.domain

            def handler(new_state: D.MaybeStateNew[states.BaseState]):
                # results.append(new_state)
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            state = kwargs["new_state"]
            if state_change_event.payload.data.new_state is None:
                assert state is None, "State should be None when not present"
            else:
                assert isinstance(state, states.BaseState), f"State should be BaseState, got {type(state)}"
                assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_new_state_with_maybe_old_state_converted_correctly(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test StateNew and MaybeStateOld conversion when only new_state is present."""

        for state_change_event in state_change_events_with_new_state:
            model = get_state_registry().get_class_for_domain(state_change_event.payload.data.domain)

            def handler(new_state: D.StateNew[model], old_state: D.MaybeStateOld[model]):
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            old_state = kwargs["old_state"]

            if state_change_event.payload.data.old_state is None:
                assert old_state is None, "Old state should be None when not present"
            else:
                assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_maybe_new_state_with_old_state_converted_correctly(
        self, state_change_events_with_old_state: list[RawStateChangeEvent]
    ):
        """Test MaybeStateNew and StateOld conversion when only old_state is present."""

        for state_change_event in state_change_events_with_old_state:
            model = get_state_registry().get_class_for_domain(state_change_event.payload.data.domain)

            def handler(new_state: D.MaybeStateNew[model], old_state: D.StateOld[model]):
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            new_state = kwargs["new_state"]
            old_state = kwargs["old_state"]

            if state_change_event.payload.data.new_state is None:
                assert new_state is None, "New state should be None when not present"
            else:
                assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"

            assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_both_states_converted_correctly(
        self, state_change_events_with_both_states: list[RawStateChangeEvent]
    ):
        """Test StateNew and StateOld conversion when both states are present."""
        for state_change_event in state_change_events_with_both_states:
            model = get_state_registry().get_class_for_domain(state_change_event.payload.data.domain)

            def handler(new_state: D.StateNew[model], old_state: D.StateOld[model]):
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            new_state = kwargs["new_state"]
            old_state = kwargs["old_state"]

            assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"
            assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_new_state_value_converted_to_correct_type(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test that StateValueNew converts to correct Python type based on state value."""

        for state_change_event in state_change_events_with_new_state:
            domain = state_change_event.payload.data.domain

            state_value_type = get_state_registry().get_value_type_for_domain(domain)

            def handler(value: D.StateValueNew[state_value_type.python_type]):
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            value = kwargs["value"]

            assert isinstance(value, state_value_type.python_type), (
                f"State value should be converted to {state_value_type.python_type}, got {type(value)}"
            )

    @pytest.mark.parametrize("value_type", [ZonedDateTime, Time, str, bool, Decimal, Any, NoneType])
    async def test_old_state_value_converted_to_correct_type(
        self, state_change_events_with_old_state: list[RawStateChangeEvent], value_type
    ):
        """Test that StateValueOld converts to correct Python type based on state value."""
        for state_change_event in state_change_events_with_old_state:
            domain = state_change_event.payload.data.domain

            state_value_type = get_state_registry().get_value_type_for_domain(domain)
            if state_value_type.python_type is not state_value_type:
                continue

            def handler(value: D.StateValueOld[value_type]):
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            value = kwargs["value"]

            assert isinstance(value, state_value_type.python_type), (
                f"State value should be converted to {state_value_type.python_type}, got {type(value)}"
            )

    async def test_both_state_values_converted_to_correct_type(
        self, state_change_events_with_both_states: list[RawStateChangeEvent]
    ):
        """Test that StateValueOldAndNew converts to correct Python type based on state value."""

        for state_change_event in state_change_events_with_both_states:
            domain = state_change_event.payload.data.domain
            state_value_type = get_state_registry().get_value_type_for_domain(domain)

            def handler(
                value: Annotated[
                    tuple[state_value_type.python_type, state_value_type.python_type],
                    D.StateValueOldAndNew(state_value_type.python_type),
                ],
            ):
                pass

            signature = get_typed_signature(handler)
            kwargs = convert_params(handler, state_change_event, signature)

            old_value, new_value = kwargs["value"]

            assert isinstance(old_value, state_value_type.python_type), (
                f"State value should be converted to {state_value_type.python_type}, got {type(old_value)}"
            )
            assert isinstance(new_value, state_value_type.python_type), (
                f"State value should be converted to {state_value_type.python_type}, got {type(new_value)}"
            )
