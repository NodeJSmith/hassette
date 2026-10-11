"""Integration tests for DatabaseService's startup cleanup catch-up and long cleanup passes (#2266)."""

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import aiosqlite

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core import database_service as database_service_module
from hassette.core.database_service import DatabaseService
from hassette.core.database_sql import CLEANUP_PROGRESS_LOG_INTERVAL
from tests.support.helpers import SIZE_FAILSAFE_TRIGGER_MB, seed_listener_for_fk

ENDLESS_STATEMENT = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"
"""Unbounded recursive CTE: never terminates unless interrupted."""


def endless_delete_connect(statement_started: asyncio.Event) -> Any:
    """Build a connect_daemon replacement whose first DELETE runs an endless statement instead,
    occupying the real sqlite worker thread the way a huge batch or slow vacuum would.
    """
    real_connect_daemon = database_service_module.connect_daemon

    async def connect(*args: Any, **kwargs: Any) -> aiosqlite.Connection:
        conn = await real_connect_daemon(*args, **kwargs)
        real_execute = conn.execute

        async def endless_execute(sql: str, parameters: Any = None) -> aiosqlite.Cursor:
            if sql.strip().upper().startswith("DELETE FROM"):
                statement_started.set()
                return await real_execute(ENDLESS_STATEMENT)
            return await real_execute(sql, parameters)

        conn.execute = endless_execute
        return conn

    return connect


async def seed_stale_executions(service: DatabaseService, count: int) -> None:
    """Insert ``count`` committed handler executions one day past the configured retention window."""
    await seed_listener_for_fk(service.db)
    retention_days = service.hassette.config.database.retention_days
    old_ts = time.time() - ((retention_days + 1) * SECONDS_PER_DAY)
    for _ in range(count):
        await service.db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
            " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
            (service.hassette.session_id, old_ts),
        )
    await service.db.commit()


async def count_executions(service: DatabaseService) -> int:
    cursor = await service.db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row is not None
    return row[0]


async def test_startup_cleanup_timeout_interrupts_in_flight_statement(
    fresh_service: DatabaseService, mock_hassette_fresh: MagicMock
) -> None:
    """When the catch-up deadline fires mid-statement, the statement keeps running on aiosqlite's
    worker thread (cancelling the await doesn't stop it). The recovery rollback queues behind it,
    so without an interrupt on_initialize() would block past the half-budget it promises.
    """
    mock_hassette_fresh.config.lifecycle = mock_hassette_fresh.config.lifecycle.model_copy(
        update={"startup_timeout_seconds": 0.2}
    )
    mock_hassette_fresh.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    statement_started = asyncio.Event()
    connect = endless_delete_connect(statement_started)
    try:
        with patch.object(database_service_module, "connect_daemon", connect):
            await asyncio.wait_for(fresh_service.on_initialize(), timeout=5.0)

        assert statement_started.is_set(), "size failsafe never reached its DELETE statement"
    finally:
        await fresh_service.on_shutdown()


async def test_restart_resumes_interrupted_retention_on_startup(
    initialized_service: DatabaseService, db_hassette: MagicMock
) -> None:
    """A restart that leaves a stale backlog behind (the same state an interrupted retention
    pass leaves, since it commits per batch) gets it cleaned during on_initialize(), not a full
    retention interval later — serve() starts its interval clock fresh on every restart.
    """
    await seed_stale_executions(initialized_service, 5)

    # The service "dies" with the backlog still in place — the equivalent of a restart that
    # landed before the in-flight retention pass finished.
    await initialized_service.on_shutdown()

    restarted = DatabaseService(db_hassette, parent=None)
    await restarted.on_initialize()
    try:
        assert await count_executions(restarted) == 0, "startup did not resume retention cleanup of the stale backlog"
    finally:
        await restarted.on_shutdown()


async def test_retention_batch_loop_continues_past_progress_checkpoint(
    initialized_service: DatabaseService,
) -> None:
    """The retention batch loop doesn't stop at the CLEANUP_PROGRESS_LOG_INTERVAL checkpoint:
    a backlog needing more batches than that is still drained in one pass.
    """
    batches = CLEANUP_PROGRESS_LOG_INTERVAL + 2
    initialized_service.hassette.config.database.retention_delete_batch = 1
    await seed_stale_executions(initialized_service, batches)

    await initialized_service._do_run_retention_cleanup()

    assert await count_executions(initialized_service) == 0


async def test_size_failsafe_iteration_loop_continues_past_progress_checkpoint(
    initialized_service: DatabaseService,
) -> None:
    """The size failsafe iteration loop doesn't stop at the CLEANUP_PROGRESS_LOG_INTERVAL
    checkpoint: it keeps deleting until its iteration budget is spent.
    """
    iterations = CLEANUP_PROGRESS_LOG_INTERVAL + 2
    config = initialized_service.hassette.config.database
    config.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB
    config.size_failsafe_delete_batch = 1
    config.size_failsafe_max_iterations = iterations
    await seed_stale_executions(initialized_service, iterations + 3)

    await initialized_service._check_size_failsafe()

    assert await count_executions(initialized_service) == 3
