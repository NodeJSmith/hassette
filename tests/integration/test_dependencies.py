# pyright: reportInvalidTypeForm=none

# disabling reportInvalidTypeForm - i know this is invalid, but it works best for the dynamic
# nature of the tests

"""Tests for dependency injection extractors and type annotation handling."""

import inspect
from collections import defaultdict
from typing import Annotated

import pytest

from hassette import MISSING_VALUE
from hassette import accessors as A
from hassette import dependencies as D
from hassette.bus.extraction import (
    extract_from_annotated,
    extract_from_event_type,
    extract_from_signature,
    has_dependency_injection,
    is_annotated_type,
    is_event_type,
    validate_di_signature,
)
from hassette.bus.injection import ParameterInjector
from hassette.core.state_registry import STATE_REGISTRY
from hassette.events import CallServiceEvent, Event, HassContext, RawStateChangeEvent
from hassette.exceptions import DependencyInjectionError, DependencyResolutionError
from hassette.models import states
from hassette.utils.type_utils import get_typed_signature


def get_random_model(exclude_models: list[type[states.BaseState]]) -> type[states.BaseState]:
    all_models = [states.LightState, states.SwitchState, states.SensorState]
    for model in all_models:
        if model not in exclude_models:
            return model
    return states.BaseState  # Fallback, should not happen in this test


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


class TestTypeAliasExtractors:
    """Test pre-defined type alias extractors (EntityId, Domain, etc.)."""

    def test_entity_id_extractor(self, all_events: list[Event]):
        """Test EntityId type alias extracts entity_id."""

        # get an event of each type
        event_types: defaultdict[type[Event], list[Event]] = defaultdict(list)
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

    def test_event_context_extractor(self, state_change_events: list[RawStateChangeEvent]):
        """Test EventContext type alias extracts context."""
        for event in state_change_events:
            _, annotation_details = extract_from_annotated(D.EventContext)
            raw_result = annotation_details.extractor(event)
            converted_result = annotation_details.converter(raw_result, None)

            assert isinstance(raw_result, dict)
            assert isinstance(converted_result, HassContext)


class TestExtractFromAnnotated:
    """Test extract_from_annotated function."""

    def test_extract_with_callable_metadata_wraps_in_annodation_details(self):
        """Test that callable metadata is wrapped in AnnotationDetails."""

        def my_extractor(_event):
            return "extracted"

        annotation = Annotated[str, my_extractor]

        param_details_dict = extract_from_annotated(annotation)

        assert param_details_dict is not None
        base_type, annotation_details = param_details_dict
        assert base_type is str
        assert annotation_details.extractor is my_extractor

    def test_extract_with_non_callable_metadata_warns(self):
        """Test that non-callable metadata returns None."""
        annotation = Annotated[str, "not_callable"]

        with pytest.warns(
            UserWarning, match="Invalid Annotated metadata: not_callable is not AnnotationDetails or callable extractor"
        ):
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

        def handler(new_state: D.StateNew[states.LightState], **kwargs):
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

        def test_handler(event: "RawStateChangeEvent"):
            pass

        signature = get_typed_signature(test_handler)

        param_details_dict = extract_from_signature(signature)

        assert "event" in param_details_dict


class TestSignatureValidation:
    """Test signature validation for DI."""

    def test_validate_di_signature_valid(self):
        """Test that valid DI signatures don't raise."""

        def handler(new_state: D.StateNew[states.LightState], entity_id: D.EntityId, **kwargs):
            pass

        signature = get_typed_signature(handler)
        # Should not raise
        validate_di_signature(signature)

    def test_validate_di_signature_with_var_positional(self):
        """Test that *args raises ValueError."""

        def handler(new_state: D.StateNew[states.LightState], *args):
            pass

        signature = get_typed_signature(handler)
        with pytest.raises(DependencyInjectionError):
            validate_di_signature(signature)

    def test_validate_di_signature_with_positional_only(self):
        """Test that positional-only parameters raise ValueError."""

        def handler(new_state: D.StateNew[states.LightState], positional_only, /):
            pass

        signature = get_typed_signature(handler)
        with pytest.raises(DependencyInjectionError):
            validate_di_signature(signature)


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


class TestRequiredAnnotations:
    """Test that required (non-Maybe) annotations raise when value is None."""

    def test_state_new_raises_on_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateNew raises DependencyResolutionError when new_state is None."""
        # Find event where new_state is None (entity removed)
        event = next((e for e in state_change_events if e.payload.data.new_state is None), None)
        assert event is not None, "No event with new_state=None found"

        _, annotation_details = extract_from_annotated(D.StateNew[states.BaseState])

        with pytest.raises(DependencyResolutionError):
            annotation_details.extractor(event)

    def test_state_old_raises_on_none(self, state_change_events: list[RawStateChangeEvent]):
        """Test StateOld raises DependencyResolutionError when old_state is None."""
        # Find event where old_state is None (first state)
        event = next((e for e in state_change_events if e.payload.data.old_state is None), None)
        assert event is not None, "No event with old_state=None found"

        _, annotation_details = extract_from_annotated(D.StateOld[states.BaseState])

        with pytest.raises(DependencyResolutionError):
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


class TestCustomDI:
    """Test custom dependency injection extractors."""

    def test_custom_extractor_used(self, state_change_events: list[RawStateChangeEvent]):
        """Test that a custom extractor function is used."""

        def custom_extractor(event: RawStateChangeEvent) -> str:
            return f"custom-{event.payload.data.entity_id}"

        annotation = Annotated[str, custom_extractor]

        event = state_change_events[0]

        base_type, annotation_details = extract_from_annotated(annotation)
        result = annotation_details.extractor(event)

        assert base_type is str
        assert result == f"custom-{event.payload.data.entity_id}"

    def test_attr_new_example_works(self, state_change_events: list[RawStateChangeEvent]):
        """Test that custom extractor for attribute new value works."""

        def handler(brightness: Annotated[float, A.get_attr_new("brightness")]):
            print("Brightness changed to %s", brightness)

        # Find event where new_state has brightness attribute
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state and "brightness" in e.payload.data.new_state.get("attributes", {})
            ),
            None,
        )
        assert event is not None, "No event with brightness attribute in new_state found"

        signature = get_typed_signature(handler)
        injector = ParameterInjector(handler.__name__, signature)
        kwargs = injector.inject_parameters(event)
        result = kwargs["brightness"]

        expected_brightness = event.payload.data.new_state.get("attributes", {}).get("brightness")

        assert result == expected_brightness, f"Expected brightness {expected_brightness}, got {result}"

    def test_attr_new_return_type(self, state_change_events: list[RawStateChangeEvent]):
        """Test that custom extractor for attribute new value works."""

        def handler(brightness: Annotated[float, A.get_attr_new("brightness")]):
            print("Brightness changed to %s", brightness)

        # Find event where new_state has brightness attribute
        event = next(
            (
                e
                for e in state_change_events
                if e.payload.data.new_state
                and "brightness" in e.payload.data.new_state.get("attributes", {})
                and isinstance(e.payload.data.new_state.get("attributes", {}).get("brightness"), (int, float))
            ),
            None,
        )
        assert event is not None, "No event with brightness attribute in new_state found"

        signature = get_typed_signature(handler)
        injector = ParameterInjector(handler.__name__, signature)
        kwargs = injector.inject_parameters(event)
        result = kwargs["brightness"]

        assert isinstance(result, float), f"Expected result to be float, got {type(result)}"

        expected_brightness = event.payload.data.new_state.get("attributes", {}).get("brightness")

        assert result == expected_brightness, f"Expected brightness {expected_brightness}, got {result}"


class TestDependencyInjectionHandlesTypeConversion:
    """Test that dependency injection handles type conversion correctly."""

    async def test_raw_state_change_event_extractor_returns_event(self, state_change_events: list[RawStateChangeEvent]):
        """Test that RawStateChangeEvent extractor returns the event as-is."""
        for state_change_event in state_change_events:

            def handler(event: RawStateChangeEvent):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)
            result = kwargs["event"]

            assert result is state_change_event, "Extractor should return the event as-is"

    async def test_state_conversion(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test that StateNew converts BaseState to domain-specific state type."""

        for state_change_event in state_change_events_with_new_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
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

    async def test_maybe_state_conversion(self, state_change_events: list[RawStateChangeEvent]):
        """Test that MaybeStateNew converts BaseState to domain-specific state type."""

        for state_change_event in state_change_events:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            domain = state_change_event.payload.data.domain

            def handler(new_state: D.MaybeStateNew[model]):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

            state = kwargs["new_state"]
            if state_change_event.payload.data.new_state is None:
                assert state is None, "State should be None when not present"
            else:
                assert isinstance(state, model), f"State should be converted to {model.__name__}, got {type(state)}"
                assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_maybe_state_as_base_state_stays_base_state(self, state_change_events: list[RawStateChangeEvent]):
        """Test that MaybeStateNew[BaseState] returns BaseState without conversion."""

        for state_change_event in state_change_events:
            domain = state_change_event.payload.data.domain

            def handler(new_state: D.MaybeStateNew[states.BaseState]):
                # results.append(new_state)
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(new_state: D.StateNew[model], old_state: D.MaybeStateOld[model]):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(new_state: D.MaybeStateNew[model], old_state: D.StateOld[model]):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(new_state: D.StateNew[model], old_state: D.StateOld[model]):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

            new_state = kwargs["new_state"]
            old_state = kwargs["old_state"]

            assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"
            assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_typed_state_change_event(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test TypedStateChangeEvent provides typed states."""

        for state_change_event in state_change_events_with_new_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(event: D.TypedStateChangeEvent[model]):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

            event = kwargs["event"]
            new_state = event.payload.data.new_state
            old_state = event.payload.data.old_state

            assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"
            if old_state is not None:
                assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_typed_annotation_with_wrong_type_raise_validation_error(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test TypedStateChangeEvent provides typed states."""

        for state_change_event in state_change_events_with_new_state:
            correct_model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            incorrect_model = get_random_model([correct_model])

            def typed_state_change_handler(event: D.TypedStateChangeEvent[incorrect_model]):
                pass

            def new_state_handler(new_state: D.StateNew[incorrect_model]):
                pass

            for handler in (typed_state_change_handler, new_state_handler):
                signature = get_typed_signature(handler)
                injector = ParameterInjector(handler.__name__, signature)

                with pytest.raises(DependencyResolutionError, match=r".*failed to convert parameter.*"):
                    injector.inject_parameters(state_change_event)


class TestDependencyInjectionTypeConversionHandlesUnions:
    """Test that dependency injection handles Union type annotations correctly."""

    async def test_typed_annotation_union_finds_correct_type(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test TypedStateChangeEvent provides typed states."""

        for state_change_event in state_change_events_with_new_state:
            correct_model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            incorrect_model = get_random_model([correct_model])

            def typed_state_change_handler(event: D.TypedStateChangeEvent[incorrect_model | correct_model]):
                pass

            def new_state_handler(new_state: D.StateNew[incorrect_model | correct_model]):
                pass

            for handler in (typed_state_change_handler, new_state_handler):
                signature = get_typed_signature(handler)
                injector = ParameterInjector(handler.__name__, signature)

                # consider not raising as successs
                injector.inject_parameters(state_change_event)

    async def test_typed_annotation_union_with_all_wrong_types_raises(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test TypedStateChangeEvent provides typed states."""

        for state_change_event in state_change_events_with_new_state:
            correct_model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            incorrect_model = get_random_model([correct_model])
            another_incorrect_model = get_random_model([correct_model, incorrect_model])

            def typed_state_change_handler(event: D.TypedStateChangeEvent[incorrect_model | another_incorrect_model]):
                pass

            def new_state_handler(new_state: D.StateNew[incorrect_model | another_incorrect_model]):
                pass

            for handler in (typed_state_change_handler, new_state_handler):
                signature = get_typed_signature(handler)
                injector = ParameterInjector(handler.__name__, signature)

                with pytest.raises(DependencyResolutionError, match=r".* to any type in Union.*"):
                    injector.inject_parameters(state_change_event)
