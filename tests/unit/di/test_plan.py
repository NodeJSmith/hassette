# pyright: reportInvalidTypeForm=none

"""Unit tests for build_injection_plan and validate_di_signature."""

from typing import Annotated

import pytest

from hassette.di import AnnotatedMatcher, AnnotationDetails, TypeMatcher, build_injection_plan, validate_di_signature
from hassette.events import Event, RawStateChangeEvent
from hassette.exceptions import DependencyInjectionError
from hassette.utils.type_utils import get_typed_signature


def _entity_id_extractor(_event: Event) -> str:
    return "light.kitchen"


class TestValidateDiSignature:
    def test_valid_signature_does_not_raise(self):
        def handler(event: RawStateChangeEvent, **kwargs):
            pass

        sig = get_typed_signature(handler)
        validate_di_signature(sig)

    def test_var_positional_raises(self):
        def handler(event: RawStateChangeEvent, *args):
            pass

        sig = get_typed_signature(handler)
        with pytest.raises(DependencyInjectionError):
            validate_di_signature(sig)

    def test_positional_only_raises(self):
        def handler(event: RawStateChangeEvent, positional_only, /):
            pass

        sig = get_typed_signature(handler)
        with pytest.raises(DependencyInjectionError):
            validate_di_signature(sig)


class TestBuildInjectionPlan:
    def test_empty_plan_for_zero_arg_callable(self):
        def handler():
            pass

        sig = get_typed_signature(handler)
        plan = build_injection_plan(sig, [TypeMatcher(Event)])

        assert plan == ()

    def test_skips_unannotated_parameters(self):
        def handler(event: RawStateChangeEvent, plain_param):
            pass

        sig = get_typed_signature(handler)
        plan = build_injection_plan(sig, [TypeMatcher(Event)])

        assert len(plan) == 1
        assert plan[0].name == "event"

    def test_skips_annotated_params_no_matcher_recognizes(self):
        def handler(value: str):
            pass

        sig = get_typed_signature(handler)
        plan = build_injection_plan(sig, [TypeMatcher(Event)])

        assert plan == ()

    def test_matcher_order_first_match_wins(self):
        def handler(event: Annotated[RawStateChangeEvent, AnnotationDetails(extractor=_entity_id_extractor)]):
            pass

        sig = get_typed_signature(handler)

        # AnnotatedMatcher first: should win over TypeMatcher for the Annotated param.
        plan = build_injection_plan(sig, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])

        assert len(plan) == 1
        assert plan[0].extractor is _entity_id_extractor

    def test_mixed_params_via_multiple_matchers(self):
        def handler(
            event: RawStateChangeEvent,
            entity_id: Annotated[str, AnnotationDetails(extractor=_entity_id_extractor)],
            regular_param: str,
        ):
            pass

        sig = get_typed_signature(handler)
        plan = build_injection_plan(sig, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])

        names = {p.name for p in plan}
        assert names == {"event", "entity_id"}

    def test_raises_for_invalid_signature(self):
        def handler(event: RawStateChangeEvent, *args):
            pass

        sig = get_typed_signature(handler)
        with pytest.raises(DependencyInjectionError):
            build_injection_plan(sig, [TypeMatcher(Event)])
