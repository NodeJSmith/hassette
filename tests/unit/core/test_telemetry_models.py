"""Unit tests for telemetry Pydantic models."""

from hassette.schemas.telemetry_models import JobSummary
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.types.enums import DEFAULT_OVERLAP_MODE


def test_job_summary_new_fields_defaults() -> None:
    """New fields on JobSummary have correct default values."""
    summary = JobSummary(
        job_id=1,
        app_key="my_app",
        instance_index=0,
        job_name="test_job",
        handler_method="MyApp.my_job",
        trigger_type="custom",
        trigger_label="",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location=TEST_SOURCE_LOCATION,
        registration_source=None,
        total_executions=0,
        successful=0,
        failed=0,
        last_executed_at=None,
        total_duration_ms=0.0,
        avg_duration_ms=0.0,
    )

    assert summary.group is None
    assert summary.next_run is None
    assert summary.fire_at is None
    assert summary.jitter is None
    assert summary.cancelled == 0


def test_job_summary_mode_field_in_model_fields() -> None:
    """mode, suppressed_count, dropped_count are declared model fields with correct defaults."""
    assert "mode" in JobSummary.model_fields
    assert "suppressed_count" in JobSummary.model_fields
    assert "dropped_count" in JobSummary.model_fields

    assert JobSummary.model_fields["mode"].default == DEFAULT_OVERLAP_MODE
    assert JobSummary.model_fields["suppressed_count"].default == 0
    assert JobSummary.model_fields["dropped_count"].default == 0


def test_job_summary_repeat_field_removed() -> None:
    """The repeat field has been removed from JobSummary."""
    assert not hasattr(JobSummary.model_fields, "repeat"), "repeat field must not exist on JobSummary"
    # Also verify via direct model_fields check
    assert "repeat" not in JobSummary.model_fields


def test_job_summary_group_can_be_set() -> None:
    """Group field accepts non-None string values."""
    summary = JobSummary(
        job_id=2,
        app_key="my_app",
        instance_index=0,
        job_name="morning_job",
        handler_method="MyApp.morning",
        trigger_type="cron",
        trigger_label="daily",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test.py:2",
        registration_source=None,
        total_executions=5,
        successful=5,
        failed=0,
        last_executed_at=1700000000.0,
        total_duration_ms=500.0,
        avg_duration_ms=100.0,
        group="morning",
    )

    assert summary.group == "morning"


def test_job_summary_cancelled_field_present() -> None:
    """Cancelled field surfaces cancelled execution counts; defaults to 0."""
    assert "cancelled" in JobSummary.model_fields
    assert JobSummary.model_fields["cancelled"].default == 0


def test_job_summary_skipped_field_present() -> None:
    """Skipped field surfaces predicate-skip execution counts; defaults to 0."""
    assert "skipped" in JobSummary.model_fields
    assert JobSummary.model_fields["skipped"].default == 0


def test_job_summary_predicate_description_fields_present() -> None:
    """predicate_description and human_description are declared model fields, defaulting to None."""
    assert "predicate_description" in JobSummary.model_fields
    assert "human_description" in JobSummary.model_fields
    assert JobSummary.model_fields["predicate_description"].default is None
    assert JobSummary.model_fields["human_description"].default is None


def test_job_summary_invariant_with_skipped() -> None:
    """Successful + failed + cancelled + timed_out + skipped == total_executions when skipped > 0."""
    summary = JobSummary(
        job_id=10,
        app_key="my_app",
        instance_index=0,
        job_name="conditional_job",
        handler_method="MyApp.conditional",
        trigger_type="cron",
        trigger_label="daily",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location=TEST_SOURCE_LOCATION,
        registration_source=None,
        total_executions=6,
        successful=3,
        failed=1,
        cancelled=1,
        timed_out=0,
        skipped=1,
        last_executed_at=1700000000.0,
        total_duration_ms=300.0,
        avg_duration_ms=100.0,
    )

    assert summary.successful + summary.failed + summary.cancelled + summary.timed_out + summary.skipped == 6
    assert summary.total_executions == 6


def test_job_summary_next_run_and_fire_at_are_floats() -> None:
    """next_run and fire_at fields accept float epoch values."""
    ts1 = 1700000000.0
    ts2 = 1700000015.0

    summary = JobSummary(
        job_id=4,
        app_key="my_app",
        instance_index=0,
        job_name="jittered_job",
        handler_method="MyApp.jittered",
        trigger_type="interval",
        trigger_label="every 1m",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test.py:4",
        registration_source=None,
        total_executions=10,
        successful=10,
        failed=0,
        last_executed_at=1699999900.0,
        total_duration_ms=1000.0,
        avg_duration_ms=100.0,
        next_run=ts1,
        fire_at=ts2,
        jitter=15.0,
    )

    assert summary.next_run == ts1
    assert summary.fire_at == ts2
    assert summary.jitter == 15.0
