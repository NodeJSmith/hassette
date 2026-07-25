"""Integration tests for TelemetryQueryService — source tier, job summary, and health.

UNION-based methods (get_app_recent_activity, get_per_app_activity_buckets,
get_per_app_last_errors) live in test_union_queries.py.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.helpers import source_tier_clause
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.exceptions import TelemetryUnavailableError
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
        """source_tier_clause accepts any alias (developer-controlled, not user input)."""
        fragment, params = source_tier_clause("app", "custom_alias")
        assert "custom_alias.source_tier" in fragment
        assert params == {"source_tier": "app"}

    def test_framework_tier_returns_filter_fragment(self) -> None:
        """source_tier_clause('framework', ...) returns an AND clause with 'framework' param."""
        fragment, params = source_tier_clause("framework", "l")
        assert "source_tier" in fragment
        assert params == {"source_tier": "framework"}

    def test_all_tier_returns_empty(self) -> None:
        """source_tier_clause('all', ...) returns an empty fragment and empty params."""
        fragment, params = source_tier_clause("all", "hi")
        assert fragment == ""
        assert params == {}

    def test_app_tier_returns_filter_fragment(self) -> None:
        """source_tier_clause('app', ...) returns an AND clause with 'app' param."""
        fragment, params = source_tier_clause("app", "je")
        assert "source_tier" in fragment
        assert params == {"source_tier": "app"}

    def test_all_valid_aliases_accepted(self) -> None:
        """All four valid aliases are accepted without raising."""
        for alias in ("l", "hi", "je", "sj"):
            # Should not raise
            source_tier_clause("app", alias)


class TestGetJobSummarySinceScoped:
    async def test_get_job_summary_since_scoped(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Since filter restricts job execution counts to records after the threshold."""
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
        """check_health() raises TelemetryUnavailableError when the read_db connection is closed."""
        db_svc, _session_id = db
        # Close the read connection to simulate a failed connection
        await db_svc._read_db.close()
        try:
            with pytest.raises(TelemetryUnavailableError):
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
        short_timeout_hassette.try_session_id.return_value = session_id
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
        """execute() raises TelemetryUnavailableError when a query exceeds read_timeout_seconds."""
        db_svc, _ = short_timeout_db

        # Register a custom SQLite function that sleeps, forcing the query to exceed the 100ms timeout
        await db_svc.read_db.create_function("sleep_ms", 1, lambda ms: time.sleep(ms / 1000))

        with pytest.raises(TelemetryUnavailableError):
            async with short_timeout_query_service.execute("SELECT sleep_ms(300)") as cursor:
                await cursor.fetchone()

    async def test_normal_query_succeeds_within_timeout(
        self,
        short_timeout_query_service: TelemetryQueryService,
        short_timeout_db: tuple[DatabaseService, int],
    ) -> None:
        """A fast query completes within even a short timeout."""
        await short_timeout_query_service.check_health()
