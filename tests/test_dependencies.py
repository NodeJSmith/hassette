"""Tests for dependency injection extractors and type annotation handling."""

import inspect
import json
import random
import typing
from collections import defaultdict
from pathlib import Path
from typing import Annotated

import pytest

from hassette import MISSING_VALUE
from hassette import dependencies as D
from hassette.dependencies.extraction import (
    extract_from_annotated,
    extract_from_event_type,
    extract_from_signature,
    has_dependency_injection,
    is_annotated_type,
    is_event_type,
    validate_di_signature,
)
from hassette.events import CallServiceEvent, Event, RawStateChangeEvent, TypedStateChangeEvent, create_event_from_hass
from hassette.exceptions import InvalidDependencyInjectionSignatureError, InvalidDependencyReturnTypeError
from hassette.models import states
from hassette.utils.type_utils import get_typed_signature

if typing.TYPE_CHECKING:
    from hassette.events.hass.raw import HassEventEnvelopeDict


@pytest.fixture(scope="session")
def state_change_events(test_data_path: Path) -> list[RawStateChangeEvent]:
    """Load state change events from test data file."""
    events = []
    with open(test_data_path / "state_change_events.jsonl") as f:
        for line in f:
            if line.strip():
                # Strip trailing comma if present (JSONL files may have them)
                line = line.strip().rstrip(",")
                envelope: HassEventEnvelopeDict = json.loads(line)
                event = create_event_from_hass(envelope)
                if isinstance(event, RawStateChangeEvent):
                    events.append(event)

    # randomize order
    random.shuffle(events)

    return events


@pytest.fixture(scope="session")
def other_events(test_data_path: Path) -> list[Event]:
    """Load other events from test data file."""
    events = []
    with open(test_data_path / "other_events.jsonl") as f:
        for line in f:
            if line.strip():
                # Strip trailing comma if present (JSONL files may have them)
                line = line.strip().rstrip(",")
                envelope: HassEventEnvelopeDict = json.loads(line)
                event = create_event_from_hass(envelope)
                events.append(event)

    # randomize order
    random.shuffle(events)

    return events


@pytest.fixture(scope="session")
def all_events(
    state_change_events: list[RawStateChangeEvent],
    other_events: list[Event],
) -> list[Event]:
    """Combine all events into a single list."""
    return state_change_events + other_events


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

    def test_state_value_new_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateValueNew type alias extracts state value."""
        event = state_change_events[0]

        _, annotation_details = extract_from_annotated(D.StateValueNew[states.BaseState])
        result = annotation_details.extractor(event)

        if event.payload.data.new_state:
            assert result == event.payload.data.new_state_value

    def test_state_value_old_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateValueOld type alias extracts old state value."""
        event = next((e for e in state_change_events if e.payload.data.old_state is not None), None)
        assert event is not None

        _, annotation_details = extract_from_annotated(D.StateValueOld[str])
        result = annotation_details.extractor(event)

        assert result == event.payload.data.old_state_value

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
