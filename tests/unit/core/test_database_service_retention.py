"""Unit tests for DatabaseService retention-target definitions and batched delete helpers.

Split out of ``test_database_service.py`` (see that file's docstring and this directory's
CLAUDE.md) once the write-queue/submit tests there grew the file past house-lint's HSL102
threshold -- this file's tests are an independent concern (retention-target metadata and the
batched-delete SQL helpers), not a companion to any other split file.
"""

import dataclasses
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService, _execute_failsafe_delete, _execute_target_delete
from hassette.core.retention_targets import _FAILSAFE_TABLES, _RETENTION_TABLES, RetentionTarget
from tests.unit.core._fixtures_database_service import mock_hassette, service

__all__ = ["mock_hassette", "service"]  # re-exposed as fixtures

WIDGETS_TARGET = RetentionTarget(
    table="widgets",
    timestamp_col="ts",
    priority=0,
    retention_days_getter=lambda _cfg: 0,
    failsafe_label="widgets",
)

WIDGETS_FRAMEWORK_TARGET = RetentionTarget(
    table="widgets",
    timestamp_col="ts",
    priority=0,
    retention_days_getter=lambda _cfg: 0,
    failsafe_label="framework widgets",
    source_tier="framework",
)


def test_retention_tables_is_list_of_retention_targets() -> None:
    assert isinstance(_RETENTION_TABLES, list)
    assert len(_RETENTION_TABLES) > 0
    for entry in _RETENTION_TABLES:
        assert isinstance(entry, RetentionTarget)


def test_retention_tables_contains_expected_tables() -> None:
    table_names = {t.table for t in _RETENTION_TABLES}
    assert table_names == {"log_records", "executions", "blocking_events"}


def test_retention_tables_has_four_entries() -> None:
    """Executions appears twice — once per source tier — plus blocking_events and log_records."""
    assert len(_RETENTION_TABLES) == 4


def test_retention_tables_priority_ordering() -> None:
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert (
        by_label["framework executions"].priority
        < by_label["blocking events"].priority
        < by_label["app executions"].priority
        < by_label["log records"].priority
    )


def test_failsafe_tables_excludes_exempt_targets() -> None:
    """The size failsafe operates on _FAILSAFE_TABLES, which drops failsafe_exempt targets.

    log_records is structurally tiny next to executions, so deleting it reclaims almost nothing
    while destroying the data most needed to diagnose whatever filled the database.
    """
    assert "log_records" not in {t.table for t in _FAILSAFE_TABLES}
    assert [t.failsafe_label for t in _FAILSAFE_TABLES] == [
        "framework executions",
        "blocking events",
        "app executions",
    ]


def test_retention_tables_still_manages_exempt_targets() -> None:
    """Exemption is failsafe-only — age-based retention still covers log_records."""
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["log records"].failsafe_exempt is True
    assert all(not t.failsafe_exempt for label, t in by_label.items() if label != "log records")


def test_retention_target_timestamp_columns() -> None:
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["log records"].timestamp_col == "timestamp"
    assert by_label["framework executions"].timestamp_col == "execution_start_ts"
    assert by_label["app executions"].timestamp_col == "execution_start_ts"
    assert by_label["blocking events"].timestamp_col == "detected_ts"


def test_retention_target_source_tier() -> None:
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["framework executions"].source_tier == "framework"
    assert by_label["app executions"].source_tier == "app"
    assert by_label["blocking events"].source_tier is None
    assert by_label["log records"].source_tier is None


def test_retention_days_getter_for_log_records(mock_hassette: MagicMock) -> None:
    mock_hassette.config.logging.log_retention_days = 3
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["log records"].retention_days_getter(mock_hassette.config) == 3


def test_retention_days_getter_for_app_executions(mock_hassette: MagicMock) -> None:
    mock_hassette.config.database.retention_days = 14
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["app executions"].retention_days_getter(mock_hassette.config) == 14


def test_retention_days_getter_for_framework_executions(mock_hassette: MagicMock) -> None:
    mock_hassette.config.database.framework_retention_days = 2
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["framework executions"].retention_days_getter(mock_hassette.config) == 2


def test_retention_days_getter_for_blocking_events(mock_hassette: MagicMock) -> None:
    mock_hassette.config.database.retention_days = 21
    by_label = {t.failsafe_label: t for t in _RETENTION_TABLES}
    assert by_label["blocking events"].retention_days_getter(mock_hassette.config) == 21


def test_retention_target_is_frozen() -> None:
    target = _RETENTION_TABLES[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.table = "mutated"  # pyright: ignore[reportGeneralTypeIssues]


@pytest.fixture
async def memory_db() -> AsyncIterator[aiosqlite.Connection]:
    """In-memory SQLite connection with a table shaped like a RetentionTarget's target table.

    Uses isolation_level=None (autocommit) to match the real connections DatabaseService opens
    in _initialize() — see database_service.py's connect_daemon() calls. Without this, a
    commit()/rollback() failure in a test behaves differently here than it does in production.
    """
    async with aiosqlite.connect(":memory:", isolation_level=None) as db:
        await db.execute(
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, "
            "source_tier TEXT NOT NULL DEFAULT 'app')"
        )
        await db.commit()
        yield db


async def test_execute_target_delete_removes_rows_older_than_cutoff(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts) VALUES (1.0), (5.0), (10.0)")
    await memory_db.commit()

    deleted = await _execute_target_delete(memory_db, WIDGETS_TARGET, cutoff=6.0, batch_limit=100)

    assert deleted == 2

    cursor = await memory_db.execute("SELECT ts FROM widgets")
    rows = await cursor.fetchall()
    assert [row[0] for row in rows] == [10.0]


async def test_execute_target_delete_returns_zero_when_nothing_matches(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts) VALUES (10.0)")
    await memory_db.commit()

    deleted = await _execute_target_delete(memory_db, WIDGETS_TARGET, cutoff=1.0, batch_limit=100)

    assert deleted == 0


async def test_execute_target_delete_caps_at_batch_limit(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts) VALUES (1.0), (2.0), (3.0)")
    await memory_db.commit()

    deleted = await _execute_target_delete(memory_db, WIDGETS_TARGET, cutoff=100.0, batch_limit=2)

    assert deleted == 2
    cursor = await memory_db.execute("SELECT COUNT(*) FROM widgets")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_execute_target_delete_filters_by_source_tier(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts, source_tier) VALUES (1.0, 'app'), (1.0, 'framework')")
    await memory_db.commit()

    deleted = await _execute_target_delete(memory_db, WIDGETS_FRAMEWORK_TARGET, cutoff=100.0, batch_limit=100)

    assert deleted == 1
    cursor = await memory_db.execute("SELECT source_tier FROM widgets")
    rows = await cursor.fetchall()
    assert [row[0] for row in rows] == ["app"]


async def test_execute_failsafe_delete_removes_oldest_n_rows(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts) VALUES (1.0), (2.0), (3.0), (4.0)")
    await memory_db.commit()

    deleted = await _execute_failsafe_delete(memory_db, WIDGETS_TARGET, batch_limit=2)

    assert deleted == 2

    cursor = await memory_db.execute("SELECT ts FROM widgets ORDER BY ts")
    rows = await cursor.fetchall()
    assert [row[0] for row in rows] == [3.0, 4.0]


async def test_execute_failsafe_delete_caps_at_available_rows(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts) VALUES (1.0)")
    await memory_db.commit()

    deleted = await _execute_failsafe_delete(memory_db, WIDGETS_TARGET, batch_limit=100)

    assert deleted == 1


async def test_execute_failsafe_delete_filters_by_source_tier(memory_db: aiosqlite.Connection) -> None:
    await memory_db.execute("INSERT INTO widgets (ts, source_tier) VALUES (1.0, 'app'), (2.0, 'framework')")
    await memory_db.commit()

    deleted = await _execute_failsafe_delete(memory_db, WIDGETS_FRAMEWORK_TARGET, batch_limit=100)

    assert deleted == 1
    cursor = await memory_db.execute("SELECT source_tier FROM widgets")
    rows = await cursor.fetchall()
    assert [row[0] for row in rows] == ["app"]


async def test_vacuum_and_checkpoint_busy_checkpoint_treated_as_failure(
    service: DatabaseService, memory_db: aiosqlite.Connection
) -> None:
    """A busy wal_checkpoint(TRUNCATE) (nonzero first column, no exception) is a failed attempt.

    SQLite doesn't raise for SQLITE_BUSY on this pragma -- it returns a result row whose first
    column is nonzero. If that row is ignored, the caller sees a false success even though the
    WAL was never truncated. Every attempt reports busy here, so the method must exhaust all
    retries and return False rather than returning True on the first attempt.
    """
    real_execute = memory_db.execute

    class _BusyCheckpointCursor:
        async def fetchone(self) -> tuple[int, int, int]:
            return (1, 5, 0)

        async def close(self) -> None:
            pass

    async def fake_execute(sql: str, *args: object, **kwargs: object):
        if sql.startswith("PRAGMA wal_checkpoint"):
            return _BusyCheckpointCursor()
        return await real_execute(sql, *args, **kwargs)

    with patch.object(memory_db, "execute", side_effect=fake_execute):
        result = await service._vacuum_and_checkpoint_with_retry(memory_db, vacuum_pages=100, group_label="test")

    assert result is False
