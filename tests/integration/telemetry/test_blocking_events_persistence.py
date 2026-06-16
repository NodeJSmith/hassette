"""Integration tests for blocking_events persistence (T05).

Covers:
    AC#7 (FR#10): one detected event → exactly one blocking_events row with correct
        tier and tier-appropriate columns populated/null.
    AC#8 (FR#11): event with unresolved owner (app_key=None) → one row with
        source_tier='framework' and null app_key, NOT dropped.

Threading invariant: record_blocking_event() always runs on the loop thread.
Tier 1 marshals via call_soon_threadsafe; Tier 2 calls directly (already on loop).
"""

import asyncio
import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from hassette.core.block_io_guard import MonkeypatchEvent
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.loop_watchdog import WatchdogEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def executor(
    db_hassette: MagicMock,
    db: tuple[DatabaseService, int],
) -> AsyncIterator[CommandExecutor]:
    """CommandExecutor wired with the telemetry conftest's real DB and session.

    Uses parent=None to match how the telemetry conftest wires DatabaseService,
    avoiding the sealed-mock unique_name issue.
    """
    _db_service, _session_id = db
    exc = CommandExecutor(db_hassette, parent=None)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_watchdog_event(*, app_key: str | None = "my_app", stall_ms: float = 250.0) -> WatchdogEvent:
    return WatchdogEvent(
        app_key=app_key,
        instance_name="my_app_instance" if app_key else None,
        instance_index=0 if app_key else None,
        execution_id="exec-uuid-watchdog",
        stall_duration_ms=stall_ms,
        tier="watchdog",
        stack_text='  File "my_app.py", line 42, in on_event (my_app)',
        detected_at=time.time(),
    )


def _make_monkeypatch_event(*, app_key: str | None = "my_app") -> MonkeypatchEvent:
    return MonkeypatchEvent(
        primitive="time.sleep",
        source_location="my_app.py:99",
        app_key=app_key,
        instance_name="my_app_instance" if app_key else None,
        instance_index=0 if app_key else None,
        execution_id="exec-uuid-monkeypatch" if app_key else None,
        tier="monkeypatch",
        detected_at=time.time(),
    )


async def _drain_tasks() -> None:
    """Wait for spawned record_blocking_event tasks and their DB writes to finish.

    record_blocking_event() spawns asyncio tasks that call database_service.submit(),
    which serializes through the DB write worker. The tasks complete very quickly
    (spawned tasks have no pending_tasks() entries by the time we reach the first
    await), so we simply yield to the event loop long enough for the DB worker to
    process all enqueued INSERT statements.
    """
    # A brief yield is sufficient: spawned tasks schedule immediately and the DB
    # write worker drains the queue in the same event-loop turn or the next.
    await asyncio.sleep(0.05)


async def _fetch_blocking_events(db_svc: DatabaseService) -> list[dict]:
    """Fetch all rows from blocking_events as plain dicts."""
    cursor = await db_svc.db.execute("SELECT * FROM blocking_events ORDER BY id")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# AC#7 / FR#10: Tier 1 (watchdog) — exactly one row, correct columns
# ---------------------------------------------------------------------------


class TestTier1Persistence:
    async def test_watchdog_event_inserts_one_row(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """AC#7: one WatchdogEvent → exactly one blocking_events row."""
        db_svc, session_id = db
        event = _make_watchdog_event(stall_ms=300.0)

        executor.record_blocking_event(event)
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 1

        row = rows[0]
        assert row["tier"] == "watchdog"
        assert row["app_key"] == "my_app"
        assert row["stall_duration_ms"] == pytest.approx(300.0)
        assert row["primitive"] is None  # Tier 1 has no primitive
        assert row["source_tier"] == "app"
        assert row["session_id"] == session_id
        assert row["execution_id"] == "exec-uuid-watchdog"

    async def test_watchdog_stack_stored_in_source_location(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Tier 1 stack text is stored in source_location column."""
        db_svc, _ = db
        stack = '  File "my_app.py", line 42, in on_event (my_app)'
        event = WatchdogEvent(
            app_key="my_app",
            instance_name=None,
            instance_index=0,
            execution_id="exec-1",
            stall_duration_ms=150.0,
            tier="watchdog",
            stack_text=stack,
            detected_at=time.time(),
        )

        executor.record_blocking_event(event)
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 1
        assert rows[0]["source_location"] == stack

    async def test_watchdog_no_stack_source_location_is_null(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Tier 1 with no stack → source_location is NULL."""
        db_svc, _ = db
        event = WatchdogEvent(
            app_key="my_app",
            instance_name=None,
            instance_index=0,
            execution_id="exec-1",
            stall_duration_ms=150.0,
            tier="watchdog",
            stack_text=None,
            detected_at=time.time(),
        )

        executor.record_blocking_event(event)
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert rows[0]["source_location"] is None


# ---------------------------------------------------------------------------
# AC#7 / FR#10: Tier 2 (monkeypatch) — exactly one row, correct columns
# ---------------------------------------------------------------------------


class TestTier2Persistence:
    async def test_monkeypatch_event_inserts_one_row(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """AC#7: one MonkeypatchEvent → exactly one blocking_events row."""
        db_svc, session_id = db
        event = _make_monkeypatch_event()

        executor.record_blocking_event(event)
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 1

        row = rows[0]
        assert row["tier"] == "monkeypatch"
        assert row["app_key"] == "my_app"
        assert row["primitive"] == "time.sleep"
        assert row["source_location"] == "my_app.py:99"
        assert row["stall_duration_ms"] is None  # Tier 2 has no stall duration
        assert row["source_tier"] == "app"
        assert row["session_id"] == session_id
        assert row["execution_id"] == "exec-uuid-monkeypatch"

    async def test_two_events_two_rows(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Two separate events produce two separate rows."""
        db_svc, _ = db

        executor.record_blocking_event(_make_watchdog_event(stall_ms=100.0))
        executor.record_blocking_event(_make_monkeypatch_event())
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 2
        tiers = {r["tier"] for r in rows}
        assert tiers == {"watchdog", "monkeypatch"}


# ---------------------------------------------------------------------------
# AC#8 / FR#11: Unresolved owner → source_tier='framework', not dropped
# ---------------------------------------------------------------------------


class TestUnresolvedOwnerPersistence:
    async def test_watchdog_unresolved_owner_recorded_as_framework(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """AC#8: WatchdogEvent with app_key=None → row with source_tier='framework', NOT dropped."""
        db_svc, _ = db
        event = _make_watchdog_event(app_key=None)

        executor.record_blocking_event(event)
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 1, "Unresolved owner must NOT be dropped"

        row = rows[0]
        assert row["app_key"] is None
        assert row["source_tier"] == "framework"
        assert row["tier"] == "watchdog"
        assert row["stall_duration_ms"] is not None

    async def test_monkeypatch_unresolved_owner_recorded_as_framework(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """AC#8: MonkeypatchEvent with app_key=None → row with source_tier='framework', NOT dropped."""
        db_svc, _ = db
        event = _make_monkeypatch_event(app_key=None)

        executor.record_blocking_event(event)
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 1, "Unresolved owner must NOT be dropped"

        row = rows[0]
        assert row["app_key"] is None
        assert row["source_tier"] == "framework"
        assert row["tier"] == "monkeypatch"
        assert row["primitive"] == "time.sleep"

    async def test_both_unresolved_events_are_framework_attributed(
        self,
        executor: CommandExecutor,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Both tier flavors with app_key=None produce framework-attributed rows."""
        db_svc, _ = db

        executor.record_blocking_event(_make_watchdog_event(app_key=None))
        executor.record_blocking_event(_make_monkeypatch_event(app_key=None))
        await _drain_tasks()

        rows = await _fetch_blocking_events(db_svc)
        assert len(rows) == 2
        assert all(r["source_tier"] == "framework" for r in rows)
        assert all(r["app_key"] is None for r in rows)
