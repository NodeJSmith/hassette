# pyright: reportInvalidTypeForm=none

# disabling reportInvalidTypeForm - i know this is invalid, but it works best for the dynamic
# nature of the tests

"""Tests for type detection functions used in dependency injection."""

import inspect
from typing import Annotated

import pytest

from hassette.bus.extraction import (
    extract_from_annotated,
    extract_from_event_type,
    is_annotated_type,
    is_event_type,
)
from hassette.events import CallServiceEvent, Event, RawStateChangeEvent


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
