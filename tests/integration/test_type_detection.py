# pyright: reportInvalidTypeForm=none
"""Tests for type detection functions used in dependency injection."""

import inspect
from typing import Annotated

import pytest

from hassette.di import AnnotatedMatcher, TypeMatcher
from hassette.events import CallServiceEvent, Event, RawStateChangeEvent, is_event_type
from hassette.utils.type_utils import get_typed_signature, is_annotated_type


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


class TestExtractFromAnnotated:
    """Test AnnotatedMatcher.match (formerly extract_from_annotated)."""

    def test_extract_with_callable_metadata_wraps_in_annodation_details(self):
        """Test that callable metadata is wrapped in AnnotationDetails."""

        def my_extractor(_event):
            return "extracted"

        def handler(value: Annotated[str, my_extractor]):
            pass

        signature = get_typed_signature(handler)
        result = AnnotatedMatcher(source_type=Event).match(signature.parameters["value"])

        assert result is not None
        assert result.target_type is str
        assert result.extractor is my_extractor

    def test_extract_with_non_callable_metadata_warns(self):
        """Test that non-callable metadata returns None."""

        def handler(value: Annotated[str, "not_callable"]):
            pass

        signature = get_typed_signature(handler)

        with pytest.warns(
            UserWarning, match="Invalid Annotated metadata: not_callable is not AnnotationDetails or callable extractor"
        ):
            result = AnnotatedMatcher(source_type=Event).match(signature.parameters["value"])

        assert result is None

    def test_extract_with_non_annotated(self):
        """Test that non-Annotated types return None."""

        def handler_str(value: str):
            pass

        def handler_int(value: int):
            pass

        matcher = AnnotatedMatcher(source_type=Event)
        for handler in (handler_str, handler_int):
            signature = get_typed_signature(handler)
            assert matcher.match(signature.parameters["value"]) is None


class TestExtractFromEventType:
    """Test TypeMatcher(Event).match (formerly extract_from_event_type)."""

    def test_extract_with_event_class(self):
        """Test extraction with Event class returns identity function."""

        def handler(event: Event):
            pass

        signature = get_typed_signature(handler)
        result = TypeMatcher(Event).match(signature.parameters["event"])

        assert result is not None
        assert result.target_type is Event

        # Test that extractor is identity function
        mock_event = Event(topic="test", payload={})
        assert result.extractor(mock_event) is mock_event

    def test_extract_with_state_change_event(self):
        """Test extraction with RawStateChangeEvent subclass."""

        def handler(event: RawStateChangeEvent):
            pass

        signature = get_typed_signature(handler)
        result = TypeMatcher(Event).match(signature.parameters["event"])

        assert result is not None
        assert result.target_type is RawStateChangeEvent

    def test_extract_with_non_event(self):
        """Test that non-Event types return None."""

        def handler_str(value: str):
            pass

        def handler_dict(value: dict):
            pass

        matcher = TypeMatcher(Event)
        for handler in (handler_str, handler_dict):
            signature = get_typed_signature(handler)
            assert matcher.match(signature.parameters["value"]) is None
