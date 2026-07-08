"""Standalone integration test proving hassette.di works independently of the bus.

Uses a plain dataclass (not an Event subclass) as the source type, demonstrating that
build_injection_plan + CallableInvoker + TypeMatcher form a reusable "inspect signature ->
build plan -> resolve kwargs at call time" pipeline with no dependency on hassette.events.
"""

from dataclasses import dataclass
from typing import Annotated

from hassette.di import AnnotatedMatcher, AnnotationDetails, CallableInvoker, TypeMatcher, build_injection_plan
from hassette.utils.type_utils import get_typed_signature


@dataclass
class ScheduledJobStub:
    """Stand-in for a future scheduler ScheduledJob - a plain, non-Event dataclass."""

    job_id: int
    name: str


def get_job_name(job: ScheduledJobStub) -> str:
    return job.name


def test_type_matcher_resolves_non_event_dataclass():
    def predicate(job: ScheduledJobStub) -> bool:
        return job.job_id > 0

    sig = get_typed_signature(predicate)
    plan = build_injection_plan(sig, [TypeMatcher(ScheduledJobStub)])
    invoker = CallableInvoker(plan)

    job = ScheduledJobStub(job_id=42, name="every_five_minutes")
    kwargs = invoker.invoke({ScheduledJobStub: job})

    assert predicate(**kwargs) is True


def test_zero_arg_predicate_resolves_to_empty_kwargs():
    def predicate() -> bool:
        return True

    sig = get_typed_signature(predicate)
    plan = build_injection_plan(sig, [TypeMatcher(ScheduledJobStub)])
    invoker = CallableInvoker(plan)

    kwargs = invoker.invoke({})

    assert kwargs == {}
    assert predicate(**kwargs) is True


def test_annotated_matcher_extracts_field_from_non_event_source():
    def predicate(name: Annotated[str, AnnotationDetails(extractor=get_job_name)]) -> bool:
        return name.startswith("every")

    sig = get_typed_signature(predicate)
    plan = build_injection_plan(sig, [AnnotatedMatcher(source_type=ScheduledJobStub)])
    invoker = CallableInvoker(plan)

    job = ScheduledJobStub(job_id=1, name="every_five_minutes")
    kwargs = invoker.invoke({ScheduledJobStub: job})

    assert kwargs == {"name": "every_five_minutes"}
    assert predicate(**kwargs) is True


def test_mixed_matchers_resolve_full_job_and_extracted_field():
    def predicate(
        job: ScheduledJobStub,
        name: Annotated[str, AnnotationDetails(extractor=get_job_name)],
    ) -> bool:
        return job.job_id > 0 and name == job.name

    sig = get_typed_signature(predicate)
    plan = build_injection_plan(
        sig,
        [AnnotatedMatcher(source_type=ScheduledJobStub), TypeMatcher(ScheduledJobStub)],
    )
    invoker = CallableInvoker(plan)

    job = ScheduledJobStub(job_id=7, name="daily_reset")
    kwargs = invoker.invoke({ScheduledJobStub: job})

    assert predicate(**kwargs) is True
