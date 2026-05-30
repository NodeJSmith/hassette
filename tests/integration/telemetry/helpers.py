"""Insert helpers for telemetry integration tests."""

import time

from hassette.core.database_service import DatabaseService
from hassette.test_utils.config import TEST_SOURCE_LOCATION

BASE_TS = 1_000_000.0


async def insert_listener(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    name: str = "test_listener",
    handler_method: str = "on_event",
    topic: str = "hass.event.state_changed",
    source_tier: str = "app",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, name, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, 0, ?, ?)""",
        (app_key, instance_index, name, handler_method, topic, TEST_SOURCE_LOCATION, source_tier),
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
        """INSERT INTO executions
               (kind, listener_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, error_traceback, source_tier, is_di_failure)
           VALUES ('handler', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
    error_traceback: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
    is_di_failure: int = 0,
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO executions
               (kind, job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, error_traceback, source_tier, is_di_failure)
           VALUES ('job', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
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
