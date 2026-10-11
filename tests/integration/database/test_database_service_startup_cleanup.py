"""Integration tests for DatabaseService's startup cleanup catch-up and active-cleanup tracking (#2266)."""

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import aiosqlite

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core import database_service as database_service_module
from hassette.core.database_service import DatabaseService
from tests.support.helpers import SIZE_FAILSAFE_TRIGGER_MB, async_noop, seed_listener_for_fk

ENDLESS_STATEMENT = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"
"""Unbounded recursive CTE: never terminates unless interrupted."""


def endless_delete_connect(
    statement_started: asyncio.Event, real_interrupts: list[Any], *, ignore_interrupt: bool
) -> Any:
    """Build a connect_daemon replacement whose first DELETE runs an endless statement instead,
    occupying the real sqlite worker thread the way a huge batch or slow vacuum would.

    Each connection's real interrupt() is appended to ``real_interrupts`` so the test can free the
    worker before shutdown. ``ignore_interrupt`` makes the service's own interrupt() a no-op.
    """
    real_connect_daemon = database_service_module.connect_daemon

    async def connect(*args: Any, **kwargs: Any) -> aiosqlite.Connection:
        conn = await real_connect_daemon(*args, **kwargs)
        real_execute = conn.execute
        real_interrupts.append(conn.interrupt)

        async def endless_execute(sql: str, parameters: Any = None) -> aiosqlite.Cursor:
            if sql.strip().upper().startswith("DELETE FROM"):
                statement_started.set()
                return await real_execute(ENDLESS_STATEMENT)
            return await real_execute(sql, parameters)

        conn.execute = endless_execute
        if ignore_interrupt:
            conn.interrupt = async_noop
        return conn

    return connect


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
    connect = endless_delete_connect(statement_started, [], ignore_interrupt=False)
    with patch.object(database_service_module, "connect_daemon", connect):
        await asyncio.wait_for(fresh_service.on_initialize(), timeout=5.0)

    assert statement_started.is_set(), "size failsafe never reached its DELETE statement"

    await fresh_service.on_shutdown()


async def test_startup_cleanup_recovery_stays_within_readiness_budget(
    fresh_service: DatabaseService, mock_hassette_fresh: MagicMock
) -> None:
    """If the interrupt fails to free the sqlite worker, the recovery rollback queues behind the
    still-running statement until its own bound expires. That bound must come out of the same
    startup budget as the catch-up, or on_initialize() overruns the readiness deadline that
    wait_for_ready() enforces.
    """
    # Generous enough that migrations plus the cleanup budget (half of this) fit with CI headroom,
    # yet far short of the half-budget plus a fixed multi-second rollback wait on top of it.
    startup_timeout = 4.0
    mock_hassette_fresh.config.lifecycle = mock_hassette_fresh.config.lifecycle.model_copy(
        update={"startup_timeout_seconds": startup_timeout}
    )
    mock_hassette_fresh.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    statement_started = asyncio.Event()
    real_interrupts: list[Any] = []
    connect = endless_delete_connect(statement_started, real_interrupts, ignore_interrupt=True)
    loop = asyncio.get_running_loop()
    with patch.object(database_service_module, "connect_daemon", connect):
        started = loop.time()
        try:
            await asyncio.wait_for(fresh_service.on_initialize(), timeout=10.0)
            elapsed = loop.time() - started
        finally:
            # Free the worker thread so shutdown's close() isn't queued behind the endless statement.
            for interrupt in real_interrupts:
                await interrupt()

    assert statement_started.is_set(), "size failsafe never reached its DELETE statement"
    assert elapsed < startup_timeout, f"on_initialize() took {elapsed:.2f}s, past the {startup_timeout}s budget"

    await fresh_service.on_shutdown()


async def test_restart_resumes_interrupted_retention_on_startup(
    initialized_service: DatabaseService, db_hassette: MagicMock
) -> None:
    """A restart that leaves a stale backlog behind (the same state an interrupted retention
    pass leaves, since it commits per batch) gets it cleaned during on_initialize(), not a full
    retention interval later — serve() starts its interval clock fresh on every restart.
    """
    session_id = initialized_service.hassette.session_id
    await seed_listener_for_fk(initialized_service.db)
    old_ts = time.time() - (8 * SECONDS_PER_DAY)  # past the 7-day retention window
    for _ in range(5):
        await initialized_service.db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
            " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
            (session_id, old_ts),
        )
    await initialized_service.db.commit()

    # The service "dies" with the backlog still in place — the equivalent of a restart that
    # landed before the in-flight retention pass finished.
    await initialized_service.on_shutdown()

    restarted = DatabaseService(db_hassette, parent=None)
    await restarted.on_initialize()
    try:
        cursor = await restarted.db.execute("SELECT COUNT(*) FROM executions")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0, "startup did not resume retention cleanup of the stale backlog"
        assert restarted._active_cleanup is None
    finally:
        await restarted.on_shutdown()


async def test_active_cleanup_names_the_pass_holding_the_write_worker(
    initialized_service: DatabaseService,
) -> None:
    """While a retention pass occupies the write worker, _active_cleanup names it, so a heartbeat
    that times out behind it is attributable to that pass rather than an unexplained wedge.
    """
    session_id = initialized_service.hassette.session_id
    await seed_listener_for_fk(initialized_service.db)
    await initialized_service.db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
        (session_id, time.time() - (8 * SECONDS_PER_DAY)),
    )
    await initialized_service.db.commit()

    gate = asyncio.Event()
    delete_reached = asyncio.Event()
    real_execute = initialized_service.db.execute

    async def gated_execute(sql: str, parameters: Any = None) -> aiosqlite.Cursor:
        if sql.strip().upper().startswith("DELETE FROM"):
            delete_reached.set()
            await gate.wait()
        return await real_execute(sql, parameters)

    with patch.object(initialized_service.db, "execute", gated_execute):
        assert await initialized_service.run_retention_cleanup() is True
        await asyncio.wait_for(delete_reached.wait(), timeout=2)
        assert initialized_service._active_cleanup == "retention cleanup"

        with patch("hassette.core.database_service._HEARTBEAT_WRITE_TIMEOUT_SECONDS", 0.05):
            await initialized_service.update_heartbeat()
        assert initialized_service._consecutive_heartbeat_failures == 1

        gate.set()
        assert initialized_service._db_write_queue is not None
        await asyncio.wait_for(initialized_service._db_write_queue.join(), timeout=2)

    assert initialized_service._active_cleanup is None
