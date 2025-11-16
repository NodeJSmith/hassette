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
from hassette.bus import accessors as A
from hassette.dependencies.classes import AttrNew, AttrOld, AttrOldAndNew, Depends, StateNew, StateOld, StateOldAndNew
from hassette.dependencies.extraction import (
    extract_from_annotated,
    extract_from_depends,
    extract_from_event_type,
    extract_from_signature,
    has_dependency_injection,
    is_annotated_type,
    is_depends_subclass,
    is_event_type,
    validate_di_signature,
)
from hassette.events import CallServiceEvent, Event, StateChangeEvent, create_event_from_hass
from hassette.models import states

if typing.TYPE_CHECKING:
    from hassette.events.hass.raw import HassEventEnvelopeDict


@pytest.fixture(scope="session")
def state_change_events(test_data_path: Path) -> list[StateChangeEvent[states.StateUnion]]:
    """Load state change events from test data file."""
    events = []
    with open(test_data_path / "state_change_events.jsonl") as f:
        for line in f:
            if line.strip():
                # Strip trailing comma if present (JSONL files may have them)
                line = line.strip().rstrip(",")
                envelope: HassEventEnvelopeDict = json.loads(line)
                event = create_event_from_hass(envelope)
                if isinstance(event, StateChangeEvent):
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
    state_change_events: list[StateChangeEvent[states.StateUnion]],
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

    def test_is_depends_subclass_with_depends_instance(self):
        """Test detection of Annotated with Depends instance."""
        annotation = Annotated[states.LightState, StateNew]
        assert is_depends_subclass(annotation) is True

    def test_is_depends_subclass_with_attr_new(self):
        """Test detection of Annotated with AttrNew instance."""
        annotation = Annotated[str, AttrNew("friendly_name")]
        assert is_depends_subclass(annotation) is True

    def test_is_depends_subclass_with_plain_callable(self):
        """Test that plain callable metadata is not detected as Depends."""
        annotation = Annotated[str, lambda x: x]
        assert is_depends_subclass(annotation) is False

    def test_is_depends_subclass_with_non_annotated(self):
        """Test that non-Annotated types return False."""
        assert is_depends_subclass(str) is False
        assert is_depends_subclass(Event) is False

    def test_is_event_type_with_event_class(self):
        """Test detection of Event class."""
        assert is_event_type(Event) is True

    def test_is_event_type_with_event_subclass(self):
        """Test detection of Event subclasses."""
        assert is_event_type(StateChangeEvent) is True
        assert is_event_type(CallServiceEvent) is True

    def test_is_event_type_with_non_event(self):
        """Test that non-Event types return False."""
        assert is_event_type(str) is False
        assert is_event_type(int) is False
        assert is_event_type(dict) is False

    def test_is_event_type_with_empty_parameter(self):
        """Test that empty parameter annotation returns False."""
        assert is_event_type(inspect.Parameter.empty) is False


class TestSingletonExtractors:
    """Test singleton extractor instances (StateNew, StateOld, StateOldAndNew)."""

    def test_state_new_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test StateNew singleton extracts new state correctly."""
        event = state_change_events[0]
        result = StateNew(event)
        assert result is not None
        assert result == event.payload.data.new_state

    def test_state_old_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test StateOld singleton extracts old state correctly."""
        # Find an event with old_state
        event = next((e for e in state_change_events if e.payload.data.old_state is not None), None)
        assert event is not None, "No event with old_state found in test data"

        result = StateOld(event)
        assert result is not None
        assert result == event.payload.data.old_state

    def test_state_old_and_new_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test StateOldAndNew singleton extracts both states correctly."""
        # Find an event with both states
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state is not None and e.payload.data.new_state is not None
            ),
            None,
        )
        assert event is not None, "No events with both old and new states found"

        old_result, new_result = StateOldAndNew(event)
        assert old_result == event.payload.data.old_state
        assert new_result == event.payload.data.new_state

    def test_state_new_with_first_state(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test StateNew works with initial state (no old_state)."""
        event = next((e for e in state_change_events if e.payload.data.old_state is None), None)
        assert event is not None, "No initial state events found"

        result = StateNew(event)
        assert result == event.payload.data.new_state
        assert result is not None

    def test_state_new_with_last_state(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test StateNew works with final state (no new_state) - should return None."""
        event = next((e for e in state_change_events if e.payload.data.new_state is None), None)
        assert event is not None, "No final state events found"

        result = StateNew(event)
        assert result is None


class TestParameterizedExtractors:
    """Test parameterized extractor classes (AttrNew, AttrOld, AttrOldAndNew)."""

    def test_attr_new_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test AttrNew extracts attribute from new state."""
        # Find an event with friendly_name in new_state
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and hasattr(e.payload.data.new_state.attributes, "friendly_name")
            ),
            None,
        )
        assert event is not None, "No events with friendly_name found"

        extractor = AttrNew("friendly_name")
        result = extractor(event)
        assert result is not None
        assert result == event.payload.data.new_state.attributes.friendly_name

    def test_attr_new_extractor_missing_attribute(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test AttrNew returns MISSING_VALUE for missing attribute."""
        # Find an event where new_state does not have 'non_existent_attr'
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and not hasattr(e.payload.data.new_state.attributes, "non_existent_attr")
            ),
            None,
        )
        assert event is not None, "No suitable event found"

        extractor = AttrNew("non_existent_attr")
        result = extractor(event)
        from hassette.bus.accessors import MISSING_VALUE

        assert result is MISSING_VALUE

    def test_attr_old_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test AttrOld extracts attribute from old state."""
        # Find an event with old_state and friendly_name
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state and hasattr(e.payload.data.old_state.attributes, "friendly_name")
            ),
            None,
        )
        assert event is not None, "No events with old_state and friendly_name found"

        extractor = AttrOld("friendly_name")
        result = extractor(event)
        assert result is not None
        assert result == event.payload.data.old_state.attributes.friendly_name

    def test_attr_old_and_new_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test AttrOldAndNew extracts attribute from both states."""
        # Find event with both states having friendly_name
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.old_state
                and e.payload.data.new_state
                and hasattr(e.payload.data.old_state.attributes, "friendly_name")
                and hasattr(e.payload.data.new_state.attributes, "friendly_name")
            ),
            None,
        )
        assert event is not None, "No suitable event found"

        extractor = AttrOldAndNew("friendly_name")
        old_val, new_val = extractor(event)
        assert old_val == event.payload.data.old_state.attributes.friendly_name
        assert new_val == event.payload.data.new_state.attributes.friendly_name

    def test_attr_new_with_different_types(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test AttrNew with different attribute types."""
        # Test with editable (boolean)
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and hasattr(e.payload.data.new_state.attributes, "editable")
            ),
            None,
        )
        if event:
            extractor = AttrNew("editable")
            result = extractor(event)
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
                # event = next((e for e in events if e.payload.data.service_data), None)
                events = [e for e in events if e.payload.data.service_data]

            for event in events:
                # Extract the callable from the Annotated type
                _, extractor = extract_from_annotated(D.EntityId)
                result = extractor(event)

                # check only for "not MISSING_VALUE", as we get entity_id from a few different places
                # and the test shouldn't need to be aware of that
                assert result is not MISSING_VALUE, f"EntityId extractor returned MISSING_VALUE for event: {event}"

    def test_entity_id_with_call_service_event_with_empty_data_returns_missing_value(self, other_events: list[Event]):
        """Test EntityId extractor returns MISSING_VALUE for CallServiceEvent with empty service_data."""
        call_service_event = next(
            (e for e in other_events if isinstance(e, CallServiceEvent) and not e.payload.data.service_data), None
        )
        assert call_service_event is not None, "No CallServiceEvent with empty service_data found in test data"

        _, extractor = extract_from_annotated(D.EntityId)
        result = extractor(call_service_event)

        assert result is MISSING_VALUE, (
            "EntityId extractor should return MISSING_VALUE for CallServiceEvent with empty service_data, "
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
                _, extractor = extract_from_annotated(D.Domain)
                result = extractor(event)

                # check only for "not MISSING_VALUE", as we get domain from a few different places
                # and the test shouldn't need to be aware of that
                assert result is not MISSING_VALUE, f"Domain extractor returned MISSING_VALUE for event: {event}"

    def test_new_state_value_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test NewStateValue type alias extracts state value."""
        event = state_change_events[0]

        _, extractor = extract_from_annotated(D.NewStateValue)
        result = extractor(event)

        if event.payload.data.new_state:
            assert result == event.payload.data.new_state.value

    def test_old_state_value_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test OldStateValue type alias extracts old state value."""
        event = next((e for e in state_change_events if e.payload.data.old_state is not None), None)
        assert event is not None

        _, extractor = extract_from_annotated(D.OldStateValue)
        result = extractor(event)

        assert result == event.payload.data.old_state.value

    def test_service_data_extractor(self, other_events: list[Event]):
        """Test ServiceData type alias extracts service data from CallServiceEvent."""
        call_service_event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert call_service_event is not None, "No CallServiceEvent found in test data"

        _, extractor = extract_from_annotated(D.ServiceData)
        result = extractor(call_service_event)

        assert isinstance(result, dict)
        assert result == call_service_event.payload.data.service_data

    def test_event_context_extractor(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test EventContext type alias extracts context."""
        event = state_change_events[0]

        _, extractor = extract_from_annotated(D.EventContext)
        result = extractor(event)

        assert isinstance(result, dict)
        assert "id" in result


class TestExtractFromAnnotated:
    """Test extract_from_annotated function."""

    def test_extract_with_callable_metadata(self):
        """Test extraction with callable metadata."""

        def my_extractor(_event):
            return "extracted"

        annotation = Annotated[str, my_extractor]
        result = extract_from_annotated(annotation)

        assert result is not None
        base_type, extractor = result
        assert base_type is str
        assert extractor is my_extractor

    def test_extract_with_non_callable_metadata(self):
        """Test that non-callable metadata returns None."""
        annotation = Annotated[str, "not_callable"]
        result = extract_from_annotated(annotation)

        assert result is None

    def test_extract_with_non_annotated(self):
        """Test that non-Annotated types return None."""
        assert extract_from_annotated(str) is None
        assert extract_from_annotated(int) is None


class TestExtractFromDepends:
    """Test extract_from_depends function."""

    def test_extract_with_state_new(self):
        """Test extraction with StateNew singleton."""
        annotation = Annotated[states.LightState, StateNew]
        result = extract_from_depends(annotation)

        assert result is not None
        base_type, extractor = result
        assert base_type is states.LightState
        assert extractor is StateNew

    def test_extract_with_attr_new(self):
        """Test extraction with AttrNew instance."""
        attr_extractor = AttrNew("friendly_name")
        annotation = Annotated[str, attr_extractor]
        result = extract_from_depends(annotation)

        assert result is not None
        base_type, extractor = result
        assert base_type is str
        assert extractor is attr_extractor

    def test_extract_with_non_depends(self):
        """Test that non-Depends metadata returns None."""
        annotation = Annotated[str, lambda x: x]
        result = extract_from_depends(annotation)

        assert result is None


class TestExtractFromEventType:
    """Test extract_from_event_type function."""

    def test_extract_with_event_class(self):
        """Test extraction with Event class returns identity function."""
        result = extract_from_event_type(Event)

        assert result is not None
        event_type, extractor = result
        assert event_type is Event

        # Test that extractor is identity function
        mock_event = Event(topic="test", payload={})
        assert extractor(mock_event) is mock_event

    def test_extract_with_state_change_event(self):
        """Test extraction with StateChangeEvent subclass."""
        result = extract_from_event_type(StateChangeEvent)

        assert result is not None
        event_type, _extractor = result
        assert event_type is StateChangeEvent

    def test_extract_with_non_event(self):
        """Test that non-Event types return None."""
        assert extract_from_event_type(str) is None
        assert extract_from_event_type(dict) is None


class TestSignatureExtraction:
    """Test signature extraction and validation."""

    def test_extract_from_signature_with_depends(self):
        """Test extracting parameters with Depends from signature."""

        def handler(
            new_state: Annotated[states.LightState, StateNew],
            friendly_name: Annotated[str, AttrNew("friendly_name")],
        ):
            pass

        signature = inspect.signature(handler)
        result = extract_from_signature(signature)

        assert len(result) == 2
        assert "new_state" in result
        assert "friendly_name" in result

        new_state_type, new_state_extractor = result["new_state"]
        assert new_state_type is states.LightState
        assert new_state_extractor is StateNew

    def test_extract_from_signature_with_event_type(self):
        """Test extracting Event-typed parameters from signature."""

        def handler(event: StateChangeEvent):
            pass

        signature = inspect.signature(handler)
        result = extract_from_signature(signature)

        assert len(result) == 1
        assert "event" in result

        event_type, _extractor = result["event"]
        assert event_type is StateChangeEvent

    def test_extract_from_signature_mixed_params(self):
        """Test extracting with mix of DI and regular params."""

        def handler(
            event: StateChangeEvent,
            new_state: Annotated[states.LightState, StateNew],
            regular_param: str,
            entity_id: Annotated[str, A.get_entity_id],
        ):
            pass

        signature = inspect.signature(handler)
        result = extract_from_signature(signature)

        # Only annotated/DI params should be extracted
        assert len(result) == 3
        assert "event" in result
        assert "new_state" in result
        assert "entity_id" in result
        assert "regular_param" not in result

    def test_extract_from_signature_with_kwargs(self):
        """Test that **kwargs is allowed."""

        def handler(
            new_state: Annotated[states.LightState, StateNew],
            **kwargs,
        ):
            pass

        signature = inspect.signature(handler)
        # Should not raise
        result = extract_from_signature(signature)
        assert "new_state" in result

    def test_has_dependency_injection_true(self):
        """Test has_dependency_injection returns True for DI signatures."""

        def handler(new_state: Annotated[states.LightState, StateNew]):
            pass

        signature = inspect.signature(handler)
        assert has_dependency_injection(signature) is True

    def test_has_dependency_injection_false(self):
        """Test has_dependency_injection returns False for plain signatures."""

        def handler(some_param: str):
            pass

        signature = inspect.signature(handler)
        assert has_dependency_injection(signature) is False

    def test_has_dependency_injection_with_event_type(self):
        """Test has_dependency_injection returns True for Event-typed params."""

        def handler(event: StateChangeEvent):
            pass

        signature = inspect.signature(handler)
        assert has_dependency_injection(signature) is True


class TestSignatureValidation:
    """Test signature validation for DI."""

    def test_validate_di_signature_valid(self):
        """Test that valid DI signatures don't raise."""

        def handler(
            new_state: Annotated[states.LightState, StateNew],
            entity_id: str,
            **kwargs,
        ):
            pass

        signature = inspect.signature(handler)
        # Should not raise
        validate_di_signature(signature)

    def test_validate_di_signature_with_var_positional(self):
        """Test that *args raises ValueError."""

        def handler(
            new_state: Annotated[states.LightState, StateNew],
            *args,
        ):
            pass

        signature = inspect.signature(handler)
        with pytest.raises(ValueError, match="cannot have \\*args parameter"):
            validate_di_signature(signature)

    def test_validate_di_signature_with_positional_only(self):
        """Test that positional-only parameters raise ValueError."""

        def handler(
            new_state: Annotated[states.LightState, StateNew],
            positional_only,
            /,
        ):
            pass

        signature = inspect.signature(handler)
        with pytest.raises(ValueError, match="cannot have positional-only parameter"):
            validate_di_signature(signature)


class TestDependsBaseClass:
    """Test the Depends base class."""

    def test_depends_base_class_not_implemented(self):
        """Test that Depends base class raises NotImplementedError."""
        depends = Depends()
        mock_event = Event(topic="test", payload={})

        with pytest.raises(NotImplementedError):
            depends(mock_event)

    def test_custom_depends_subclass(self):
        """Test creating custom Depends subclass."""

        class CustomExtractor(Depends):
            def __call__(self, event: Event) -> str:
                return "custom_value"

        extractor = CustomExtractor()
        mock_event = Event(topic="test", payload={})
        result = extractor(mock_event)

        assert result == "custom_value"

    def test_depends_subclass_in_annotation(self):
        """Test using custom Depends subclass in annotation."""

        class CustomExtractor(Depends):
            def __call__(self, event: Event) -> str:
                return "custom_value"

        extractor = CustomExtractor()
        annotation = Annotated[str, extractor]

        assert is_depends_subclass(annotation) is True
        result = extract_from_depends(annotation)
        assert result is not None


class TestEndToEndDI:
    """End-to-end tests with real event data."""

    def test_extract_multiple_attributes_from_event(
        self, state_change_events: list[StateChangeEvent[states.StateUnion]]
    ):
        """Test extracting multiple pieces of data from same event."""
        # Find suitable event
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and hasattr(e.payload.data.new_state.attributes, "friendly_name")
            ),
            None,
        )
        assert event is not None

        # Define handler signature
        def handler(
            new_state: Annotated[states.BaseState, StateNew],
            entity_id: Annotated[str, A.get_entity_id],
            friendly_name: Annotated[str, AttrNew("friendly_name")],
            context: Annotated[dict, A.get_context],
        ):
            pass

        # Extract from signature
        signature = inspect.signature(handler)
        extractors = extract_from_signature(signature)

        # Apply extractors to event
        extracted_values = {name: extractor(event) for name, (_, extractor) in extractors.items()}

        assert extracted_values["new_state"] == event.payload.data.new_state
        assert extracted_values["entity_id"] == event.payload.data.entity_id
        assert extracted_values["friendly_name"] == event.payload.data.new_state.attributes.friendly_name
        assert extracted_values["context"] == event.payload.context

    def test_extract_with_state_change(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
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
            old_state: Annotated[states.BaseState, StateOld],
            new_state: Annotated[states.BaseState, StateNew],
            states_tuple: Annotated[tuple[states.BaseState, states.BaseState], StateOldAndNew],
        ):
            pass

        signature = inspect.signature(handler)
        extractors = extract_from_signature(signature)
        extracted_values = {name: extractor(event) for name, (_, extractor) in extractors.items()}

        assert extracted_values["old_state"] == event.payload.data.old_state
        assert extracted_values["new_state"] == event.payload.data.new_state
        assert extracted_values["states_tuple"] == (event.payload.data.old_state, event.payload.data.new_state)

    def test_extract_from_call_service_event(self, other_events: list[Event]):
        """Test extraction from CallServiceEvent."""
        event = next((e for e in other_events if isinstance(e, CallServiceEvent)), None)
        assert event is not None

        def handler(
            domain: Annotated[str, A.get_domain],
            service_data: Annotated[dict, A.get_service_data],
        ):
            pass

        signature = inspect.signature(handler)
        extractors = extract_from_signature(signature)
        extracted_values = {name: extractor(event) for name, (_, extractor) in extractors.items()}

        assert extracted_values["domain"] == event.payload.data.domain
        assert extracted_values["service_data"] == event.payload.data.service_data

    def test_mixed_di_strategies_in_one_handler(self, state_change_events: list[StateChangeEvent[states.StateUnion]]):
        """Test handler using multiple DI strategies together."""
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and hasattr(e.payload.data.new_state.attributes, "friendly_name")
            ),
            None,
        )
        assert event is not None

        def handler(
            event_param: StateChangeEvent,  # Event type (identity)
            new_state: Annotated[states.BaseState, StateNew],  # Depends singleton
            friendly_name: Annotated[str, AttrNew("friendly_name")],  # Depends parameterized
            entity_id: Annotated[str, A.get_entity_id],  # Type alias with accessor
        ):
            pass

        signature = inspect.signature(handler)
        extractors = extract_from_signature(signature)

        assert len(extractors) == 4
        extracted_values = {name: extractor(event) for name, (_, extractor) in extractors.items()}

        # All strategies should work together
        assert extracted_values["event_param"] is event
        assert extracted_values["new_state"] == event.payload.data.new_state
        assert extracted_values["friendly_name"] == event.payload.data.new_state.attributes.friendly_name
        assert extracted_values["entity_id"] == event.payload.data.entity_id
