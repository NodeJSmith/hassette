"""Integration tests for TelemetryQueryService — source tier, job summary, health, and activity feed."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.helpers import _source_tier_clause
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.telemetry_models import (
    ActivityFeedEntry,
)
from hassette.test_utils.mock_hassette import make_mock_hassette

from .helpers import (
    BASE_TS,
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
)


class TestSourceTierClause:
    def test_any_alias_accepted(self) -> None:
        """_source_tier_clause accepts any alias (developer-controlled, not user input)."""
        fragment, params = _source_tier_clause("app", "custom_alias")
        assert "custom_alias.source_tier" in fragment
        assert params == {"source_tier": "app"}

    def test_framework_tier_returns_filter_fragment(self) -> None:
        """_source_tier_clause('framework', ...) returns an AND clause with 'framework' param."""
        fragment, params = _source_tier_clause("framework", "l")
        assert "source_tier" in fragment
        assert params == {"source_tier": "framework"}

    def test_all_tier_returns_empty(self) -> None:
        """_source_tier_clause('all', ...) returns an empty fragment and empty params."""
        fragment, params = _source_tier_clause("all", "hi")
        assert fragment == ""
        assert params == {}

    def test_app_tier_returns_filter_fragment(self) -> None:
        """_source_tier_clause('app', ...) returns an AND clause with 'app' param."""
        fragment, params = _source_tier_clause("app", "je")
        assert "source_tier" in fragment
        assert params == {"source_tier": "app"}

    def test_all_valid_aliases_accepted(self) -> None:
        """All four valid aliases are accepted without raising."""
        for alias in ("l", "hi", "je", "sj"):
            # Should not raise
            _source_tier_clause("app", alias)


class TestGetJobSummarySinceScoped:
    async def test_get_job_summary_since_scoped(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since filter restricts job execution counts to records after the threshold."""
        db_svc, session_id = db

        base_ts = BASE_TS
        since_ts = base_ts + 5.0

        j1 = await insert_job(db_svc, job_name="job_a")

        # 2 executions after since_ts — should count
        await insert_execution(
            db_svc, j1, session_id, status="success", duration_ms=10.0, execution_start_ts=base_ts + 10.0
        )
        await insert_execution(
            db_svc, j1, session_id, status="error", duration_ms=20.0, execution_start_ts=base_ts + 20.0
        )
        # 1 execution before since_ts — should NOT be counted
        await insert_execution(
            db_svc, j1, session_id, status="success", duration_ms=30.0, execution_start_ts=base_ts + 1.0
        )

        rows = await query_service.get_job_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_executions == 2
        assert row.successful == 1
        assert row.failed == 1


class TestGetAllAppSummariesFrameworkTier:
    async def test_get_all_app_summaries_framework_tier(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='framework' selects active_framework_listeners and active_framework_scheduled_jobs."""
        db_svc, session_id = db

        # Framework-tier listener and job under __hassette__
        fw_listener = await insert_listener(
            db_svc, app_key="__hassette__", handler_method="on_fw", source_tier="framework"
        )
        fw_job = await insert_job(db_svc, app_key="__hassette__", job_name="fw_job", source_tier="framework")

        # App-tier listener and job (should NOT appear for framework query)
        _app_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_app", source_tier="app")
        _app_job = await insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")

        await insert_invocation(
            db_svc, fw_listener, session_id, status="success", duration_ms=5.0, source_tier="framework"
        )
        await insert_execution(db_svc, fw_job, session_id, status="success", duration_ms=10.0, source_tier="framework")

        result = await query_service.get_all_app_summaries(source_tier="framework")

        # Framework data lives under __hassette__ key, which is discarded by FRAMEWORK_APP_KEY guard
        # So result should be empty (the __hassette__ key is excluded)
        assert "my_app" not in result

    async def test_get_all_app_summaries_framework_tier_non_hassette_app_key(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='framework' shows framework-tier records for non-__hassette__ app_key."""
        db_svc, session_id = db

        # A regular app with mixed-tier listeners
        fw_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_fw", source_tier="framework")
        await insert_listener(db_svc, app_key="my_app", handler_method="on_app", source_tier="app")

        await insert_invocation(
            db_svc, fw_listener, session_id, status="success", duration_ms=5.0, source_tier="framework"
        )

        result = await query_service.get_all_app_summaries(source_tier="framework")
        # my_app has 1 framework-tier listener (instance 0)
        assert "my_app" in result
        summary = result["my_app"]
        assert summary.handler_count == 1  # only the framework listener
        assert summary.total_invocations == 1


class TestCheckHealth:
    async def test_check_health_succeeds_on_live_db(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """check_health() completes without raising when the database is live."""
        # Should not raise
        await query_service.check_health()

    async def test_check_health_raises_on_closed_db(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """check_health() raises when the read_db connection is closed."""
        db_svc, _session_id = db
        # Close the read connection to simulate a failed connection
        await db_svc._read_db.close()
        try:
            with pytest.raises((sqlite3.Error, ValueError)):
                await query_service.check_health()
        finally:
            # Restore so fixture teardown doesn't crash
            db_svc._read_db = await aiosqlite.connect(db_svc._db_path, isolation_level=None)
            db_svc._read_db.row_factory = aiosqlite.Row


class TestReadTimeout:
    @pytest.fixture
    def short_timeout_hassette(self, premigrated_db_path: Path) -> MagicMock:
        return make_mock_hassette(
            data_dir=premigrated_db_path.parent,
            set_ready=False,
            database={"telemetry_write_queue_max": 500, "max_size_mb": 0, "read_timeout_seconds": 0.1},
            lifecycle={"resource_shutdown_timeout_seconds": 5},
            web_api={"run": True},
        )

    @pytest.fixture
    async def short_timeout_db(self, short_timeout_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
        db_service = DatabaseService(short_timeout_hassette, parent=None)
        await db_service.on_initialize()
        cursor = await db_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (time.time(), time.time()),
        )
        session_id = cursor.lastrowid
        await db_service.db.commit()
        short_timeout_hassette.session_id = session_id
        short_timeout_hassette.database_service = db_service
        yield db_service, session_id
        await db_service.on_shutdown()

    @pytest.fixture
    def short_timeout_query_service(
        self,
        short_timeout_hassette: MagicMock,
        short_timeout_db: tuple[DatabaseService, int],
    ) -> TelemetryQueryService:
        service = TelemetryQueryService.__new__(TelemetryQueryService)
        service.hassette = short_timeout_hassette
        service.logger = MagicMock()
        service._snapshot_lock = asyncio.Lock()
        return service

    async def test_execute_raises_timeout_error(
        self,
        short_timeout_query_service: TelemetryQueryService,
        short_timeout_db: tuple[DatabaseService, int],
    ) -> None:
        """execute() raises TimeoutError when a query exceeds read_timeout_seconds."""
        db_svc, _ = short_timeout_db

        # Register a custom SQLite function that sleeps, forcing the query to exceed the 100ms timeout
        await db_svc.read_db.create_function("sleep_ms", 1, lambda ms: time.sleep(ms / 1000))

        with pytest.raises(TimeoutError):
            async with short_timeout_query_service.execute("SELECT sleep_ms(300)") as cursor:
                await cursor.fetchone()

    async def test_normal_query_succeeds_within_timeout(
        self,
        short_timeout_query_service: TelemetryQueryService,
        short_timeout_db: tuple[DatabaseService, int],
    ) -> None:
        """A fast query completes within even a short timeout."""
        await short_timeout_query_service.check_health()


class TestGetAppRecentActivity:
    async def test_merged_sorted_by_timestamp_desc(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler invocations and job executions are merged and sorted by timestamp DESC."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_id = await insert_listener(db_svc, app_key="test_app", handler_method="on_event")
        job_id = await insert_job(db_svc, app_key="test_app", job_name="my_job", handler_method="run_job")

        # Interleave timestamps so merge order is testable
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 30.0)
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 10.0, error_type="ValueError"
        )
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=base_ts + 20.0)

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=50,
            since=None,
            source_tier="app",
        )

        assert len(results) == 3
        assert all(isinstance(r, ActivityFeedEntry) for r in results)
        # Sorted DESC by timestamp
        assert results[0].timestamp == pytest.approx(base_ts + 30.0)
        assert results[1].timestamp == pytest.approx(base_ts + 20.0)
        assert results[2].timestamp == pytest.approx(base_ts + 10.0)

    async def test_kind_field_correct(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler invocations have kind='handler', job executions have kind='job'."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_id = await insert_listener(db_svc, app_key="test_app", handler_method="on_event")
        job_id = await insert_job(db_svc, app_key="test_app", job_name="my_job", handler_method="run_job")

        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 20.0)
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=base_ts + 10.0)

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=50,
            since=None,
            source_tier="app",
        )

        assert len(results) == 2
        assert results[0].kind == "handler"
        assert results[1].kind == "job"

    async def test_limit_is_respected(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """limit parameter caps the number of returned entries."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_id = await insert_listener(db_svc, app_key="test_app", handler_method="on_event")

        for i in range(10):
            await insert_invocation(
                db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + float(i)
            )

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=3,
            since=None,
            source_tier="app",
        )

        assert len(results) == 3
        # Should be the 3 most recent
        assert results[0].timestamp == pytest.approx(base_ts + 9.0)
        assert results[1].timestamp == pytest.approx(base_ts + 8.0)
        assert results[2].timestamp == pytest.approx(base_ts + 7.0)

    async def test_since_filters_old_entries(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since parameter excludes entries older than the threshold."""
        db_svc, session_id = db

        base_ts = BASE_TS
        since_ts = base_ts + 15.0

        listener_id = await insert_listener(db_svc, app_key="test_app", handler_method="on_event")
        job_id = await insert_job(db_svc, app_key="test_app", job_name="my_job", handler_method="run_job")

        # After since_ts — should be included
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 20.0)
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=base_ts + 30.0)

        # Before since_ts — should be excluded
        await insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 5.0)
        await insert_execution(db_svc, job_id, session_id, status="error", execution_start_ts=base_ts + 10.0)

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=50,
            since=since_ts,
            source_tier="app",
        )

        assert len(results) == 2
        assert all(r.timestamp >= since_ts for r in results)

    async def test_source_tier_filtering(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='framework' returns only framework-tier entries, not app-tier."""
        db_svc, session_id = db

        base_ts = BASE_TS
        app_listener = await insert_listener(db_svc, app_key="test_app", handler_method="on_app", source_tier="app")
        fw_listener = await insert_listener(db_svc, app_key="test_app", handler_method="on_fw", source_tier="framework")

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

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=50,
            since=None,
            source_tier="framework",
        )

        assert len(results) == 1
        assert results[0].handler_name == "on_fw"

    async def test_instance_index_scoping(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """instance_index filters to entries for that instance only."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_0 = await insert_listener(db_svc, app_key="test_app", instance_index=0, handler_method="on_event")
        listener_1 = await insert_listener(db_svc, app_key="test_app", instance_index=1, handler_method="on_event")

        await insert_invocation(db_svc, listener_0, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_invocation(db_svc, listener_1, session_id, status="success", execution_start_ts=base_ts + 20.0)

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=0,
            limit=50,
            since=None,
            source_tier="app",
        )

        assert len(results) == 1
        assert results[0].timestamp == pytest.approx(base_ts + 10.0)

    async def test_empty_app_returns_empty_list(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """App with no invocations or executions returns an empty list."""
        db_svc, _session_id = db
        await insert_listener(db_svc, app_key="test_app", handler_method="on_event")

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=50,
            since=None,
            source_tier="app",
        )

        assert results == []

    async def test_isolates_to_app_key(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Results are scoped to the requested app_key only."""
        db_svc, session_id = db

        base_ts = BASE_TS
        listener_a = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")
        listener_b = await insert_listener(db_svc, app_key="app_b", handler_method="on_b")

        await insert_invocation(db_svc, listener_a, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_invocation(db_svc, listener_b, session_id, status="success", execution_start_ts=base_ts + 20.0)

        results = await query_service.get_app_recent_activity(
            app_key="app_a",
            instance_index=None,
            limit=50,
            since=None,
            source_tier="app",
        )

        assert len(results) == 1
        assert results[0].app_key == "app_a"

    async def test_row_id_uniqueness_and_prefixes(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """row_id values are unique across all rows and use the correct kind prefix."""
        db_svc, session_id = db

        # Same timestamp for both invocations to stress-test uniqueness
        shared_ts = 1_000_000.0

        listener_id = await insert_listener(db_svc, app_key="test_app", handler_method="on_event")
        job_id = await insert_job(db_svc, app_key="test_app", job_name="my_job", handler_method="run_job")

        # Two handler invocations with the same timestamp
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=shared_ts)
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", execution_start_ts=shared_ts, error_type="ValueError"
        )
        # One job execution with the same timestamp
        await insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=shared_ts)

        results = await query_service.get_app_recent_activity(
            app_key="test_app",
            instance_index=None,
            limit=50,
            since=None,
            source_tier="app",
        )

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
