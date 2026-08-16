"""Insert helpers for telemetry integration tests."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import aiosqlite
import pytest

from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.execution_models import ActivityFeedEntry
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.types.types import QuerySourceTier

BASE_TS = 1_000_000.0

DbFixture = tuple[DatabaseService, int]
"""What the ``db`` fixture yields: an initialized ``DatabaseService`` and its seeded session id."""

RowT = TypeVar("RowT")


async def commit_returning_id(db_svc: DatabaseService, cursor: aiosqlite.Cursor) -> int:
    """Commit ``cursor``'s pending INSERT and return the row id it produced."""
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def open_db_with_session(hassette: Any) -> tuple[DatabaseService, int]:
    """Initialize a ``DatabaseService`` against ``hassette`` and seed one running session row.

    Returns:
        Tuple of (DatabaseService instance, session_id). The caller owns shutdown.
    """
    db_service = DatabaseService(hassette, parent=None)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    assert session_id is not None
    return db_service, session_id


@asynccontextmanager
async def running_command_executor(hassette: Any) -> AsyncIterator[CommandExecutor]:
    """Yield an initialized ``CommandExecutor``, shutting it down on exit.

    ``parent=None`` matches how the telemetry conftest wires ``DatabaseService``, avoiding the
    sealed-mock ``unique_name`` issue.
    """
    exc = CommandExecutor(hassette, parent=None)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


async def only_row(query: Awaitable[Sequence[RowT]]) -> RowT:
    """Await ``query`` and return its single row, asserting there is exactly one."""
    rows = await query
    assert len(rows) == 1, f"expected exactly 1 row, got {len(rows)}"
    return rows[0]


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
    return await commit_returning_id(db_svc, cursor)


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
    return await commit_returning_id(db_svc, cursor)


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
    return await commit_returning_id(db_svc, cursor)


async def insert_listener_and_job(db_svc: DatabaseService, *, app_key: str = "test_app") -> tuple[int, int]:
    """Insert one listener and one job for ``app_key`` — the two arms every UNION query merges.

    Returns:
        Tuple of (listener_id, job_id).
    """
    listener_id = await insert_listener(db_svc, app_key=app_key, handler_method="on_event")
    job_id = await insert_job(db_svc, app_key=app_key, job_name="my_job", handler_method="run_job")
    return listener_id, job_id


async def insert_tiered_listeners(db_svc: DatabaseService, *, app_key: str = "test_app") -> tuple[int, int]:
    """Insert an app-tier and a framework-tier listener under the same ``app_key``.

    Returns:
        Tuple of (app_tier_listener_id, framework_tier_listener_id).
    """
    app_listener = await insert_listener(db_svc, app_key=app_key, handler_method="on_app", source_tier="app")
    fw_listener = await insert_listener(db_svc, app_key=app_key, handler_method="on_fw", source_tier="framework")
    return app_listener, fw_listener


def error_row(
    error_type: str, error_message: str, error_traceback: str | None, execution_start_ts: float
) -> dict[str, Any]:
    """Build one entry for ``assert_last_error_row_coherence``'s ``error_rows`` argument."""
    return {
        "error_type": error_type,
        "error_message": error_message,
        "error_traceback": error_traceback,
        "execution_start_ts": execution_start_ts,
    }


SINCE_WINDOW_ERROR_ROWS: tuple[dict[str, Any], ...] = (
    error_row("OldError", "before window", "old tb", BASE_TS + 1.0),
    error_row("NewError", "inside window", "new tb", BASE_TS + 100.0),
)
"""One error either side of a ``since=BASE_TS + 50.0`` window, for the ``since``-scoping tests."""


def assert_no_last_error(row: Any) -> None:
    """Assert every ``last_error_*`` field the row exposes is None.

    ``JobSummary`` exposes ``last_error_ts`` and ``ListenerSummary`` doesn't, so this checks that
    one only when present — same accommodation ``assert_last_error_row_coherence`` makes.
    """
    assert row.last_error_type is None
    assert row.last_error_message is None
    assert row.last_error_traceback is None
    if hasattr(row, "last_error_ts"):
        assert row.last_error_ts is None


async def insert_app_listener_pair(db_svc: DatabaseService) -> tuple[int, int]:
    """Insert one app-tier listener each under ``app_a`` and ``app_b``, for cross-app isolation tests.

    Returns:
        Tuple of (app_a_listener_id, app_b_listener_id).
    """
    listener_a = await insert_listener(db_svc, app_key="app_a", handler_method="on_a")
    listener_b = await insert_listener(db_svc, app_key="app_b", handler_method="on_b")
    return listener_a, listener_b


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
    return await commit_returning_id(db_svc, cursor)


async def recent_activity(
    query_service: TelemetryQueryService,
    *,
    app_key: str = "test_app",
    instance_index: int | None = None,
    limit: int = 50,
    since: float | None = None,
    source_tier: QuerySourceTier = "app",
) -> list[ActivityFeedEntry]:
    """Call ``get_app_recent_activity`` with the defaults the union tests share.

    Every argument on the real method is required, so spelling all five out at each call site
    buried the one or two that a given test actually varies.
    """
    return await query_service.get_app_recent_activity(
        app_key=app_key, instance_index=instance_index, limit=limit, since=since, source_tier=source_tier
    )
