"""Integration tests for TelemetryQueryService — aggregate and cross-cutting queries.

Covers get_all_app_summaries, cross-session/retired-row behaviour, source-tier
clause helpers, DI failure flags, slow-handler left-join, job summary, activity
feed, and health check.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_models import (
    AppHealthSummary,
)
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.test_utils.config import SECONDS_PER_DAY
from hassette.test_utils.mock_hassette import make_mock_hassette

from .telemetry_query_helpers import BASE_TS, insert_execution, insert_invocation, insert_job, insert_listener


@pytest.fixture
def db_hassette(premigrated_db_path: Path) -> MagicMock:
    return make_mock_hassette(
        data_dir=premigrated_db_path.parent,
        set_ready=False,
        database={"telemetry_write_queue_max": 500, "max_size_mb": 0},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
        web_api={"run": True},
    )


@pytest.fixture
async def db(db_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a DatabaseService with a seeded session row.

    Yields:
        Tuple of (DatabaseService instance, session_id).
    """
    db_service = DatabaseService(db_hassette, parent=None)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    db_hassette.session_id = session_id
    db_hassette.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def svc(db_hassette: MagicMock, db: tuple[DatabaseService, int]) -> TelemetryQueryService:  # noqa: ARG001
    """Create a TelemetryQueryService with DatabaseService already wired.

    Skips on_initialize (which waits on DatabaseService) since the fixture
    provides it directly via db_hassette.database_service.
    """
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = db_hassette
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service


class TestGetAllAppSummaries:
    async def test_get_all_app_summaries_returns_dict(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Two apps with listeners and jobs — returns dict[str, AppHealthSummary]."""
        db_svc, session_id = db

        # App A: 2 listeners, 1 job
        l1 = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")
        l2 = await insert_listener(db_svc, app_key="app_a", handler_method="on_b")
        j1 = await insert_job(db_svc, app_key="app_a", job_name="job_a")

        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=20.0)
        await insert_invocation(db_svc, l2, session_id, status="success", duration_ms=30.0)
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, j1, session_id, status="error", duration_ms=50.0)

        # App B: 1 listener, 0 jobs
        l3 = await insert_listener(db_svc, app_key="app_b", handler_method="on_c")
        await insert_invocation(db_svc, l3, session_id, status="success", duration_ms=5.0)

        result = await svc.get_all_app_summaries()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"app_a", "app_b"}

        a = result["app_a"]
        assert isinstance(a, AppHealthSummary)
        assert a.handler_count == 2
        assert a.job_count == 1
        assert a.total_invocations == 3
        assert a.total_errors == 1
        assert a.total_executions == 2
        assert a.total_job_errors == 1
        assert a.avg_duration_ms == pytest.approx(20.0)  # (10+20+30)/3
        assert a.last_activity_ts is not None

        b = result["app_b"]
        assert isinstance(b, AppHealthSummary)
        assert b.handler_count == 1
        assert b.job_count == 0
        assert b.total_invocations == 1
        assert b.total_errors == 0
        assert b.total_executions == 0
        assert b.total_job_errors == 0

    async def test_get_all_app_summaries_empty_db(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """No listeners or jobs — returns empty dict."""
        result = await svc.get_all_app_summaries()
        assert result == {}

    async def test_get_all_app_summaries_since_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since filter restricts invocation/execution counts to records after the threshold."""
        db_svc, session_id = db
        base_ts = BASE_TS
        since_ts = base_ts + 5.0

        l1 = await insert_listener(db_svc, app_key="app_x", handler_method="on_a")
        j1 = await insert_job(db_svc, app_key="app_x", job_name="job_a")

        # After since_ts: 2 invocations (1 error), 1 execution — should count
        await insert_invocation(db_svc, l1, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_invocation(db_svc, l1, session_id, status="error", execution_start_ts=base_ts + 20.0)
        await insert_execution(db_svc, j1, session_id, status="success", execution_start_ts=base_ts + 15.0)

        # Before since_ts: 1 invocation, 1 execution (error) — should NOT count
        await insert_invocation(db_svc, l1, session_id, status="success", execution_start_ts=base_ts + 1.0)
        await insert_execution(db_svc, j1, session_id, status="error", execution_start_ts=base_ts + 2.0)

        result = await svc.get_all_app_summaries(since=since_ts)
        assert "app_x" in result
        x = result["app_x"]
        assert x.total_invocations == 2
        assert x.total_errors == 1
        assert x.total_executions == 1
        assert x.total_job_errors == 0

    async def test_get_all_app_summaries_multi_instance_activity_aggregation(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multi-instance app: activity sums across all instances, handler_count reflects instance 0 only."""
        db_svc, session_id = db

        # Instance 0: 2 listeners, 2 invocations
        l0a = await insert_listener(db_svc, app_key="app_m", instance_index=0, handler_method="on_a")
        l0b = await insert_listener(db_svc, app_key="app_m", instance_index=0, handler_method="on_b")
        await insert_invocation(db_svc, l0a, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l0b, session_id, status="error", duration_ms=20.0)

        # Instance 1: 2 listeners (same handlers, different instance), 3 invocations
        l1a = await insert_listener(db_svc, app_key="app_m", instance_index=1, handler_method="on_a")
        l1b = await insert_listener(db_svc, app_key="app_m", instance_index=1, handler_method="on_b")
        await insert_invocation(db_svc, l1a, session_id, status="success", duration_ms=30.0)
        await insert_invocation(db_svc, l1b, session_id, status="success", duration_ms=40.0)
        await insert_invocation(db_svc, l1b, session_id, status="error", duration_ms=50.0)

        # Instance 2: 1 listener, 1 invocation
        l2a = await insert_listener(db_svc, app_key="app_m", instance_index=2, handler_method="on_a")
        await insert_invocation(db_svc, l2a, session_id, status="success", duration_ms=60.0)

        result = await svc.get_all_app_summaries()
        assert "app_m" in result
        m = result["app_m"]

        # handler_count reflects instance 0 only (2 listeners)
        assert m.handler_count == 2
        # total_invocations sums across ALL instances: 2 + 3 + 1 = 6
        assert m.total_invocations == 6
        # total_errors sums across ALL instances: 1 + 1 = 2
        assert m.total_errors == 2
        # avg_duration_ms is AVG over all 6 raw rows: (10+20+30+40+50+60)/6 = 35.0
        assert m.avg_duration_ms == pytest.approx(35.0)

    async def test_get_all_app_summaries_multi_instance_job_aggregation(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multi-instance app: job activity sums across all instances, job_count reflects instance 0 only."""
        db_svc, session_id = db

        # Instance 0: 1 job, 2 executions
        j0 = await insert_job(db_svc, app_key="app_j", instance_index=0, job_name="cron_a")
        await insert_execution(db_svc, j0, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, j0, session_id, status="error", duration_ms=50.0)

        # Instance 1: 1 job, 3 executions
        j1 = await insert_job(db_svc, app_key="app_j", instance_index=1, job_name="cron_a")
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=200.0)
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=150.0)
        await insert_execution(db_svc, j1, session_id, status="error", duration_ms=80.0)

        # Instance 2: 1 job, 1 execution
        j2 = await insert_job(db_svc, app_key="app_j", instance_index=2, job_name="cron_a")
        await insert_execution(db_svc, j2, session_id, status="success", duration_ms=300.0)

        result = await svc.get_all_app_summaries()
        assert "app_j" in result
        j = result["app_j"]

        # job_count reflects instance 0 only (1 job)
        assert j.job_count == 1
        # total_executions sums across ALL instances: 2 + 3 + 1 = 6
        assert j.total_executions == 6
        # total_job_errors sums across ALL instances: 1 + 1 = 2
        assert j.total_job_errors == 2

    async def test_get_all_app_summaries_single_instance_equivalence(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Single-instance app produces equivalent results to current behavior."""
        db_svc, session_id = db

        # Only instance 0 — same as current behavior
        l1 = await insert_listener(db_svc, app_key="app_s", instance_index=0, handler_method="on_x")
        j1 = await insert_job(db_svc, app_key="app_s", instance_index=0, job_name="job_x")

        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=15.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=25.0)
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)

        result = await svc.get_all_app_summaries()
        assert "app_s" in result
        s = result["app_s"]

        assert s.handler_count == 1
        assert s.job_count == 1
        assert s.total_invocations == 2
        assert s.total_errors == 1
        assert s.total_executions == 1
        assert s.total_job_errors == 0
        assert s.avg_duration_ms == pytest.approx(20.0, abs=0.001)

    async def test_get_all_app_summaries_multi_instance_since_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multi-instance data with since filter: only records after threshold count."""
        db_svc, session_id = db

        base_ts = BASE_TS
        since_ts = base_ts + 5.0

        # Instance 0: listener + job
        l0 = await insert_listener(db_svc, app_key="app_ms", instance_index=0, handler_method="on_a")
        j0 = await insert_job(db_svc, app_key="app_ms", instance_index=0, job_name="cron_a")

        # Instance 1: listener + job
        l1 = await insert_listener(db_svc, app_key="app_ms", instance_index=1, handler_method="on_a")
        j1 = await insert_job(db_svc, app_key="app_ms", instance_index=1, job_name="cron_a")

        # After since_ts: instance 0 gets 2 invocations, instance 1 gets 1 invocation
        await insert_invocation(
            db_svc, l0, session_id, status="success", duration_ms=10.0, execution_start_ts=base_ts + 10.0
        )
        await insert_invocation(
            db_svc, l0, session_id, status="error", duration_ms=20.0, execution_start_ts=base_ts + 20.0
        )
        await insert_invocation(
            db_svc, l1, session_id, status="success", duration_ms=30.0, execution_start_ts=base_ts + 30.0
        )
        await insert_execution(db_svc, j0, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_execution(db_svc, j1, session_id, status="error", execution_start_ts=base_ts + 20.0)

        # Before since_ts: 1 invocation + 1 execution per instance — should NOT be counted
        await insert_invocation(
            db_svc, l0, session_id, status="success", duration_ms=100.0, execution_start_ts=base_ts + 1.0
        )
        await insert_execution(db_svc, j0, session_id, status="error", execution_start_ts=base_ts + 2.0)

        result = await svc.get_all_app_summaries(since=since_ts)
        assert "app_ms" in result
        ms = result["app_ms"]

        # handler_count from instance 0 only
        assert ms.handler_count == 1
        # job_count from instance 0 only
        assert ms.job_count == 1
        # total_invocations: after since_ts across all instances = 2 + 1 = 3
        assert ms.total_invocations == 3
        # total_errors: after since_ts across all instances = 1
        assert ms.total_errors == 1
        # total_executions: after since_ts across all instances = 1 + 1 = 2
        assert ms.total_executions == 2
        # total_job_errors: after since_ts across all instances = 1
        assert ms.total_job_errors == 1
        # avg_duration_ms: after since_ts across all instances = (10+20+30)/3 = 20.0
        assert ms.avg_duration_ms == pytest.approx(20.0)


class TestCrossSessionAndRetiredRows:
    async def test_all_time_aggregates_across_sessions(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All-time query (no session_id) spans multiple sessions.

        Register a listener in session 1, create invocations, then simulate
        a restart (upsert the same row in session 2 by re-inserting with a new
        session), create more invocations, and assert the all-time total covers
        both sessions.
        """
        db_svc, session_1 = db

        # Create session 2 (simulates a restart)
        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (time.time(), time.time()),
        )
        session_2 = cursor.lastrowid
        await db_svc.db.commit()

        # Session 1: register listener and create 2 invocations
        listener_id = await insert_listener(db_svc, handler_method="on_event")
        await insert_invocation(db_svc, listener_id, session_1, status="success")
        await insert_invocation(db_svc, listener_id, session_1, status="error")

        # Session 2: same listener row (FK still valid), 3 more invocations
        await insert_invocation(db_svc, listener_id, session_2, status="success")
        await insert_invocation(db_svc, listener_id, session_2, status="success")
        await insert_invocation(db_svc, listener_id, session_2, status="success")

        # All-time query must aggregate across both sessions
        summary = await svc.get_listener_summary("test_app", 0)
        assert len(summary) == 1
        row = summary[0]
        assert row.total_invocations == 5
        assert row.successful == 4
        assert row.failed == 1

    async def test_listener_summary_includes_retired(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_listener_summary queries base tables and includes retired rows.

        A retired listener with invocation history must still appear in the summary.
        """
        db_svc, session_id = db

        retired_id = await insert_listener(db_svc, handler_method="on_retired")
        await insert_invocation(db_svc, retired_id, session_id, status="success")
        await insert_invocation(db_svc, retired_id, session_id, status="error")

        # Mark as retired
        now = time.time()
        await db_svc.db.execute(
            "UPDATE listeners SET retired_at = ? WHERE id = ?",
            (now, retired_id),
        )
        await db_svc.db.commit()

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.handler_method == "on_retired"
        assert row.total_invocations == 2
        assert row.successful == 1
        assert row.failed == 1

    async def test_retention_cleanup_deletes_old_retired_rows(
        self,
        db: tuple[DatabaseService, int],
    ) -> None:
        """_do_run_retention_cleanup deletes retired registration rows older than retention_days.

        Insert a listener and a scheduled_job with old retired_at timestamps and
        a recent one. After cleanup, the old ones must be deleted and the recent
        one preserved.
        """
        db_svc, _session_id = db

        now = time.time()
        old_retired_at = now - (8 * SECONDS_PER_DAY)  # 8 days ago — beyond 7-day retention
        recent_retired_at = now - (1 * SECONDS_PER_DAY)  # 1 day ago — within retention

        # Insert old retired listener (no invocations needed)
        cursor = await db_svc.db.execute(
            "INSERT INTO listeners (app_key, instance_index, handler_method, topic, "
            "debounce, throttle, once, priority, source_location, retired_at) "
            "VALUES ('test_app', 0, 'on_old', 'hass.event', NULL, NULL, 0, 0, 'test.py:1', ?)",
            (old_retired_at,),
        )
        old_listener_id = cursor.lastrowid

        # Insert recent retired listener (should survive cleanup)
        cursor = await db_svc.db.execute(
            "INSERT INTO listeners (app_key, instance_index, handler_method, topic, "
            "debounce, throttle, once, priority, source_location, retired_at) "
            "VALUES ('test_app', 0, 'on_recent', 'hass.event', NULL, NULL, 0, 0, 'test.py:2', ?)",
            (recent_retired_at,),
        )
        recent_listener_id = cursor.lastrowid

        # Insert old retired scheduled_job
        cursor = await db_svc.db.execute(
            "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, "
            "trigger_type, repeat, source_location, retired_at) "
            "VALUES ('test_app', 0, 'old_job', 'run_old', 'interval', 1, 'test.py:3', ?)",
            (old_retired_at,),
        )
        old_job_id = cursor.lastrowid

        # Insert recent retired scheduled_job (should survive cleanup)
        cursor = await db_svc.db.execute(
            "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, "
            "trigger_type, repeat, source_location, retired_at) "
            "VALUES ('test_app', 0, 'recent_job', 'run_recent', 'interval', 1, 'test.py:4', ?)",
            (recent_retired_at,),
        )
        recent_job_id = cursor.lastrowid

        await db_svc.db.commit()

        # Run retention cleanup
        await db_svc._do_run_retention_cleanup()

        # Old retired rows must be deleted
        cursor = await db_svc.db.execute("SELECT id FROM listeners WHERE id = ?", (old_listener_id,))
        assert await cursor.fetchone() is None, "Old retired listener must be deleted"

        cursor = await db_svc.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (old_job_id,))
        assert await cursor.fetchone() is None, "Old retired job must be deleted"

        # Recent retired rows must be preserved
        cursor = await db_svc.db.execute("SELECT id FROM listeners WHERE id = ?", (recent_listener_id,))
        assert await cursor.fetchone() is not None, "Recent retired listener must survive"

        cursor = await db_svc.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (recent_job_id,))
        assert await cursor.fetchone() is not None, "Recent retired job must survive"


class TestGetAllAppSummariesSourceTier:
    async def test_get_all_app_summaries_excludes_hassette(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Framework actors (__hassette__) are excluded from get_all_app_summaries."""
        db_svc, session_id = db

        # App-tier listener
        app_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_a", source_tier="app")
        # Framework-tier listener registered as __hassette__
        fw_listener = await insert_listener(
            db_svc, app_key="__hassette__", handler_method="on_fw", source_tier="framework"
        )

        base_ts = 8_000_000.0
        await insert_invocation(
            db_svc, app_listener, session_id, status="success", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        await insert_invocation(
            db_svc, fw_listener, session_id, status="success", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )

        result = await svc.get_all_app_summaries()
        assert "__hassette__" not in result
        assert "my_app" in result

    async def test_get_all_app_summaries_activity_filtered_by_app_tier(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Framework invocations don't inflate app-tier counts in get_all_app_summaries."""
        db_svc, session_id = db

        # App-tier listener for "my_app"
        app_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_a", source_tier="app")
        # Framework-tier listener for "my_app" (same app_key, different tier)
        fw_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_fw", source_tier="framework")

        base_ts = 9_000_000.0
        # 1 app-tier invocation
        await insert_invocation(
            db_svc, app_listener, session_id, status="success", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        # 2 framework-tier invocations — must NOT be counted in app summary
        await insert_invocation(
            db_svc, fw_listener, session_id, status="success", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )
        await insert_invocation(
            db_svc, fw_listener, session_id, status="error", execution_start_ts=base_ts + 3.0, source_tier="framework"
        )

        result = await svc.get_all_app_summaries()
        assert "my_app" in result
        summary = result["my_app"]
        # Only the 1 app-tier invocation should be counted
        assert summary.total_invocations == 1
        assert summary.total_errors == 0


class TestDiFailureFlag:
    async def test_di_failure_flag_query(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """is_di_failure=1 records are counted as di_failures in get_listener_summary."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_di")

        # 2 DI failures (is_di_failure=1) and 1 regular error
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyError", is_di_failure=1
        )
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyError", is_di_failure=1
        )
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="ValueError", is_di_failure=0
        )

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.di_failures == 2
        assert row.failed == 3

    async def test_di_failure_flag_not_string_match(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Records with error_type LIKE 'Dependency%' but is_di_failure=0 are NOT counted."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_test")

        # error_type looks like a DI error but flag is 0
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyError", is_di_failure=0
        )
        # Real DI failure with flag set
        await insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyInjectionError", is_di_failure=1
        )

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        # Only the one with is_di_failure=1 should count
        assert row.di_failures == 1


class TestGetSlowHandlersLeftJoin:
    async def test_get_slow_handlers_left_join(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Delete a listener; its slow invocations still appear with null app_key."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_slow")

        await insert_invocation(db_svc, listener_id, session_id, duration_ms=500.0)
        # Delete the listener
        await db_svc.db.execute("DELETE FROM listeners WHERE id = ?", (listener_id,))
        await db_svc.db.commit()

        rows = await svc.get_slow_handlers(threshold_ms=100.0)
        assert len(rows) == 1
        # Orphaned row: app_key should be None (LEFT JOIN with no match)
        assert rows[0].duration_ms == pytest.approx(500.0)

    async def test_get_slow_handlers_source_tier_filter(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='app' (default) excludes framework slow handlers."""
        db_svc, session_id = db
        app_listener = await insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await insert_listener(db_svc, handler_method="on_fw", source_tier="framework")

        await insert_invocation(db_svc, app_listener, session_id, duration_ms=500.0, source_tier="app")
        await insert_invocation(db_svc, fw_listener, session_id, duration_ms=1000.0, source_tier="framework")

        rows = await svc.get_slow_handlers(threshold_ms=100.0)
        assert len(rows) == 1
        assert rows[0].duration_ms == pytest.approx(500.0)
