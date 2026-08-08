"""Insert helpers for telemetry integration tests."""

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest

from hassette.core.database_service import DatabaseService
from hassette.test_utils.config import TEST_SOURCE_LOCATION

BASE_TS = 1_000_000.0


async def insert_listener(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    name: str | None = None,
    handler_method: str = "on_event",
    topic: str = "hass.event.state_changed",
    source_tier: str = "app",
) -> int:
    # Default the natural-key name to handler_method so callers that vary handler_method
    # (the pre-unification discriminator) get distinct names and don't collide on the
    # (app_key, instance_index, name, topic) unique index.
    name = name if name is not None else handler_method
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
    schedule_status: str = "scheduled",
) -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, repeat,
                source_location, source_tier, schedule_status)
           VALUES (?, ?, ?, ?, 'interval', 1, ?, ?, ?)""",
        (app_key, instance_index, job_name, handler_method, TEST_SOURCE_LOCATION, source_tier, schedule_status),
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
    thread_leaked: int = 0,
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO executions
               (kind, listener_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, error_traceback, source_tier, is_di_failure,
                thread_leaked)
           VALUES ('handler', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            thread_leaked,
        ),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def assert_last_error_row_coherence(
    insert_row: Callable[..., Awaitable[int]],
    query_fn: Callable[[], Awaitable[Sequence[Any]]],
    error_rows: Sequence[dict[str, Any]],
    *,
    trailing_success_ts: float | None = None,
) -> None:
    """Assert that ``last_error_*`` fields on the row returned by ``query_fn`` all come from
    the most recently inserted error row, not a mix of columns from different error rows.

    This is the "row coherence" shape shared by ``get_job_summary()`` and
    ``get_listener_summary()``: both use a ``ROW_NUMBER() OVER (PARTITION BY ... ORDER BY
    execution_start_ts DESC)`` CTE to pick one error row per entity, and the risk this guards
    against is that CTE picking columns from different rows instead of one coherent row.

    Args:
        insert_row: Async callable already bound to the entity (job/listener), db, and
            session — e.g. ``lambda **kw: insert_execution(db_svc, job_id, session_id, **kw)``.
            Called once per entry in ``error_rows`` with ``status="error"`` plus that entry's
            kwargs, then once more for ``trailing_success_ts`` (with ``status="success"``) if given.
        query_fn: Zero-arg async callable already bound to the query, scope (global or
            per-instance), and any ``since`` filter — e.g.
            ``lambda: query_service.get_job_summary(since=since_ts)``.
        error_rows: Error rows to insert, ordered oldest to newest. Each dict must set at least
            ``error_type``, ``error_message``, ``error_traceback``, and ``execution_start_ts``.
            The last entry is the one the assertions expect to win.
        trailing_success_ts: If given, insert a success row at this timestamp after all error
            rows — proves a later success doesn't clear or overwrite the last_error_* columns.
    """
    for kw in error_rows:
        await insert_row(status="error", **kw)
    if trailing_success_ts is not None:
        await insert_row(status="success", execution_start_ts=trailing_success_ts)

    results = await query_fn()
    assert len(results) == 1
    row = results[0]
    newest = error_rows[-1]
    assert row.last_error_type == newest["error_type"]
    assert row.last_error_message == newest["error_message"]
    assert row.last_error_traceback == newest["error_traceback"]
    # JobSummary exposes last_error_ts; ListenerSummary doesn't declare the field at all —
    # check it whenever the returned row actually has it, rather than asking every caller
    # to remember which query type does.
    if hasattr(row, "last_error_ts"):
        assert row.last_error_ts == pytest.approx(newest["execution_start_ts"])


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
    thread_leaked: int = 0,
) -> int:
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO executions
               (kind, job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, error_traceback, source_tier, is_di_failure,
                thread_leaked)
           VALUES ('job', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            thread_leaked,
        ),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid
