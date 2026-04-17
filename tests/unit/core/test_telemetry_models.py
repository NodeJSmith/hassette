"""Unit tests for telemetry Pydantic models."""

from hassette.core.telemetry_models import JobSummary

# ---------------------------------------------------------------------------
# JobSummary model tests
# ---------------------------------------------------------------------------


def test_job_summary_new_fields_defaults() -> None:
    """New fields added in WP01 have correct default values."""
    summary = JobSummary(
        job_id=1,
        app_key="my_app",
        instance_index=0,
        job_name="test_job",
        handler_method="MyApp.my_job",
        trigger_type=None,
        trigger_label="",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test.py:1",
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
    assert summary.cancelled is False


def test_job_summary_repeat_field_removed() -> None:
    """The repeat field has been removed from JobSummary."""
    assert not hasattr(JobSummary.model_fields, "repeat"), "repeat field must not exist on JobSummary"
    # Also verify via direct model_fields check
    assert "repeat" not in JobSummary.model_fields


def test_job_summary_group_can_be_set() -> None:
    """group field accepts non-None string values."""
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


def test_job_summary_cancelled_can_be_set_true() -> None:
    """cancelled field accepts True when the job is cancelled."""
    summary = JobSummary(
        job_id=3,
        app_key="my_app",
        instance_index=0,
        job_name="cancelled_job",
        handler_method="MyApp.cancelled",
        trigger_type="once",
        trigger_label="once",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test.py:3",
        registration_source=None,
        total_executions=1,
        successful=1,
        failed=0,
        last_executed_at=1700000000.0,
        total_duration_ms=100.0,
        avg_duration_ms=100.0,
        cancelled=True,
    )

    assert summary.cancelled is True


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
