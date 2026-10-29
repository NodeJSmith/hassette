"""Tests for hassette.resources.shutdown_outcome -- the outcome of one completed shutdown attempt.

Covers restart safety derived from the ranked result and the still-running names, the merge (worst
result, union of names, the worst result's first reason), RestartRefusedError retaining resource
identity and the exact outcome, and public importability of the outcome types and typed errors.
"""

import dataclasses

import pytest

import hassette.exceptions as exceptions_pkg
import hassette.resources as resources_pkg
from hassette.exceptions import FatalError, LifecycleReentryError, RestartRefusedError
from hassette.resources import ShutdownOutcome, ShutdownResult
from hassette.resources.shutdown_outcome import incomplete, merge_outcomes

# Every evidence kind the old cause vocabulary recorded, as its producer now records it, with the
# restart-safe verdict the old vocabulary gave it. Pins that the reshape changed no verdict.
EVIDENCE_VERDICTS = {
    "hook raised": (ShutdownOutcome(ShutdownResult.FAILED, reason="x"), True),
    "hook timed out": (ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="x"), True),
    "cleanup raised": (ShutdownOutcome(ShutdownResult.FAILED, reason="x"), True),
    "cleanup timed out": (ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="x"), True),
    "owned tasks pending": (ShutdownOutcome(still_running=("task",)), False),
    "serve task pending": (ShutdownOutcome(still_running=("service:serve:X",)), False),
    "initializer pending": (ShutdownOutcome(still_running=("resource:initialize:X",)), False),
    "body raised or was cancelled": (incomplete("x"), False),
    "coordinator raised": (incomplete("x"), False),
    "forced terminal": (incomplete("x"), False),
    "child shutdown raised": (incomplete("x"), False),
    "child cut off at a stage deadline": (incomplete("x"), False),
}


class TestRestartSafetyDerivation:
    def test_empty_outcome_is_safe(self) -> None:
        assert ShutdownOutcome().is_restart_safe

    @pytest.mark.parametrize(("outcome", "safe"), EVIDENCE_VERDICTS.values(), ids=EVIDENCE_VERDICTS.keys())
    def test_each_evidence_kind_keeps_its_verdict(self, outcome: ShutdownOutcome, safe: bool) -> None:
        assert outcome.is_restart_safe is safe

    def test_done_with_still_running_names_is_unsafe(self) -> None:
        outcome = ShutdownOutcome(ShutdownResult.DONE, still_running=("task",))

        assert not outcome.is_restart_safe

    def test_an_unsafe_child_makes_its_parent_unsafe_through_the_merge(self) -> None:
        assert not merge_outcomes(ShutdownOutcome(), incomplete("child")).is_restart_safe
        assert not merge_outcomes(ShutdownOutcome(), ShutdownOutcome(still_running=("t",))).is_restart_safe

    def test_results_are_ranked_done_failed_timed_out_incomplete(self) -> None:
        assert ShutdownResult.DONE < ShutdownResult.FAILED < ShutdownResult.TIMED_OUT < ShutdownResult.INCOMPLETE


class TestOutcomeImmutability:
    def test_outcome_is_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            ShutdownOutcome().result = ShutdownResult.INCOMPLETE  # pyright: ignore[reportAttributeAccessIssue]

    def test_still_running_list_is_normalized_to_a_tuple(self) -> None:
        names = ["a"]
        outcome = ShutdownOutcome(still_running=names)  # pyright: ignore[reportArgumentType]
        names.append("b")

        assert outcome.still_running == ("a",)
        assert hash(outcome) == hash(ShutdownOutcome(still_running=("a",)))


class TestMergeOutcomes:
    def test_worst_result_wins(self) -> None:
        merged = merge_outcomes(
            ShutdownOutcome(ShutdownResult.FAILED, reason="raised"),
            ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="timed out"),
            ShutdownOutcome(),
        )

        assert merged.result is ShutdownResult.TIMED_OUT
        assert merged.reason == "timed out"

    def test_first_reason_at_the_worst_result_wins(self) -> None:
        merged = merge_outcomes(
            incomplete("first"), ShutdownOutcome(ShutdownResult.FAILED, reason="x"), incomplete("second")
        )

        assert merged.reason == "first"

    def test_a_timed_out_hook_with_incomplete_evidence_is_incomplete(self) -> None:
        merged = merge_outcomes(ShutdownOutcome(ShutdownResult.TIMED_OUT, reason="hook"), incomplete("body"))

        assert merged.result is ShutdownResult.INCOMPLETE
        assert merged.reason == "body"

    def test_names_are_a_deduplicated_union_in_first_seen_order(self) -> None:
        merged = merge_outcomes(
            ShutdownOutcome(still_running=("b", "a")),
            ShutdownOutcome(still_running=("a", "c")),
        )

        assert merged.still_running == ("b", "a", "c")

    def test_merge_does_not_mutate_inputs(self) -> None:
        first = ShutdownOutcome(still_running=("a",))
        merge_outcomes(first, incomplete("x", ("b",)))

        assert first == ShutdownOutcome(still_running=("a",))

    def test_merge_with_no_arguments_is_an_empty_done_outcome(self) -> None:
        assert merge_outcomes() == ShutdownOutcome()


class TestRestartRefusedError:
    def test_retains_resource_name_and_exact_outcome(self) -> None:
        outcome = incomplete("Bus's shutdown body raised RuntimeError", ("task-1",))
        error = RestartRefusedError("my_resource", outcome)

        assert error.resource_name == "my_resource"
        assert error.outcome is outcome

    def test_message_gives_result_reason_and_still_running(self) -> None:
        error = RestartRefusedError("my_resource", incomplete("Bus's shutdown body raised RuntimeError", ("task-1",)))

        message = str(error)
        assert "my_resource" in message
        assert "INCOMPLETE" in message
        assert "Bus's shutdown body raised RuntimeError" in message
        assert "task-1" in message

    def test_message_without_a_reason(self) -> None:
        message = str(RestartRefusedError("my_resource", ShutdownOutcome(still_running=("task-1",))))

        assert "DONE" in message
        assert "Still running: task-1." in message

    def test_is_a_fatal_error(self) -> None:
        assert isinstance(RestartRefusedError("r", incomplete("x")), FatalError)


class TestLifecycleReentryError:
    def test_retains_resource_name_and_method_name(self) -> None:
        error = LifecycleReentryError("kitchen_light_app", "initialize")

        assert error.resource_name == "kitchen_light_app"
        assert error.method_name == "initialize"

    def test_message_names_resource_and_method(self) -> None:
        error = LifecycleReentryError("my_service", "shutdown")

        message = str(error)
        assert "my_service" in message
        assert "shutdown" in message


class TestPublicImportSurface:
    def test_outcome_types_importable_from_resources_package(self) -> None:
        assert resources_pkg.ShutdownOutcome is ShutdownOutcome
        assert resources_pkg.ShutdownResult is ShutdownResult

    def test_errors_importable_from_exceptions_module(self) -> None:
        assert exceptions_pkg.RestartRefusedError is RestartRefusedError
        assert exceptions_pkg.LifecycleReentryError is LifecycleReentryError
