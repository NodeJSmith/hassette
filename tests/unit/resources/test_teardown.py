"""Tests for hassette.resources.teardown -- immutable teardown safety evidence.

Covers restart safety derivation from causes (immutable merges cannot remove negative
evidence), RestartRefusedError retaining resource identity and the exact teardown report
with useful bounded details, and public importability of the teardown types and typed errors.
"""

import pytest

import hassette.exceptions as exceptions_pkg
import hassette.resources as resources_pkg
from hassette.exceptions import FatalError, LifecycleReentryError, RestartRefusedError
from hassette.resources import TeardownCause, TeardownReport
from hassette.resources.teardown import add_teardown_evidence, merge_teardown_reports


class TestRestartSafetyDerivation:
    def test_empty_report_is_safe(self) -> None:
        report = TeardownReport()

        assert report.is_restart_safe is True

    def test_report_with_any_cause_is_unsafe(self) -> None:
        report = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,))

        assert report.is_restart_safe is False

    def test_is_restart_safe_cannot_be_set_independently_of_causes(self) -> None:
        # TeardownReport intentionally has no constructor parameter for is_restart_safe --
        # it is always derived from `causes`, so a caller cannot construct a report that
        # claims restart-safe while also carrying negative evidence.
        assert "is_restart_safe" not in TeardownReport.__dataclass_fields__


class TestReportImmutability:
    def test_report_is_frozen(self) -> None:
        report = TeardownReport()

        with pytest.raises(AttributeError):
            report.causes = (TeardownCause.CLEANUP_FAILED,)

    def test_report_fields_are_tuples(self) -> None:
        report = TeardownReport(
            causes=(TeardownCause.CLEANUP_FAILED,),
            failed_operations=("cleanup",),
            pending_tasks=("job-1",),
            affected_resources=("child-a",),
        )

        assert isinstance(report.causes, tuple)
        assert isinstance(report.failed_operations, tuple)
        assert isinstance(report.pending_tasks, tuple)
        assert isinstance(report.affected_resources, tuple)


class TestMergeTeardownReports:
    def test_merge_deduplicates_while_preserving_first_seen_order(self) -> None:
        first = TeardownReport(
            causes=(TeardownCause.SHUTDOWN_HOOK_FAILED, TeardownCause.CLEANUP_FAILED),
            failed_operations=("hook_a",),
        )
        second = TeardownReport(
            causes=(TeardownCause.CLEANUP_FAILED, TeardownCause.SERVE_TASK_PENDING),
            failed_operations=("hook_a", "cleanup"),
        )

        merged = merge_teardown_reports(first, second)

        assert merged.causes == (
            TeardownCause.SHUTDOWN_HOOK_FAILED,
            TeardownCause.CLEANUP_FAILED,
            TeardownCause.SERVE_TASK_PENDING,
        )
        assert merged.failed_operations == ("hook_a", "cleanup")

    def test_merge_returns_new_report_and_does_not_mutate_inputs(self) -> None:
        first = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,))
        second = TeardownReport(causes=(TeardownCause.CLEANUP_FAILED,))

        merged = merge_teardown_reports(first, second)

        assert merged is not first
        assert merged is not second
        assert first.causes == (TeardownCause.SHUTDOWN_HOOK_FAILED,)
        assert second.causes == (TeardownCause.CLEANUP_FAILED,)

    def test_merge_of_two_safe_reports_is_safe(self) -> None:
        merged = merge_teardown_reports(TeardownReport(), TeardownReport())

        assert merged.is_restart_safe is True

    def test_merge_with_no_arguments_returns_safe_empty_report(self) -> None:
        merged = merge_teardown_reports()

        assert merged == TeardownReport()
        assert merged.is_restart_safe is True


class TestAddTeardownEvidence:
    def test_add_evidence_preserves_existing_causes(self) -> None:
        report = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED,))

        updated = add_teardown_evidence(report, causes=[TeardownCause.CHILD_RESTART_UNSAFE])

        assert updated.causes == (
            TeardownCause.SHUTDOWN_HOOK_FAILED,
            TeardownCause.CHILD_RESTART_UNSAFE,
        )

    def test_add_evidence_cannot_remove_a_cause(self) -> None:
        # Simulates a later completion (e.g. a straggling shutdown-body task) adding more
        # evidence on top of an already-unsafe report. The original cause must survive.
        report = TeardownReport(causes=(TeardownCause.SHUTDOWN_BODY_TIMED_OUT,))

        updated = add_teardown_evidence(report, causes=[TeardownCause.SHUTDOWN_BODY_FAILED])

        assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT in updated.causes
        assert updated.is_restart_safe is False

    def test_add_no_evidence_returns_equal_but_new_report(self) -> None:
        report = TeardownReport(causes=(TeardownCause.CLEANUP_FAILED,))

        updated = add_teardown_evidence(report)

        assert updated == report
        assert updated is not report

    def test_add_evidence_merges_all_detail_fields(self) -> None:
        report = TeardownReport(pending_tasks=("job-1",))

        updated = add_teardown_evidence(
            report,
            causes=[TeardownCause.TASKS_PENDING],
            failed_operations=["cleanup"],
            pending_tasks=["job-2"],
            affected_resources=["child-a"],
        )

        assert updated.causes == (TeardownCause.TASKS_PENDING,)
        assert updated.failed_operations == ("cleanup",)
        assert updated.pending_tasks == ("job-1", "job-2")
        assert updated.affected_resources == ("child-a",)


class TestReportHasNoTracebackFields:
    def test_report_does_not_carry_exception_type_message_or_traceback_fields(self) -> None:
        field_names = set(TeardownReport.__dataclass_fields__)

        assert not field_names & {"exception", "exception_type", "exception_traceback", "traceback"}


class TestRestartRefusedError:
    def test_retains_resource_name_and_exact_report(self) -> None:
        report = TeardownReport(causes=(TeardownCause.CHILD_SHUTDOWN_TIMED_OUT,))

        error = RestartRefusedError("kitchen_light_app", report)

        assert error.resource_name == "kitchen_light_app"
        assert error.report is report

    def test_message_includes_causes(self) -> None:
        report = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_FAILED, TeardownCause.CLEANUP_TIMED_OUT))

        error = RestartRefusedError("my_service", report)

        assert "my_service" in str(error)
        assert TeardownCause.SHUTDOWN_HOOK_FAILED in str(error)
        assert TeardownCause.CLEANUP_TIMED_OUT in str(error)

    def test_message_includes_populated_bounded_detail_fields(self) -> None:
        report = TeardownReport(
            causes=(TeardownCause.TASKS_PENDING,),
            failed_operations=("cleanup",),
            pending_tasks=("job-1", "job-2"),
            affected_resources=("child-a",),
        )

        error = RestartRefusedError("my_service", report)
        message = str(error)

        assert "cleanup" in message
        assert "job-1" in message
        assert "job-2" in message
        assert "child-a" in message

    def test_message_handles_no_detail_fields_gracefully(self) -> None:
        report = TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))

        error = RestartRefusedError("my_service", report)

        assert "my_service" in str(error)
        assert TeardownCause.FORCED_TERMINAL in str(error)

    def test_is_a_fatal_error(self) -> None:
        report = TeardownReport(causes=(TeardownCause.TOTAL_TIMEOUT,))
        error = RestartRefusedError("my_service", report)

        assert isinstance(error, FatalError)


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
    def test_teardown_types_importable_from_resources_package(self) -> None:
        assert resources_pkg.TeardownCause is TeardownCause
        assert resources_pkg.TeardownReport is TeardownReport

    def test_errors_importable_from_exceptions_module(self) -> None:
        assert exceptions_pkg.RestartRefusedError is RestartRefusedError
        assert exceptions_pkg.LifecycleReentryError is LifecycleReentryError
