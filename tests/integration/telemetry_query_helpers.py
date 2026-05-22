"""Shared fixtures and insert helpers for TelemetryQueryService integration tests."""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.mock_hassette import make_mock_hassette

# Stable base timestamp (Jan 12 1970) — far from "now" for reproducible time comparisons.
BASE_TS = 1_000_000.0


@pytest.fixture
def db_hassette(premigrated_db_path: Path) -> MagicMock:
    """Variant of conftest.db_hassette with web_api enabled for telemetry query tests."""
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


async def insert_listener(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    handler_method: str = "on_event",
    topic: str = "hass.event.state_changed",
    source_tier: str = "app",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, ?, ?)""",
        (app_key, instance_index, handler_method, topic, TEST_SOURCE_LOCATION, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def insert_job(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    job_name: str = "my_job",
    handler_method: str = "run_job",
    source_tier: str = "app",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, repeat,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, 'interval', 1, ?, ?)""",
        (app_key, instance_index, job_name, handler_method, TEST_SOURCE_LOCATION, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def insert_invocation(
    db_svc: DatabaseService,
    listener_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 10.0,
    error_type: str | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
    is_di_failure: int = 0,
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO handler_invocations
               (listener_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, error_traceback, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            listener_id,
            session_id,
            ts,
            duration_ms,
            status,
            error_type,
            error_message,
            error_traceback,
            source_tier,
            is_di_failure,
        ),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def insert_execution(
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
    is_di_failure: int = 0,
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO job_executions
               (job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, session_id, ts, duration_ms, status, error_type, error_message, source_tier, is_di_failure),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid
