"""Integration tests for age-based retention of ``sessions`` rows (#2753)."""

import sqlite3
import time
from typing import Any
from unittest.mock import Mock

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService
from tests.support.helpers import seed_listener_for_fk
from tests.support.sql import count_rows, insert_execution_row


async def insert_session(db: aiosqlite.Connection, *, started_at: float, stopped_at: float | None) -> int:
    """Insert a session row and return its id."""
    status = "running" if stopped_at is None else "failure"
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, stopped_at, last_heartbeat_at, status, error_traceback)"
        " VALUES (?, ?, ?, ?, 'Traceback ...')",
        (started_at, stopped_at, stopped_at or started_at, status),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def session_ids(db: aiosqlite.Connection) -> set[int]:
    cursor = await db.execute("SELECT id FROM sessions")
    return {row[0] for row in await cursor.fetchall()}


@pytest.mark.parametrize("entry_point", ["_do_run_retention_cleanup", "catch_up_cleanup_at_startup"])
async def test_retention_deletes_only_old_unreferenced_sessions(
    initialized_service: DatabaseService, entry_point: str
) -> None:
    """Old stopped sessions with nothing referencing them are deleted; sessions still referenced by
    executions or blocking events, recent sessions, unstopped sessions, and the live session stay.
    """
    db = initialized_service.db
    retention_days = initialized_service.hassette.config.database.retention_days
    now = time.time()
    old_ts = now - (retention_days + 5) * SECONDS_PER_DAY
    recent_ts = now - 60

    await seed_listener_for_fk(db)
    unreferenced = await insert_session(db, started_at=old_ts, stopped_at=old_ts + 10)
    with_execution = await insert_session(db, started_at=old_ts, stopped_at=old_ts + 10)
    with_blocking_event = await insert_session(db, started_at=old_ts, stopped_at=old_ts + 10)
    unstopped_orphan = await insert_session(db, started_at=old_ts, stopped_at=None)
    recent = await insert_session(db, started_at=recent_ts, stopped_at=recent_ts + 10)
    # The live session id is protected even if its row somehow carries an old stopped_at.
    current = await insert_session(db, started_at=old_ts, stopped_at=old_ts + 10)
    initialized_service.hassette.try_session_id = Mock(return_value=current)

    # Children still inside their retention windows, so they survive the target deletes.
    await insert_execution_row(db, listener_id=1, session_id=with_execution, execution_start_ts=recent_ts)
    await db.execute(
        "INSERT INTO blocking_events (session_id, tier, detected_ts, source_tier)"
        " VALUES (?, 'watchdog', ?, 'framework')",
        (with_blocking_event, recent_ts),
    )
    await db.commit()
    fixture_session = initialized_service.hassette.session_id
    assert unreferenced in await session_ids(db)

    await getattr(initialized_service, entry_point)()

    survivors = {fixture_session, with_execution, with_blocking_event, unstopped_orphan, recent, current}
    assert await session_ids(db) == survivors


async def test_session_is_deleted_once_its_children_age_out(initialized_service: DatabaseService) -> None:
    """A session whose executions and blocking events are all past the cutoff is deleted in the
    same cycle that removes those children.
    """
    db = initialized_service.db
    retention_days = initialized_service.hassette.config.database.retention_days
    old_ts = time.time() - (retention_days + 5) * SECONDS_PER_DAY

    await seed_listener_for_fk(db)
    old_session = await insert_session(db, started_at=old_ts, stopped_at=old_ts + 10)
    await insert_execution_row(db, listener_id=1, session_id=old_session, execution_start_ts=old_ts)
    await db.execute(
        "INSERT INTO blocking_events (session_id, tier, detected_ts, source_tier)"
        " VALUES (?, 'watchdog', ?, 'framework')",
        (old_session, old_ts),
    )
    await db.commit()

    await initialized_service._do_run_retention_cleanup()

    assert old_session not in await session_ids(db)


async def test_sessions_delete_failure_does_not_break_other_targets(
    initialized_service: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing sessions delete rolls back the parent-guard transaction without undoing the
    target deletes already committed, and the next cycle retries it.
    """
    db = initialized_service.db
    retention_days = initialized_service.hassette.config.database.retention_days
    old_ts = time.time() - (retention_days + 5) * SECONDS_PER_DAY

    await seed_listener_for_fk(db)
    old_session = await insert_session(db, started_at=old_ts, stopped_at=old_ts + 10)
    await insert_execution_row(db, listener_id=1, session_id=old_session, execution_start_ts=old_ts)
    await db.commit()

    real_execute = db.execute

    async def failing_execute(sql: str, *args: Any, **kwargs: Any) -> aiosqlite.Cursor:
        if "DELETE FROM sessions" in sql:
            raise sqlite3.OperationalError("simulated sessions delete failure")
        return await real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(db, "execute", failing_execute)
    await initialized_service._do_run_retention_cleanup()

    assert await count_rows(db, "executions") == 0
    assert old_session in await session_ids(db)

    monkeypatch.setattr(db, "execute", real_execute)
    await initialized_service._do_run_retention_cleanup()

    assert old_session not in await session_ids(db)
