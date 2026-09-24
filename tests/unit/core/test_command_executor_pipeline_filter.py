"""Unit tests for framework-tier execution filtering in the write pipeline.

Companion to ``test_command_executor_pipeline_persist.py`` (record building) and
``test_command_executor_pipeline_queue.py`` (queue/retry). Tests here verify the
anomaly-only persistence gate: framework-tier records are filtered before reaching
the write queue, while app-tier records always pass through.
"""

from unittest.mock import patch

from hassette.config.models import DatabaseConfig
from hassette.core.execution_pipeline import enqueue_record, should_persist_framework_record
from hassette.core.execution_record import ExecutionRecord
from hassette.types.types import ExecutionStatus

from .conftest import init_executor, make_invocation


def _make_framework_record(
    *,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    duration_ms: float = 1.0,
) -> ExecutionRecord:
    return ExecutionRecord(
        kind="handler",
        listener_id=1,
        job_id=None,
        session_id=1,
        execution_start_ts=0.0,
        duration_ms=duration_ms,
        status=status,
        source_tier="framework",
    )


def _init_executor_with_filter_config(
    *,
    record_errors: bool = True,
    record_slow_ms: float | None = 100.0,
    sample_rate: float = 0.0,
):
    executor = init_executor()
    executor.hassette.config.database = DatabaseConfig(
        framework_record_errors=record_errors,
        framework_record_slow_ms=record_slow_ms,
        framework_record_sample_rate=sample_rate,
    )
    return executor


class TestShouldPersistFrameworkRecord:
    def test_error_status_always_persisted(self):
        executor = _init_executor_with_filter_config(record_errors=True, record_slow_ms=None, sample_rate=0.0)
        for status in (ExecutionStatus.ERROR, ExecutionStatus.TIMED_OUT, ExecutionStatus.CANCELLED):
            record = _make_framework_record(status=status)
            assert should_persist_framework_record(executor, record) is True

    def test_error_status_dropped_when_record_errors_disabled(self):
        executor = _init_executor_with_filter_config(record_errors=False, record_slow_ms=None, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.ERROR)
        assert should_persist_framework_record(executor, record) is False

    def test_slow_execution_always_persisted(self):
        executor = _init_executor_with_filter_config(record_slow_ms=100.0, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=150.0)
        assert should_persist_framework_record(executor, record) is True

    def test_fast_execution_at_threshold_not_persisted(self):
        executor = _init_executor_with_filter_config(record_slow_ms=100.0, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=100.0)
        assert should_persist_framework_record(executor, record) is False

    def test_slow_threshold_none_disables_duration_check(self):
        executor = _init_executor_with_filter_config(record_errors=False, record_slow_ms=None, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=99999.0)
        assert should_persist_framework_record(executor, record) is False

    def test_sample_rate_zero_drops_routine_successes(self):
        executor = _init_executor_with_filter_config(record_slow_ms=None, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=1.0)
        assert should_persist_framework_record(executor, record) is False

    def test_sample_rate_one_persists_all(self):
        executor = _init_executor_with_filter_config(record_slow_ms=None, sample_rate=1.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=1.0)
        assert should_persist_framework_record(executor, record) is True

    def test_sample_rate_partial_samples_statistically(self):
        executor = _init_executor_with_filter_config(record_slow_ms=None, sample_rate=0.5)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=1.0)

        with patch("hassette.core.execution_pipeline.random") as mock_random:
            mock_random.random.return_value = 0.3
            assert should_persist_framework_record(executor, record) is True

            mock_random.random.return_value = 0.7
            assert should_persist_framework_record(executor, record) is False

    def test_skipped_status_persisted_as_non_success(self):
        executor = _init_executor_with_filter_config(record_errors=True, record_slow_ms=None, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SKIPPED)
        assert should_persist_framework_record(executor, record) is True


class TestEnqueueRecordFiltering:
    def test_app_tier_always_enqueued(self):
        executor = _init_executor_with_filter_config(sample_rate=0.0)
        record = make_invocation(source_tier="app")
        enqueue_record(executor, record)
        assert executor._write_queue.qsize() == 1

    def test_framework_tier_routine_success_dropped(self):
        executor = _init_executor_with_filter_config(record_slow_ms=100.0, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=1.0)
        enqueue_record(executor, record)
        assert executor._write_queue.qsize() == 0

    def test_framework_tier_error_enqueued(self):
        executor = _init_executor_with_filter_config(record_slow_ms=100.0, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.ERROR, duration_ms=1.0)
        enqueue_record(executor, record)
        assert executor._write_queue.qsize() == 1

    def test_framework_tier_slow_success_enqueued(self):
        executor = _init_executor_with_filter_config(record_slow_ms=100.0, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=200.0)
        enqueue_record(executor, record)
        assert executor._write_queue.qsize() == 1

    def test_filtered_records_increment_filtered_counter(self):
        executor = _init_executor_with_filter_config(record_slow_ms=None, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=1.0)
        enqueue_record(executor, record)
        assert executor._dropped_filtered == 1
        assert executor._dropped_overflow == 0

    def test_overflow_counter_not_incremented_for_filtered_records(self):
        executor = _init_executor_with_filter_config(record_slow_ms=None, sample_rate=0.0)
        record = _make_framework_record(status=ExecutionStatus.SUCCESS, duration_ms=1.0)
        enqueue_record(executor, record)
        assert executor._dropped_overflow == 0


class TestFrameworkFilterConfig:
    def test_defaults_are_anomaly_only(self):
        config = DatabaseConfig()
        assert config.framework_record_errors is True
        assert config.framework_record_slow_ms == 100.0
        assert config.framework_record_sample_rate == 0.0
