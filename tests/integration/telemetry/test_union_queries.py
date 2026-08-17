"""Integration tests for TelemetryQueryService's 3 UNION methods.

Covers ``get_app_recent_activity``, ``get_per_app_activity_buckets``, and
``get_per_app_last_errors`` — all three build their SQL via the shared
``handler_job_union_arms`` helper (see ``core/telemetry/helpers.py``).
"""

import pytest

from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.execution_models import ActivityFeedEntry

from .helpers import (
    BASE_TS,
    DbFixture,
    insert_app_listener_pair,
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
    insert_listener_and_job,
    insert_tiered_listeners,
    recent_activity,
)


class TestGetAppRecentActivity:
    async def test_merged_sorted_by_timestamp_desc(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Handler invocations and job executions are merged and sorted by timestamp DESC."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_id, job_id = await insert_listener_and_job(db_svc)

        # Interleave timestamps so merge order is testable
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 30.0)
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 10.0, error_type="ValueError"
        )
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=base_ts + 20.0)

        results = await recent_activity(query_service)

        assert len(results) == 3
        assert all(isinstance(r, ActivityFeedEntry) for r in results)
        # Sorted DESC by timestamp
        assert results[0].timestamp == pytest.approx(base_ts + 30.0)
        assert results[1].timestamp == pytest.approx(base_ts + 20.0)
        assert results[2].timestamp == pytest.approx(base_ts + 10.0)

    async def test_kind_field_correct(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Handler invocations have kind='handler', job executions have kind='job'."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_id, job_id = await insert_listener_and_job(db_svc)

        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 20.0)
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=base_ts + 10.0)

        results = await recent_activity(query_service)

        assert len(results) == 2
        assert results[0].kind == "handler"
        assert results[0].handler_id == listener_id
        assert results[1].kind == "job"
        assert results[1].handler_id == job_id

    async def test_limit_is_respected(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Limit parameter caps the number of returned entries."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_id = await insert_listener(db_svc, app_key="test_app", handler_method="on_event")

        for i in range(10):
            await insert_invocation(
                db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + float(i)
            )

        results = await recent_activity(query_service, limit=3)

        assert len(results) == 3
        # Should be the 3 most recent
        assert results[0].timestamp == pytest.approx(base_ts + 9.0)
        assert results[1].timestamp == pytest.approx(base_ts + 8.0)
        assert results[2].timestamp == pytest.approx(base_ts + 7.0)

    async def test_since_filters_old_entries(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Since parameter excludes entries older than the threshold."""
        db_svc, session_id = db

        base_ts = BASE_TS
        since_ts = base_ts + 15.0

        listener_id, job_id = await insert_listener_and_job(db_svc)

        # After since_ts — should be included
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 20.0)
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=base_ts + 30.0)

        # Before since_ts — should be excluded
        await insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 5.0)
        await insert_execution(db_svc, job_id, session_id, status="error", execution_start_ts=base_ts + 10.0)

        results = await recent_activity(query_service, since=since_ts)

        assert len(results) == 2
        assert all(r.timestamp >= since_ts for r in results)

    async def test_source_tier_filtering(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """source_tier='framework' returns only framework-tier entries, not app-tier."""
        # dup-ignore-start: tier-scoping cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        app_listener, fw_listener = await insert_tiered_listeners(db_svc)

        await insert_invocation(
            db_svc, app_listener, session_id, status="success", execution_start_ts=base_ts + 10.0, source_tier="app"
        )
        await insert_invocation(
            db_svc,
            fw_listener,
            session_id,
            status="success",
            execution_start_ts=base_ts + 20.0,
            source_tier="framework",
        )
        # dup-ignore-end

        results = await recent_activity(query_service, source_tier="framework")

        assert len(results) == 1
        assert results[0].handler_name == "on_fw"

    async def test_instance_index_scoping(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """instance_index filters to entries for that instance only."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_0 = await insert_listener(db_svc, app_key="test_app", instance_index=0, handler_method="on_event")
        listener_1 = await insert_listener(db_svc, app_key="test_app", instance_index=1, handler_method="on_event")

        await insert_invocation(db_svc, listener_0, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_invocation(db_svc, listener_1, session_id, status="success", execution_start_ts=base_ts + 20.0)

        results = await recent_activity(query_service, instance_index=0)

        assert len(results) == 1
        assert results[0].timestamp == pytest.approx(base_ts + 10.0)

    async def test_empty_app_returns_empty_list(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """App with no invocations or executions returns an empty list."""
        db_svc, _session_id = db
        await insert_listener(db_svc, app_key="test_app", handler_method="on_event")

        results = await recent_activity(query_service)

        assert results == []

    async def test_isolates_to_app_key(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Results are scoped to the requested app_key only."""
        # dup-ignore-start: cross-app cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a, listener_b = await insert_app_listener_pair(db_svc)

        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_invocation(db_svc, listener_b, session_id, status="success", execution_start_ts=base_ts + 20.0)
        # dup-ignore-end

        results = await recent_activity(query_service, app_key="app_a")

        assert len(results) == 1
        assert results[0].app_key == "app_a"

    async def test_row_id_uniqueness_and_prefixes(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """row_id values are unique across all rows and use the correct kind prefix."""
        db_svc, session_id = db

        # Same timestamp for both invocations to stress-test uniqueness
        shared_ts = 1_000_000.0

        listener_id, job_id = await insert_listener_and_job(db_svc)

        # Two handler invocations with the same timestamp
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=shared_ts)
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", execution_start_ts=shared_ts, error_type="ValueError"
        )
        # One job execution with the same timestamp
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=shared_ts)

        results = await recent_activity(query_service)

        assert len(results) == 3

        # All row_id values must be present and unique
        row_ids = [r.row_id for r in results]
        assert len(set(row_ids)) == 3, f"Expected 3 unique row_ids, got: {row_ids}"

        # Handler rows prefixed with 'h-', job rows with 'j-'
        handler_rows = [r for r in results if r.kind == "handler"]
        job_rows = [r for r in results if r.kind == "job"]

        assert len(handler_rows) == 2
        assert len(job_rows) == 1

        for r in handler_rows:
            assert r.row_id.startswith("h-"), f"Handler row_id should start with 'h-', got: {r.row_id!r}"
        for r in job_rows:
            assert r.row_id.startswith("j-"), f"Job row_id should start with 'j-', got: {r.row_id!r}"


class TestGetPerAppActivityBuckets:
    async def test_basic_bucketed_ok_err_counts(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Executions across 2 apps are bucketed into (ok, err) counts per app_key."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")
        job_a = await insert_job(db_svc, app_key="app_a", job_name="job_a")
        listener_b = await insert_listener(db_svc, app_key="app_b", handler_method="on_b")

        since = base_ts
        now = base_ts + 100.0
        num_buckets = 10  # bucket_width == 10.0

        # app_a bucket 0: 1 success (handler)
        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=base_ts + 5.0)
        # app_a bucket 1: 1 error (handler) + 1 success (job)
        await insert_invocation(
            db_svc, listener_a, session_id, status="error", execution_start_ts=base_ts + 15.0, error_type="ValueError"
        )
        await insert_execution(db_svc, job_a, session_id, status="success", execution_start_ts=base_ts + 16.0)
        # app_b bucket 2: 1 success (handler)
        await insert_invocation(db_svc, listener_b, session_id, status="success", execution_start_ts=base_ts + 25.0)

        result = await query_service.get_per_app_activity_buckets(since, now, num_buckets=num_buckets)

        assert set(result.keys()) == {"app_a", "app_b"}
        assert len(result["app_a"]) == num_buckets
        assert len(result["app_b"]) == num_buckets

        assert result["app_a"][0] == (1, 0)
        assert result["app_a"][1] == (1, 1)
        assert result["app_b"][2] == (1, 0)

        # All other buckets are (0, 0)
        for idx in range(num_buckets):
            if idx not in (0, 1):
                assert result["app_a"][idx] == (0, 0)
            if idx != 2:
                assert result["app_b"][idx] == (0, 0)

    async def test_empty_time_range_returns_empty_dict(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Now <= since short-circuits to an empty dict without querying."""
        db_svc, session_id = db
        listener_a = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")
        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=BASE_TS + 5.0)

        result = await query_service.get_per_app_activity_buckets(since=BASE_TS + 50.0, now=BASE_TS + 50.0)
        assert result == {}

        result = await query_service.get_per_app_activity_buckets(since=BASE_TS + 50.0, now=BASE_TS)
        assert result == {}

    async def test_single_bucket_covers_entire_range(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """num_buckets=1 aggregates the whole [since, now) window into one (ok, err) tuple."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")

        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=base_ts + 5.0)
        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=base_ts + 50.0)
        await insert_invocation(
            db_svc, listener_a, session_id, status="error", execution_start_ts=base_ts + 90.0, error_type="ValueError"
        )

        result = await query_service.get_per_app_activity_buckets(since=base_ts, now=base_ts + 100.0, num_buckets=1)

        assert result["app_a"] == [(2, 1)]

    async def test_cross_app_isolation(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """One app's errors do not leak into another app's buckets."""
        # dup-ignore-start: cross-app cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a, listener_b = await insert_app_listener_pair(db_svc)

        # Same bucket (bucket 0) for both apps
        await insert_invocation(
            db_svc, listener_a, session_id, status="error", execution_start_ts=base_ts + 1.0, error_type="ValueError"
        )
        await insert_invocation(db_svc, listener_b, session_id, status="success", execution_start_ts=base_ts + 2.0)
        # dup-ignore-end

        result = await query_service.get_per_app_activity_buckets(since=base_ts, now=base_ts + 10.0, num_buckets=1)

        assert result["app_a"] == [(0, 1)]
        assert result["app_b"] == [(1, 0)]

    async def test_source_tier_app_excludes_framework(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """source_tier='app' (the default) excludes framework-tier executions."""
        # dup-ignore-start: tier-scoping cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        app_listener, fw_listener = await insert_tiered_listeners(db_svc)

        await insert_invocation(
            db_svc, app_listener, session_id, status="success", execution_start_ts=base_ts + 5.0, source_tier="app"
        )
        await insert_invocation(
            db_svc,
            fw_listener,
            session_id,
            status="success",
            execution_start_ts=base_ts + 5.0,
            source_tier="framework",
        )
        # dup-ignore-end

        result = await query_service.get_per_app_activity_buckets(
            since=base_ts, now=base_ts + 10.0, num_buckets=1, source_tier="app"
        )

        assert result["test_app"] == [(1, 0)]


class TestGetPerAppLastErrors:
    async def test_returns_most_recent_error_per_app(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Multiple errors per app resolve to the one with the latest timestamp."""
        # dup-ignore-start: cross-app cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a, listener_b = await insert_app_listener_pair(db_svc)

        await insert_invocation(
            db_svc,
            listener_a,
            session_id,
            status="error",
            execution_start_ts=base_ts + 10.0,
            error_type="ValueError",
            error_message="first",
        )
        await insert_invocation(
            db_svc,
            listener_a,
            session_id,
            status="error",
            execution_start_ts=base_ts + 20.0,
            error_type="RuntimeError",
            error_message="second",
        )
        await insert_invocation(
            db_svc,
            listener_b,
            session_id,
            status="error",
            execution_start_ts=base_ts + 15.0,
            error_type="KeyError",
            error_message="b_error",
        )
        # dup-ignore-end

        result = await query_service.get_per_app_last_errors()

        assert result["app_a"].error_message == "second"
        assert result["app_a"].error_type == "RuntimeError"
        assert result["app_a"].timestamp == pytest.approx(base_ts + 20.0)

        assert result["app_b"].error_message == "b_error"
        assert result["app_b"].timestamp == pytest.approx(base_ts + 15.0)

    async def test_since_window_filtering_excludes_apps_with_no_recent_errors(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """An app whose only error predates the since threshold is excluded entirely."""
        # dup-ignore-start: cross-app cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a, listener_b = await insert_app_listener_pair(db_svc)

        await insert_invocation(
            db_svc,
            listener_a,
            session_id,
            status="error",
            execution_start_ts=base_ts + 10.0,
            error_type="ValueError",
            error_message="before_window",
        )
        await insert_invocation(
            db_svc,
            listener_b,
            session_id,
            status="error",
            execution_start_ts=base_ts + 20.0,
            error_type="KeyError",
            error_message="in_window",
        )
        # dup-ignore-end

        result = await query_service.get_per_app_last_errors(since=base_ts + 15.0)

        assert "app_a" not in result
        assert result["app_b"].error_message == "in_window"

    async def test_source_tier_app_excludes_framework_errors(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """source_tier='app' (the default) ignores later framework-tier errors."""
        # dup-ignore-start: tier-scoping cases share this setup and differ only in the timestamps/statuses each probes
        db_svc, session_id = db

        base_ts = BASE_TS
        app_listener, fw_listener = await insert_tiered_listeners(db_svc)

        await insert_invocation(
            db_svc,
            app_listener,
            session_id,
            status="error",
            execution_start_ts=base_ts + 10.0,
            error_type="ValueError",
            error_message="app_err",
            source_tier="app",
        )
        # Later timestamp, but framework tier — must not win over app_err when source_tier="app"
        await insert_invocation(
            db_svc,
            fw_listener,
            session_id,
            status="error",
            execution_start_ts=base_ts + 20.0,
            error_type="RuntimeError",
            error_message="fw_err",
            source_tier="framework",
        )
        # dup-ignore-end

        result = await query_service.get_per_app_last_errors(source_tier="app")

        assert result["test_app"].error_message == "app_err"

    async def test_apps_with_only_successful_executions_are_excluded(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """An app with no errors at all does not appear in the result."""
        db_svc, session_id = db

        listener_a = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")
        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=BASE_TS + 5.0)

        result = await query_service.get_per_app_last_errors()

        assert result == {}
