"""Integration tests for WP16 telemetry query additions:
- get_recent_errors includes source_location via JOIN
- get_activity_feed returns merged handler+job entries sorted by timestamp
- get_activity_buckets returns bucketed ok/err counts
- get_recent_invocations_1h returns count for a specific app
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_query_service import TelemetryQueryService

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_telemetry_query_service.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.web_api_log_level = "INFO"
    hassette.config.run_web_api = True
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    mock_hassette.session_id = session_id
    mock_hassette.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def svc(mock_hassette: MagicMock, db: tuple[DatabaseService, int]) -> TelemetryQueryService:  # noqa: ARG001
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = mock_hassette
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_listener(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    handler_method: str = "on_event",
    topic: str = "hass.event.state_changed",
    source_tier: str = "app",
    source_location: str = "test_app.py:1",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, ?, ?)""",
        (app_key, instance_index, handler_method, topic, source_location, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_job(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    job_name: str = "my_job",
    handler_method: str = "run_job",
    source_tier: str = "app",
    source_location: str = "test_app.py:50",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, repeat,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, 'interval', 1, ?, ?)""",
        (app_key, instance_index, job_name, handler_method, source_location, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_invocation(
    db_svc: DatabaseService,
    listener_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 10.0,
    error_type: str | None = None,
    error_message: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO handler_invocations
               (listener_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (listener_id, session_id, ts, duration_ms, status, error_type, error_message, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_execution(
    db_svc: DatabaseService,
    job_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 20.0,
    error_type: str | None = None,
    error_message: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO job_executions
               (job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (job_id, session_id, ts, duration_ms, status, error_type, error_message, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Subtask 3: source_location in get_recent_errors
# ---------------------------------------------------------------------------


class TestGetRecentErrorsWithSourceLocation:
    async def test_handler_error_includes_source_location(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_recent_errors returns source_location from listeners table."""
        db_svc, session_id = db
        listener_id = await _insert_listener(
            db_svc,
            app_key="loc_app",
            source_location="loc_app.py:42",
        )
        await _insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="ValueError",
            execution_start_ts=time.time() - 10.0,
        )

        errors = await svc.get_recent_errors(since_ts=time.time() - 3600.0)
        assert len(errors) == 1
        assert errors[0].source_location == "loc_app.py:42"

    async def test_job_error_includes_source_location(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_recent_errors returns source_location from scheduled_jobs table for job errors."""
        db_svc, session_id = db
        job_id = await _insert_job(
            db_svc,
            app_key="job_app",
            source_location="job_app.py:99",
        )
        await _insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="RuntimeError",
            execution_start_ts=time.time() - 5.0,
        )

        errors = await svc.get_recent_errors(since_ts=time.time() - 3600.0)
        assert len(errors) == 1
        assert errors[0].source_location == "job_app.py:99"

    async def test_handler_error_source_location_null_when_listener_deleted(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Orphaned handler errors (listener deleted) have source_location=None."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, app_key="orphan_app")

        # Insert invocation, then delete the listener row
        await _insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            execution_start_ts=time.time() - 5.0,
        )
        await db_svc.db.execute("DELETE FROM listeners WHERE id = ?", (listener_id,))
        await db_svc.db.commit()

        errors = await svc.get_recent_errors(since_ts=time.time() - 3600.0)
        assert len(errors) == 1
        assert errors[0].source_location is None


# ---------------------------------------------------------------------------
# Subtask 6: get_activity_feed
# ---------------------------------------------------------------------------


class TestGetActivityFeed:
    async def test_returns_handler_invocations(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_activity_feed returns handler invocations as 'handler' kind entries."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, app_key="feed_app", handler_method="on_motion")
        await _insert_invocation(
            db_svc, listener_id, session_id, status="success", execution_start_ts=time.time() - 30.0
        )

        entries = await svc.get_activity_feed()
        assert len(entries) == 1
        assert entries[0].kind == "handler"
        assert entries[0].app_key == "feed_app"
        assert entries[0].handler_name == "on_motion"
        assert entries[0].status == "success"

    async def test_returns_job_executions(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_activity_feed returns job executions as 'job' kind entries."""
        db_svc, session_id = db
        job_id = await _insert_job(db_svc, app_key="feed_app", handler_method="run_report")
        await _insert_execution(db_svc, job_id, session_id, status="success", execution_start_ts=time.time() - 10.0)

        entries = await svc.get_activity_feed()
        assert len(entries) == 1
        assert entries[0].kind == "job"
        assert entries[0].app_key == "feed_app"
        assert entries[0].handler_name == "run_report"

    async def test_merged_sorted_by_timestamp_descending(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler and job entries are merged and sorted by timestamp descending."""
        db_svc, session_id = db
        now = time.time()

        listener_id = await _insert_listener(db_svc, app_key="sort_app")
        job_id = await _insert_job(db_svc, app_key="sort_app")

        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 30.0)
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 10.0)
        await _insert_execution(db_svc, job_id, session_id, execution_start_ts=now - 20.0)

        entries = await svc.get_activity_feed()
        assert len(entries) == 3
        timestamps = [e.timestamp for e in entries]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_respects_limit(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_activity_feed respects the limit parameter."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)
        now = time.time()

        for i in range(5):
            await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - i)

        entries = await svc.get_activity_feed(limit=3)
        assert len(entries) == 3

    async def test_respects_since_filter(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_activity_feed filters by since timestamp."""
        db_svc, session_id = db
        now = time.time()
        listener_id = await _insert_listener(db_svc)

        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 7200.0)
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 10.0)

        entries = await svc.get_activity_feed(since=now - 3600.0)
        assert len(entries) == 1
        assert entries[0].timestamp == pytest.approx(now - 10.0, abs=1.0)

    async def test_empty_when_no_data(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_activity_feed returns an empty list when no data exists."""
        entries = await svc.get_activity_feed()
        assert entries == []


# ---------------------------------------------------------------------------
# Subtask 7: get_activity_buckets
# ---------------------------------------------------------------------------


class TestGetActivityBuckets:
    async def test_returns_twelve_buckets(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_activity_buckets returns exactly 12 buckets."""
        now = time.time()
        buckets = await svc.get_activity_buckets(since=now - 3600.0, now=now)
        assert len(buckets) == 12

    async def test_counts_ok_in_correct_bucket(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Successful invocations are counted as ok in the correct bucket."""
        db_svc, session_id = db
        now = time.time()
        since = now - 3600.0
        # Place one invocation at the start of the window → bucket 0
        # And one at the end → bucket 11
        listener_id = await _insert_listener(db_svc)
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=since + 1.0)
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 1.0)

        buckets = await svc.get_activity_buckets(since=since, now=now)
        assert len(buckets) == 12
        total_ok = sum(b[0] for b in buckets)
        assert total_ok == 2

    async def test_counts_errors_as_err(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Error invocations are counted as err."""
        db_svc, session_id = db
        now = time.time()
        since = now - 3600.0
        listener_id = await _insert_listener(db_svc)
        await _insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            execution_start_ts=now - 100.0,
        )

        buckets = await svc.get_activity_buckets(since=since, now=now)
        total_err = sum(b[1] for b in buckets)
        assert total_err == 1

    async def test_all_zero_when_no_data(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All buckets are zero when no data exists in the window."""
        now = time.time()
        buckets = await svc.get_activity_buckets(since=now - 3600.0, now=now)
        assert all(b == (0, 0) for b in buckets)

    async def test_includes_job_executions(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Job executions are included in bucket counts."""
        db_svc, session_id = db
        now = time.time()
        since = now - 3600.0
        job_id = await _insert_job(db_svc)
        await _insert_execution(db_svc, job_id, session_id, execution_start_ts=now - 100.0)

        buckets = await svc.get_activity_buckets(since=since, now=now)
        total_ok = sum(b[0] for b in buckets)
        assert total_ok == 1


# ---------------------------------------------------------------------------
# Subtask 4: get_recent_invocations_1h
# ---------------------------------------------------------------------------


class TestGetRecentInvocations1h:
    async def test_returns_count_for_app(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_recent_invocations_1h returns invocations within the last hour for the given app."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, app_key="my_app")

        now = time.time()
        # Two within the hour, one outside
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 100.0)
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 1800.0)
        await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=now - 7200.0)

        count = await svc.get_recent_invocations_1h(app_key="my_app")
        assert count == 2

    async def test_returns_zero_for_unknown_app(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_recent_invocations_1h returns 0 for an app with no data."""
        count = await svc.get_recent_invocations_1h(app_key="nonexistent_app")
        assert count == 0

    async def test_isolates_by_app_key(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_recent_invocations_1h only counts invocations for the specified app."""
        db_svc, session_id = db
        now = time.time()

        listener_a = await _insert_listener(db_svc, app_key="app_a")
        listener_b = await _insert_listener(db_svc, app_key="app_b")

        await _insert_invocation(db_svc, listener_a, session_id, execution_start_ts=now - 100.0)
        await _insert_invocation(db_svc, listener_a, session_id, execution_start_ts=now - 200.0)
        await _insert_invocation(db_svc, listener_b, session_id, execution_start_ts=now - 150.0)

        count_a = await svc.get_recent_invocations_1h(app_key="app_a")
        count_b = await svc.get_recent_invocations_1h(app_key="app_b")

        assert count_a == 2
        assert count_b == 1
