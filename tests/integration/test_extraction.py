# pyright: reportInvalidTypeForm=none

# disabling reportInvalidTypeForm - i know this is invalid, but it works best for the dynamic
# nature of the tests

"""Tests for signature extraction, validation, and pre-defined type alias extractors."""

import inspect
from collections import defaultdict
from typing import Any

import pytest

from hassette import MISSING_VALUE, D
from hassette.di import AnnotatedMatcher, InjectionParam, TypeMatcher, build_injection_plan, validate_di_signature
from hassette.events import CallServiceEvent, Event, RawStateChangeEvent
from hassette.exceptions import DependencyInjectionError
from hassette.models import states
from hassette.utils.type_utils import get_typed_signature


def _match_annotated(annotation: Any, source_type: type = Event) -> InjectionParam | None:
    """Build a synthetic parameter for `annotation` and match it via AnnotatedMatcher.

    Mirrors the old `extract_from_annotated(annotation)` call shape for tests that only care
    about the resolved extractor, not the full handler-signature matching flow.
    """
    param = inspect.Parameter("value", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation)
    return AnnotatedMatcher(source_type=source_type).match(param)


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
                # Match the Annotated type via AnnotatedMatcher
                result = _match_annotated(D.EntityId)
                assert result is not None
                extracted = result.extractor(event)

                # check only for "not MISSING_VALUE", as we get entity_id from a few different places
                # and the test shouldn't need to be aware of that
                assert extracted is not MISSING_VALUE, f"EntityId extractor returned MISSING_VALUE for event: {event}"

    def test_entity_id_with_call_service_event_with_empty_data_returns_missing_value(self, other_events: list[Event]):
        """Test MaybeEntityId extractor returns MISSING_VALUE for CallServiceEvent with empty service_data."""
        call_service_event = next(
            (e for e in other_events if isinstance(e, CallServiceEvent) and not e.payload.data.service_data), None
        )
        assert call_service_event is not None, "No CallServiceEvent with empty service_data found in test data"

        result = _match_annotated(D.MaybeEntityId)
        assert result is not None
        extracted = result.extractor(call_service_event)

        assert extracted is MISSING_VALUE, (
            "MaybeEntityId extractor should return MISSING_VALUE for CallServiceEvent with empty service_data, "
            f"got: {extracted}"
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
                # Match the Annotated type via AnnotatedMatcher
                result = _match_annotated(D.Domain)
                assert result is not None
                extracted = result.extractor(event)

                # check only for "not MISSING_VALUE", as we get domain from a few different places
                # and the test shouldn't need to be aware of that
                assert extracted is not MISSING_VALUE, f"Domain extractor returned MISSING_VALUE for event: {event}"


class TestSignatureExtraction:
    """Test signature extraction and validation."""

    def test_extract_from_signature_with_event_type(self):
        """Test extracting Event-typed parameters from signature."""

        def handler(event: RawStateChangeEvent):
            pass

        signature = get_typed_signature(handler)
        plan = build_injection_plan(signature, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])

        assert len(plan) == 1
        assert plan[0].name == "event"
        assert plan[0].target_type is RawStateChangeEvent

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
        plan = build_injection_plan(signature, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])

        # Only annotated/DI params should be extracted
        names = {param.name for param in plan}
        assert len(plan) == 3
        assert "event" in names
        assert "new_state" in names
        assert "entity_id" in names
        assert "regular_param" not in names

    def test_extract_from_signature_with_kwargs(self):
        """Test that **kwargs is allowed."""

        def handler(new_state: D.StateNew[states.LightState], **kwargs):
            pass

        signature = get_typed_signature(handler)
        # Should not raise
        plan = build_injection_plan(signature, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])
        assert "new_state" in {param.name for param in plan}

    def test_extract_with_string_annotation(self):
        """Test that string annotations are resolved and matched normally."""

        def test_handler(event: "RawStateChangeEvent"):
            pass

        signature = get_typed_signature(test_handler)

        plan = build_injection_plan(signature, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])

        assert "event" in {param.name for param in plan}


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
