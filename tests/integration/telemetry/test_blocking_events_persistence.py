"""Integration tests for blocking_events persistence.

Covers:
    One detected event → exactly one blocking_events row with correct
        tier and tier-appropriate columns populated/null.
    Event with unresolved owner (app_key=None) → one row with
        source_tier='framework' and null app_key, NOT dropped.

Threading invariant: record_blocking_event() always runs on the loop thread.
Tier 1 marshals via call_soon_threadsafe; Tier 2 calls directly (already on loop).
"""

import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from hassette.core.block_io_guard import MonkeypatchEvent
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.loop_watchdog import WatchdogEvent

from .helpers import DbFixture, drain_db_writes, fetch_blocking_events, running_command_executor


@pytest.fixture
async def executor(db_hassette: MagicMock, db: DbFixture) -> AsyncIterator[CommandExecutor]:
    """CommandExecutor wired with the telemetry conftest's real DB and session.

    Uses parent=None to match how the telemetry conftest wires DatabaseService,
    avoiding the sealed-mock unique_name issue.
    """
    _db_service, _session_id = db
    async with running_command_executor(db_hassette) as exc:
        yield exc


def _make_watchdog_event(*, app_key: str | None = "my_app", stall_ms: float = 250.0) -> WatchdogEvent:
    return WatchdogEvent(
        app_key=app_key,
        instance_name="my_app_instance" if app_key else None,
        instance_index=0 if app_key else None,
        execution_id="exec-uuid-watchdog" if app_key else None,
        stall_duration_ms=stall_ms,
        tier="watchdog",
        stack_text='  File "my_app.py", line 42, in on_event (my_app)',
        detected_at=time.time(),
        reason="attributed" if app_key else "framework",
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
        reason="attributed" if app_key else "framework",
    )


async def _record_and_fetch(
    executor: CommandExecutor, db_svc: DatabaseService, event: WatchdogEvent | MonkeypatchEvent
) -> list[dict]:
    """Record one blocking event, wait for its DB write to drain, and return all persisted rows."""
    executor.record_blocking_event(event)
    await drain_db_writes(db_svc)
    return await fetch_blocking_events(db_svc)


class TestTier1Persistence:
    async def test_watchdog_event_inserts_one_row(self, executor: CommandExecutor, db: DbFixture) -> None:
        """One WatchdogEvent → exactly one blocking_events row."""
        db_svc, session_id = db
        event = _make_watchdog_event(stall_ms=300.0)

        rows = await _record_and_fetch(executor, db_svc, event)
        assert len(rows) == 1

        row = rows[0]
        assert row["tier"] == "watchdog"
        assert row["app_key"] == "my_app"
        assert row["stall_duration_ms"] == pytest.approx(300.0)
        assert row["primitive"] is None  # Tier 1 has no primitive
        assert row["source_tier"] == "app"
        assert row["session_id"] == session_id
        assert row["execution_id"] == "exec-uuid-watchdog"
        assert row["reason"] == "attributed"

    async def test_watchdog_stack_stored_in_source_location(self, executor: CommandExecutor, db: DbFixture) -> None:
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
            reason="attributed",
        )

        rows = await _record_and_fetch(executor, db_svc, event)
        assert len(rows) == 1
        assert rows[0]["source_location"] == stack

    async def test_watchdog_no_stack_source_location_is_null(self, executor: CommandExecutor, db: DbFixture) -> None:
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
            reason="attributed",
        )

        rows = await _record_and_fetch(executor, db_svc, event)
        assert rows[0]["source_location"] is None


class TestTier2Persistence:
    async def test_monkeypatch_event_inserts_one_row(self, executor: CommandExecutor, db: DbFixture) -> None:
        """One MonkeypatchEvent → exactly one blocking_events row."""
        db_svc, session_id = db
        event = _make_monkeypatch_event()

        rows = await _record_and_fetch(executor, db_svc, event)
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
        assert row["reason"] == "attributed"

    async def test_two_events_two_rows(self, executor: CommandExecutor, db: DbFixture) -> None:
        """Two separate events produce two separate rows."""
        db_svc, _ = db

        executor.record_blocking_event(_make_watchdog_event(stall_ms=100.0))
        executor.record_blocking_event(_make_monkeypatch_event())
        await drain_db_writes(db_svc)

        rows = await fetch_blocking_events(db_svc)
        assert len(rows) == 2
        tiers = {r["tier"] for r in rows}
        assert tiers == {"watchdog", "monkeypatch"}


class TestUnresolvedOwnerPersistence:
    async def test_watchdog_unresolved_owner_recorded_as_framework(
        self, executor: CommandExecutor, db: DbFixture
    ) -> None:
        """WatchdogEvent with app_key=None → row with source_tier='framework', NOT dropped."""
        db_svc, _ = db
        event = _make_watchdog_event(app_key=None)

        rows = await _record_and_fetch(executor, db_svc, event)
        assert len(rows) == 1, "Unresolved owner must NOT be dropped"

        row = rows[0]
        assert row["app_key"] is None
        assert row["execution_id"] is None
        assert row["source_tier"] == "framework"
        assert row["tier"] == "watchdog"
        assert row["stall_duration_ms"] is not None
        assert row["reason"] == "framework"

    async def test_monkeypatch_unresolved_owner_recorded_as_framework(
        self, executor: CommandExecutor, db: DbFixture
    ) -> None:
        """MonkeypatchEvent with app_key=None → row with source_tier='framework', NOT dropped."""
        db_svc, _ = db
        event = _make_monkeypatch_event(app_key=None)

        rows = await _record_and_fetch(executor, db_svc, event)
        assert len(rows) == 1, "Unresolved owner must NOT be dropped"

        row = rows[0]
        assert row["app_key"] is None
        assert row["execution_id"] is None
        assert row["source_tier"] == "framework"
        assert row["tier"] == "monkeypatch"
        assert row["primitive"] == "time.sleep"
        assert row["reason"] == "framework"

    async def test_both_unresolved_events_are_framework_attributed(
        self, executor: CommandExecutor, db: DbFixture
    ) -> None:
        """Both tier flavors with app_key=None produce framework-attributed rows."""
        db_svc, _ = db

        executor.record_blocking_event(_make_watchdog_event(app_key=None))
        executor.record_blocking_event(_make_monkeypatch_event(app_key=None))
        await drain_db_writes(db_svc)

        rows = await fetch_blocking_events(db_svc)
        assert len(rows) == 2
        assert all(r["source_tier"] == "framework" for r in rows)
        assert all(r["app_key"] is None for r in rows)
