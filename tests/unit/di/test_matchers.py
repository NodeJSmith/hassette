# pyright: reportInvalidTypeForm=none

"""Unit tests for TypeMatcher and AnnotatedMatcher."""

from collections.abc import Callable
from typing import Annotated, Any

import pytest

from hassette.di import AnnotatedMatcher, AnnotationDetails, InjectionParam, TypeMatcher
from hassette.events import AnyEvent, CallServiceEvent, Event, EventPayload, RawStateChangeEvent
from hassette.utils.type_utils import get_typed_signature


def match_param(
    matcher: TypeMatcher | AnnotatedMatcher, handler: Callable[..., Any], name: str
) -> InjectionParam | None:
    """Run `matcher` against the parameter `name` of `handler`'s typed signature."""
    return matcher.match(get_typed_signature(handler).parameters[name])


class TestTypeMatcher:
    """Tests for TypeMatcher.match."""

    def test_matches_exact_type(self):
        def handler(event: AnyEvent):
            pass

        matcher = TypeMatcher(Event)

        result = match_param(matcher, handler, "event")

        assert result is not None
        assert result.name == "event"
        assert result.source_type is Event
        assert result.target_type is AnyEvent

    def test_matches_subclass(self):
        def handler(event: RawStateChangeEvent):
            pass

        matcher = TypeMatcher(Event)

        result = match_param(matcher, handler, "event")

        assert result is not None
        assert result.source_type is Event
        assert result.target_type is RawStateChangeEvent

    def test_extractor_is_identity(self):
        def handler(event: RawStateChangeEvent):
            pass

        matcher = TypeMatcher(Event)
        result = match_param(matcher, handler, "event")

        assert result is not None
        sentinel = object()
        assert result.extractor(sentinel) is sentinel

    def test_unwraps_parameterized_generic(self):
        def handler(event: "Event[EventPayload[Any]]"):
            pass

        matcher = TypeMatcher(Event)

        result = match_param(matcher, handler, "event")

        assert result is not None
        assert result.source_type is Event

    def test_non_matching_type_returns_none(self):
        def handler(value: str):
            pass

        matcher = TypeMatcher(Event)

        assert match_param(matcher, handler, "value") is None

    def test_unrelated_subclass_family_returns_none(self):
        def handler(event: CallServiceEvent):
            pass

        matcher = TypeMatcher(str)

        assert match_param(matcher, handler, "event") is None

    def test_empty_annotation_returns_none(self):
        def handler(value):
            pass

        matcher = TypeMatcher(Event)

        assert match_param(matcher, handler, "value") is None

    def test_matches_union_containing_target(self):
        def handler(event: AnyEvent | None):
            pass

        matcher = TypeMatcher(Event)

        result = match_param(matcher, handler, "event")
        assert result is not None
        assert result.source_type is Event

    def test_union_without_target_returns_none(self):
        def handler(value: str | None):
            pass

        matcher = TypeMatcher(Event)

        assert match_param(matcher, handler, "value") is None

    def test_parameterized_generic_containing_target_returns_none(self):
        def handler(events: list[AnyEvent]):
            pass

        matcher = TypeMatcher(Event)

        assert match_param(matcher, handler, "events") is None


class TestAnnotatedMatcher:
    """Tests for AnnotatedMatcher.match."""

    def test_matches_annotation_details_metadata(self):
        def extractor(_source: AnyEvent) -> str:
            return "extracted"

        def handler(value: Annotated[str, AnnotationDetails(extractor=extractor)]):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        result = match_param(matcher, handler, "value")

        assert result is not None
        assert result.name == "value"
        assert result.source_type is Event
        assert result.target_type is str
        assert result.extractor is extractor
        assert result.converter is None

    def test_auto_wraps_bare_callable(self):
        def bare_extractor(_source: AnyEvent) -> str:
            return "extracted"

        def handler(value: Annotated[str, bare_extractor]):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        result = match_param(matcher, handler, "value")

        assert result is not None
        assert result.extractor is bare_extractor

    def test_warns_and_returns_none_for_invalid_metadata(self):
        def handler(value: Annotated[str, "not_callable"]):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        with pytest.warns(UserWarning, match="Invalid Annotated metadata"):
            result = match_param(matcher, handler, "value")

        assert result is None

    def test_propagates_converter(self):
        def extractor(_source: AnyEvent) -> str:
            return "extracted"

        def converter(value: object, _target_type: object) -> object:
            return value

        def handler(value: Annotated[str, AnnotationDetails(extractor=extractor, converter=converter)]):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        result = match_param(matcher, handler, "value")

        assert result is not None
        assert result.converter is converter

    def test_source_type_falls_back_to_constructor_default(self):
        def extractor(_source: AnyEvent) -> str:
            return "extracted"

        def handler(value: Annotated[str, AnnotationDetails(extractor=extractor)]):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        result = match_param(matcher, handler, "value")

        assert result is not None
        assert result.source_type is Event

    def test_annotation_details_source_type_overrides_constructor_default(self):
        class OtherSource:
            pass

        def extractor(_source: "OtherSource") -> str:
            return "extracted"

        def handler(value: Annotated[str, AnnotationDetails(extractor=extractor, source_type=OtherSource)]):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        result = match_param(matcher, handler, "value")

        assert result is not None
        assert result.source_type is OtherSource

    def test_non_annotated_type_returns_none(self):
        def handler(value: str):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        assert match_param(matcher, handler, "value") is None

    def test_empty_annotation_returns_none(self):
        def handler(value):
            pass

        matcher = AnnotatedMatcher(source_type=Event)

        assert match_param(matcher, handler, "value") is None
