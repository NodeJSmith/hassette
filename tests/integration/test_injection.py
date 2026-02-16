# pyright: reportInvalidTypeForm=none

# disabling reportInvalidTypeForm - i know this is invalid, but it works best for the dynamic
# nature of the tests

"""Tests for Maybe/Required annotations and custom dependency injection extractors."""

from typing import Annotated

import pytest

from hassette import MISSING_VALUE, A, D
from hassette.bus.extraction import extract_from_annotated
from hassette.bus.injection import ParameterInjector
from hassette.events import CallServiceEvent, Event, RawStateChangeEvent
from hassette.exceptions import DependencyResolutionError
from hassette.models import states
from hassette.utils.type_utils import get_typed_signature


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
            pass

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
            pass

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
