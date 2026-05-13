"""Unit tests for T04: log_records table, repository methods, retention, and size failsafe.

Covers:
- Migration 009 creates the log_records table and indexes
- insert_log_records() writes records and they're queryable
- get_log_records() filters by app_key, level, execution_id, since
- get_log_records_by_execution() returns ordered records with truncated flag
- Retention cleanup deletes log_records older than log_retention_days
- Size failsafe pre-pass deletes log_records before execution records
- Config validator rejects log_retention_days > db_retention_days
- LogPersistenceHandler.set_database() wiring via RuntimeQueryService.on_initialize()
"""

import asyncio
import logging
import sqlite3
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pydantic
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_models import LogRecord
from hassette.core.telemetry_repository import get_log_records, get_log_records_by_execution, insert_log_records
from hassette.logging_ import LogPersistenceHandler, get_log_persistence_handler

# ---------------------------------------------------------------------------
# Helpers to run Alembic migrations
# ---------------------------------------------------------------------------

_WORKTREE = Path(__file__).parent.parent.parent.parent


def _run_migrations_to_head(db_path: str) -> None:
    config = AlembicConfig()
    config.set_main_option("script_location", str(_WORKTREE / "src" / "hassette" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    alembic_command.upgrade(config, "head")


# ---------------------------------------------------------------------------
# Minimal DDL for in-memory DB (log_records table + stubs for FK targets)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE log_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seq             INTEGER NOT NULL,
    timestamp       REAL NOT NULL,
    level           TEXT NOT NULL,
    logger_name     TEXT NOT NULL,
    func_name       TEXT,
    lineno          INTEGER,
    message         TEXT NOT NULL,
    exc_info        TEXT,
    app_key         TEXT,
    instance_name   TEXT,
    instance_index  INTEGER,
    execution_id    TEXT,
    source_tier     TEXT
);
CREATE INDEX idx_lr_time ON log_records(timestamp);
CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp);

CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    handler_method        TEXT NOT NULL DEFAULT '',
    topic                 TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    retired_at            REAL
);

CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    job_name              TEXT NOT NULL DEFAULT '',
    handler_method        TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    retired_at            REAL
);

CREATE TABLE handler_invocations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    execution_start_ts    REAL NOT NULL,
    duration_ms           REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'success'
);
CREATE TABLE job_executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    execution_start_ts    REAL NOT NULL,
    duration_ms           REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'success'
);
"""


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    """In-memory aiosqlite connection with log_records schema."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(_DDL)
    try:
        yield conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 1. Migration 009: table and indexes are created
# ---------------------------------------------------------------------------


def _open_migrated_db(db_path: str) -> sqlite3.Connection:
    _run_migrations_to_head(db_path)
    return sqlite3.connect(db_path)


class TestMigration009:
    @pytest.fixture
    def migrated_db(self, tmp_path: Path) -> Iterator[sqlite3.Connection]:
        conn = _open_migrated_db(str(tmp_path / "test.db"))
        try:
            yield conn
        finally:
            conn.close()

    def test_migration_creates_log_records_table(self, migrated_db: sqlite3.Connection) -> None:
        """Migration 009 creates the log_records table."""
        cursor = migrated_db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall() if not row[0].startswith("alembic")}
        assert "log_records" in tables

    def test_migration_creates_log_records_columns(self, migrated_db: sqlite3.Connection) -> None:
        """log_records has all required columns."""
        cursor = migrated_db.execute("PRAGMA table_info(log_records)")
        cols = {row[1] for row in cursor.fetchall()}
        expected = {
            "id",
            "seq",
            "timestamp",
            "level",
            "logger_name",
            "func_name",
            "lineno",
            "message",
            "exc_info",
            "app_key",
            "instance_name",
            "instance_index",
            "execution_id",
            "source_tier",
        }
        assert expected == cols

    def test_migration_creates_time_index(self, migrated_db: sqlite3.Connection) -> None:
        """Migration 009 creates idx_lr_time on log_records(timestamp)."""
        cursor = migrated_db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='log_records'")
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_lr_time" in indexes

    def test_migration_creates_exec_index(self, migrated_db: sqlite3.Connection) -> None:
        """Migration 009 creates idx_lr_exec on log_records(execution_id)."""
        cursor = migrated_db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='log_records'")
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_lr_exec" in indexes

    def test_migration_creates_app_time_index(self, migrated_db: sqlite3.Connection) -> None:
        """Migration 009 creates idx_lr_app_time on log_records(app_key, timestamp)."""
        cursor = migrated_db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='log_records'")
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_lr_app_time" in indexes

    def test_migration_version_is_009(self, tmp_path: Path) -> None:
        """After full migration, the Alembic version is 009."""
        db_path = str(tmp_path / "test.db")
        _run_migrations_to_head(db_path)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                version = ctx.get_current_revision()
        finally:
            engine.dispose()

        assert version == "009"


class TestRestartPersistence:
    """AC#6: After a simulated restart (new DB connection), previously-persisted records are queryable."""

    async def test_records_survive_connection_close_and_reopen(self, tmp_path: Path) -> None:
        """Write records, close the connection, reopen, and confirm they're queryable."""

        db_path = str(tmp_path / "persistence_test.db")
        _run_migrations_to_head(db_path)

        records = [
            {
                "seq": i,
                "timestamp": time.time(),
                "level": "INFO",
                "logger_name": "hassette.test",
                "func_name": "test_fn",
                "lineno": 10,
                "message": f"persist_{i}",
                "exc_info": None,
                "app_key": "test_app",
                "instance_name": None,
                "instance_index": None,
                "execution_id": "exec-restart-test",
                "source_tier": "app",
            }
            for i in range(5)
        ]

        async with aiosqlite.connect(db_path) as db1:
            db1.row_factory = aiosqlite.Row
            await insert_log_records(db1, records)
            await db1.commit()

        async with aiosqlite.connect(db_path) as db2:
            db2.row_factory = aiosqlite.Row
            result = await get_log_records(db2)
            assert len(result) == 5
            messages = {r["message"] for r in result}
            for i in range(5):
                assert f"persist_{i}" in messages


# ---------------------------------------------------------------------------
# 2. insert_log_records — batch INSERT
# ---------------------------------------------------------------------------


class TestInsertLogRecords:
    async def test_insert_writes_records(self, db: aiosqlite.Connection) -> None:
        """insert_log_records() inserts records that are queryable."""

        now = time.time()
        records = [
            {
                "seq": 1,
                "timestamp": now,
                "level": "INFO",
                "logger_name": "my.logger",
                "func_name": "run",
                "lineno": 10,
                "message": "hello",
                "exc_info": None,
                "app_key": "my_app",
                "instance_name": "my_app_0",
                "instance_index": 0,
                "execution_id": "exec-001",
                "source_tier": "app",
            },
            {
                "seq": 2,
                "timestamp": now + 0.001,
                "level": "WARNING",
                "logger_name": "my.logger",
                "func_name": "run",
                "lineno": 20,
                "message": "warn msg",
                "exc_info": None,
                "app_key": "my_app",
                "instance_name": "my_app_0",
                "instance_index": 0,
                "execution_id": "exec-001",
                "source_tier": "app",
            },
        ]
        await insert_log_records(db, records)

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        row = await cursor.fetchone()
        assert row[0] == 2

    async def test_insert_empty_list_is_noop(self, db: aiosqlite.Connection) -> None:
        """insert_log_records() with empty list does not raise."""

        await insert_log_records(db, [])

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        row = await cursor.fetchone()
        assert row[0] == 0

    async def test_insert_stores_all_fields(self, db: aiosqlite.Connection) -> None:
        """insert_log_records() stores all specified fields correctly."""

        now = time.time()
        exc_text = "Traceback: something went wrong"
        records = [
            {
                "seq": 5,
                "timestamp": now,
                "level": "ERROR",
                "logger_name": "app.module",
                "func_name": "handler",
                "lineno": 42,
                "message": "something failed",
                "exc_info": exc_text,
                "app_key": "test_app",
                "instance_name": "test_app_0",
                "instance_index": 0,
                "execution_id": "exec-xyz",
                "source_tier": "app",
            }
        ]
        await insert_log_records(db, records)

        cursor = await db.execute("SELECT * FROM log_records WHERE execution_id = ?", ("exec-xyz",))
        row = await cursor.fetchone()
        assert row is not None
        assert row["seq"] == 5
        assert row["level"] == "ERROR"
        assert row["logger_name"] == "app.module"
        assert row["func_name"] == "handler"
        assert row["lineno"] == 42
        assert row["message"] == "something failed"
        assert row["exc_info"] == exc_text
        assert row["app_key"] == "test_app"
        assert row["instance_name"] == "test_app_0"
        assert row["instance_index"] == 0
        assert row["execution_id"] == "exec-xyz"
        assert row["source_tier"] == "app"

    async def test_insert_framework_record_null_app_key(self, db: aiosqlite.Connection) -> None:
        """Framework records with no app_key (None) are inserted correctly."""

        now = time.time()
        records = [
            {
                "seq": 1,
                "timestamp": now,
                "level": "INFO",
                "logger_name": "hassette.core",
                "func_name": "startup",
                "lineno": 5,
                "message": "framework log",
                "exc_info": None,
                "app_key": None,
                "instance_name": None,
                "instance_index": None,
                "execution_id": None,
                "source_tier": "framework",
            }
        ]
        await insert_log_records(db, records)

        cursor = await db.execute("SELECT app_key, execution_id, source_tier FROM log_records")
        row = await cursor.fetchone()
        assert row["app_key"] is None
        assert row["execution_id"] is None
        assert row["source_tier"] == "framework"


# ---------------------------------------------------------------------------
# 3. get_log_records — filtering and pagination
# ---------------------------------------------------------------------------


async def _seed_log_records(db: aiosqlite.Connection) -> None:
    """Insert a set of log records for filter tests."""

    now = time.time()
    records = [
        {
            "seq": 1,
            "timestamp": now - 100,
            "level": "DEBUG",
            "logger_name": "a",
            "func_name": "f",
            "lineno": 1,
            "message": "debug msg",
            "exc_info": None,
            "app_key": "app_a",
            "instance_name": "app_a_0",
            "instance_index": 0,
            "execution_id": "exec-1",
            "source_tier": "app",
        },
        {
            "seq": 2,
            "timestamp": now - 50,
            "level": "INFO",
            "logger_name": "a",
            "func_name": "f",
            "lineno": 2,
            "message": "info msg",
            "exc_info": None,
            "app_key": "app_a",
            "instance_name": "app_a_0",
            "instance_index": 0,
            "execution_id": "exec-1",
            "source_tier": "app",
        },
        {
            "seq": 3,
            "timestamp": now - 25,
            "level": "ERROR",
            "logger_name": "b",
            "func_name": "g",
            "lineno": 3,
            "message": "error msg",
            "exc_info": None,
            "app_key": "app_b",
            "instance_name": "app_b_0",
            "instance_index": 0,
            "execution_id": "exec-2",
            "source_tier": "app",
        },
        {
            "seq": 4,
            "timestamp": now - 10,
            "level": "WARNING",
            "logger_name": "hassette.core",
            "func_name": "h",
            "lineno": 4,
            "message": "framework warn",
            "exc_info": None,
            "app_key": None,
            "instance_name": None,
            "instance_index": None,
            "execution_id": None,
            "source_tier": "framework",
        },
    ]
    await insert_log_records(db, records)


class TestGetLogRecords:
    async def test_returns_all_records_no_filters(self, db: aiosqlite.Connection) -> None:
        """get_log_records() with no filters returns all records."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=100)
        assert len(results) == 4

    async def test_ordered_by_timestamp_desc(self, db: aiosqlite.Connection) -> None:
        """get_log_records() returns results ordered by timestamp DESC."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=100)
        timestamps = [r["timestamp"] for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_filter_by_app_key(self, db: aiosqlite.Connection) -> None:
        """get_log_records() filters by app_key."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=100, app_key="app_a")
        assert all(r["app_key"] == "app_a" for r in results)
        assert len(results) == 2

    async def test_filter_by_level(self, db: aiosqlite.Connection) -> None:
        """get_log_records() filters by level."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=100, level="ERROR")
        assert all(r["level"] == "ERROR" for r in results)
        assert len(results) == 1

    async def test_filter_by_execution_id(self, db: aiosqlite.Connection) -> None:
        """get_log_records() filters by execution_id."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=100, execution_id="exec-1")
        assert all(r["execution_id"] == "exec-1" for r in results)
        assert len(results) == 2

    async def test_filter_by_since(self, db: aiosqlite.Connection) -> None:
        """get_log_records() filters by since (timestamp >= since)."""

        await _seed_log_records(db)
        now = time.time()
        # Only records newer than now-30 (seq 3 and 4)
        results = await get_log_records(db, limit=100, since=now - 30)
        assert len(results) == 2

    async def test_filter_by_source_tier(self, db: aiosqlite.Connection) -> None:
        """get_log_records() filters by source_tier."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=100, source_tier="framework")
        assert all(r["source_tier"] == "framework" for r in results)
        assert len(results) == 1

    async def test_limit_applied(self, db: aiosqlite.Connection) -> None:
        """get_log_records() respects the limit parameter."""

        await _seed_log_records(db)
        results = await get_log_records(db, limit=2)
        assert len(results) == 2

    async def test_empty_result(self, db: aiosqlite.Connection) -> None:
        """get_log_records() returns empty list when no records match."""

        results = await get_log_records(db, limit=100, app_key="nonexistent")
        assert results == []


# ---------------------------------------------------------------------------
# 4. get_log_records_by_execution — ordered by seq, truncation
# ---------------------------------------------------------------------------


class TestGetLogRecordsByExecution:
    async def _seed_for_execution(self, db: aiosqlite.Connection) -> None:
        now = time.time()
        records = [
            {
                "seq": i,
                "timestamp": now + i * 0.001,
                "level": "INFO",
                "logger_name": "x",
                "func_name": "f",
                "lineno": i,
                "message": f"msg {i}",
                "exc_info": None,
                "app_key": "app_x",
                "instance_name": "x_0",
                "instance_index": 0,
                "execution_id": "exec-exec",
                "source_tier": "app",
            }
            for i in range(1, 6)  # 5 records
        ]
        # Also add a record for a different execution
        records.append(
            {
                "seq": 99,
                "timestamp": now + 10,
                "level": "ERROR",
                "logger_name": "y",
                "func_name": "g",
                "lineno": 1,
                "message": "other exec",
                "exc_info": None,
                "app_key": "app_y",
                "instance_name": "y_0",
                "instance_index": 0,
                "execution_id": "exec-other",
                "source_tier": "app",
            }
        )
        await insert_log_records(db, records)

    async def test_returns_records_for_execution(self, db: aiosqlite.Connection) -> None:
        """get_log_records_by_execution() returns records only for the given execution."""

        await self._seed_for_execution(db)
        records, truncated = await get_log_records_by_execution(db, "exec-exec", limit=100)
        assert len(records) == 5
        assert not truncated

    async def test_ordered_by_seq_asc(self, db: aiosqlite.Connection) -> None:
        """get_log_records_by_execution() returns records ordered by seq ASC."""

        await self._seed_for_execution(db)
        records, _ = await get_log_records_by_execution(db, "exec-exec", limit=100)
        seqs = [r["seq"] for r in records]
        assert seqs == sorted(seqs)

    async def test_truncated_when_over_limit(self, db: aiosqlite.Connection) -> None:
        """get_log_records_by_execution() returns truncated=True when count > limit."""

        await self._seed_for_execution(db)
        records, truncated = await get_log_records_by_execution(db, "exec-exec", limit=3)
        assert len(records) == 3
        assert truncated

    async def test_not_truncated_when_at_limit(self, db: aiosqlite.Connection) -> None:
        """get_log_records_by_execution() returns truncated=False when count == limit."""

        await self._seed_for_execution(db)
        records, truncated = await get_log_records_by_execution(db, "exec-exec", limit=5)
        assert len(records) == 5
        assert not truncated

    async def test_empty_for_unknown_execution(self, db: aiosqlite.Connection) -> None:
        """get_log_records_by_execution() returns empty list for unknown execution_id."""

        await self._seed_for_execution(db)
        records, truncated = await get_log_records_by_execution(db, "no-such-exec", limit=100)
        assert records == []
        assert not truncated

    async def test_does_not_include_other_executions(self, db: aiosqlite.Connection) -> None:
        """get_log_records_by_execution() excludes records from other executions."""

        await self._seed_for_execution(db)
        records, _ = await get_log_records_by_execution(db, "exec-exec", limit=100)
        assert all(r["execution_id"] == "exec-exec" for r in records)


# ---------------------------------------------------------------------------
# 5. LogRecord Pydantic model
# ---------------------------------------------------------------------------


class TestLogRecordModel:
    def test_log_record_has_all_fields(self) -> None:
        """LogRecord model has all required fields."""

        now = time.time()
        record = LogRecord(
            id=1,
            seq=1,
            timestamp=now,
            level="INFO",
            logger_name="my.logger",
            func_name="run",
            lineno=10,
            message="hello",
        )
        assert record.id == 1
        assert record.level == "INFO"
        assert record.message == "hello"
        assert record.app_key is None
        assert record.execution_id is None
        assert record.source_tier is None
        assert record.exc_info is None
        assert record.instance_name is None
        assert record.instance_index is None

    def test_log_record_accepts_full_fields(self) -> None:
        """LogRecord model accepts all optional fields."""

        now = time.time()
        record = LogRecord(
            id=2,
            seq=5,
            timestamp=now,
            level="ERROR",
            logger_name="x.y",
            func_name="handler",
            lineno=42,
            message="boom",
            exc_info="Traceback...",
            app_key="my_app",
            instance_name="my_app_0",
            instance_index=0,
            execution_id="exec-abc",
            source_tier="app",
        )
        assert record.execution_id == "exec-abc"
        assert record.source_tier == "app"
        assert record.exc_info == "Traceback..."


# ---------------------------------------------------------------------------
# 6. Config validator: log_retention_days <= db_retention_days
# ---------------------------------------------------------------------------


class TestConfigValidator:
    def test_log_retention_days_field_exists(self) -> None:
        """HassetteConfig has a log_retention_days field with default=3."""

        fields = HassetteConfig.model_fields
        assert "log_retention_days" in fields
        default = fields["log_retention_days"].default
        assert default == 3

    def test_log_retention_days_ge_1(self) -> None:
        """log_retention_days rejects values < 1."""

        with pytest.raises(pydantic.ValidationError):
            HassetteConfig(token="tok", log_retention_days=0, _cli_parse_args=False)

    def test_log_retention_days_gt_db_retention_days_raises(self) -> None:
        """Validator rejects log_retention_days > db_retention_days."""

        with pytest.raises(pydantic.ValidationError, match="log_retention_days"):
            HassetteConfig(
                token="tok",
                db_retention_days=3,
                log_retention_days=5,
                _cli_parse_args=False,
            )

    def test_log_retention_days_equal_db_retention_days_ok(self) -> None:
        """log_retention_days == db_retention_days is valid."""

        cfg = HassetteConfig(
            token="tok",
            db_retention_days=5,
            log_retention_days=5,
            _cli_parse_args=False,
        )
        assert cfg.log_retention_days == 5

    def test_log_retention_days_less_than_db_retention_days_ok(self) -> None:
        """log_retention_days < db_retention_days is valid."""

        cfg = HassetteConfig(
            token="tok",
            db_retention_days=7,
            log_retention_days=3,
            _cli_parse_args=False,
        )
        assert cfg.log_retention_days == 3


# ---------------------------------------------------------------------------
# 7. Retention cleanup deletes log_records older than log_retention_days
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette_for_db(tmp_path: Path) -> MagicMock:
    """Mock Hassette for DatabaseService tests."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.log_retention_days = 3
    hassette.config.db_max_size_mb = 500
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    return hassette


class TestRetentionCleanup:
    async def test_retention_deletes_old_log_records(
        self, db: aiosqlite.Connection, mock_hassette_for_db: MagicMock
    ) -> None:
        """_do_run_retention_cleanup() deletes log_records older than log_retention_days."""

        # Seed: one old record (5 days ago), one recent (now)
        now = time.time()
        old_ts = now - (5 * 86400)  # 5 days ago (older than log_retention_days=3)
        recent_ts = now - (1 * 86400)  # 1 day ago (within log_retention_days=3)

        await insert_log_records(
            db,
            [
                {
                    "seq": 1,
                    "timestamp": old_ts,
                    "level": "INFO",
                    "logger_name": "x",
                    "func_name": "f",
                    "lineno": 1,
                    "message": "old",
                    "exc_info": None,
                    "app_key": "a",
                    "instance_name": "a_0",
                    "instance_index": 0,
                    "execution_id": None,
                    "source_tier": "app",
                },
                {
                    "seq": 2,
                    "timestamp": recent_ts,
                    "level": "INFO",
                    "logger_name": "x",
                    "func_name": "f",
                    "lineno": 2,
                    "message": "recent",
                    "exc_info": None,
                    "app_key": "a",
                    "instance_name": "a_0",
                    "instance_index": 0,
                    "execution_id": None,
                    "source_tier": "app",
                },
            ],
        )

        service = DatabaseService(mock_hassette_for_db, parent=mock_hassette_for_db)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT message FROM log_records ORDER BY seq")
        remaining = [row[0] for row in await cursor.fetchall()]
        assert remaining == ["recent"]

    async def test_retention_keeps_within_log_retention_days(
        self, db: aiosqlite.Connection, mock_hassette_for_db: MagicMock
    ) -> None:
        """Retention cleanup keeps records within log_retention_days."""

        now = time.time()
        # Use half-day offsets to avoid exact boundary ambiguity with log_retention_days=3:
        # 0.5, 1.5, 2.5 days → within 3 days (kept); 3.5, 4.5 days → older than 3 days (deleted)
        ages_days = [0.5, 1.5, 2.5, 3.5, 4.5]
        records = [
            {
                "seq": i + 1,
                "timestamp": now - (age * 86400),
                "level": "INFO",
                "logger_name": "x",
                "func_name": "f",
                "lineno": i + 1,
                "message": f"age {age} days",
                "exc_info": None,
                "app_key": "a",
                "instance_name": "a_0",
                "instance_index": 0,
                "execution_id": None,
                "source_tier": "app",
            }
            for i, age in enumerate(ages_days)
        ]
        await insert_log_records(db, records)

        service = DatabaseService(mock_hassette_for_db, parent=mock_hassette_for_db)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        # log_retention_days=3: records at 0.5, 1.5, 2.5 days old are kept;
        # records at 3.5 and 4.5 days old are deleted
        await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        count = (await cursor.fetchone())[0]
        assert count == 3  # 0.5, 1.5, 2.5 day records remain

    async def test_retention_uses_log_retention_days_not_db_retention_days(
        self, db: aiosqlite.Connection, mock_hassette_for_db: MagicMock
    ) -> None:
        """Retention for log_records uses log_retention_days, not db_retention_days."""

        # log_retention_days=3, db_retention_days=7
        # A record 5 days old is within db_retention_days but outside log_retention_days
        now = time.time()
        await insert_log_records(
            db,
            [
                {
                    "seq": 1,
                    "timestamp": now - (5 * 86400),
                    "level": "INFO",
                    "logger_name": "x",
                    "func_name": "f",
                    "lineno": 1,
                    "message": "5 days old",
                    "exc_info": None,
                    "app_key": "a",
                    "instance_name": "a_0",
                    "instance_index": 0,
                    "execution_id": None,
                    "source_tier": "app",
                }
            ],
        )

        service = DatabaseService(mock_hassette_for_db, parent=mock_hassette_for_db)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # Should be deleted (5 days > 3 day log_retention_days)
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        count = (await cursor.fetchone())[0]
        assert count == 0


# ---------------------------------------------------------------------------
# 8. Size failsafe pre-pass: log_records deleted before execution records
# ---------------------------------------------------------------------------


class TestSizeFailsafePrePass:
    async def _seed_both_tables(self, db: aiosqlite.Connection, log_count: int = 10, exec_count: int = 5) -> None:
        """Seed log_records and handler_invocations."""

        now = time.time()
        logs = [
            {
                "seq": i,
                "timestamp": now - (i * 10),
                "level": "INFO",
                "logger_name": "x",
                "func_name": "f",
                "lineno": i,
                "message": f"log {i}",
                "exc_info": None,
                "app_key": "a",
                "instance_name": "a_0",
                "instance_index": 0,
                "execution_id": None,
                "source_tier": "app",
            }
            for i in range(1, log_count + 1)
        ]
        await insert_log_records(db, logs)

        for i in range(exec_count):
            await db.execute(
                "INSERT INTO handler_invocations (execution_start_ts) VALUES (?)",
                (now - i * 10,),
            )
        await db.commit()

    async def test_size_failsafe_deletes_log_records_before_execution_records(
        self, db: aiosqlite.Connection, mock_hassette_for_db: MagicMock
    ) -> None:
        """Size failsafe pre-pass deletes from log_records before handler_invocations."""

        await self._seed_both_tables(db, log_count=10, exec_count=5)

        service = DatabaseService(mock_hassette_for_db, parent=mock_hassette_for_db)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        mock_hassette_for_db.config.db_max_size_mb = 0.0001  # tiny limit

        # Override _get_db_size_mb to return always-over-limit first, then under
        call_count = [0]

        def mock_size() -> float:
            call_count[0] += 1
            # First call: over limit → triggers failsafe
            # After first pre-pass iteration: under limit
            if call_count[0] <= 2:  # initial check + after first pre-pass del
                return 10.0
            return 0.0

        service._get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # handler_invocations should NOT be touched (log_records were sufficient)
        cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
        exec_count = (await cursor.fetchone())[0]
        assert exec_count == 5  # untouched

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        log_count = (await cursor.fetchone())[0]
        assert log_count < 10  # some deleted

    async def test_size_failsafe_proceeds_to_execution_records_if_log_prepass_insufficient(
        self, db: aiosqlite.Connection, mock_hassette_for_db: MagicMock
    ) -> None:
        """If log pre-pass can't bring size under limit, execution records are also deleted.

        Mock sizing: pre-pass exhausts log_records but DB remains over limit.
        The re-check after the pre-pass still returns over limit, so the failsafe
        proceeds to delete execution records.
        """

        # Seed a small number of logs (all get deleted in pre-pass but still over limit)
        await self._seed_both_tables(db, log_count=2, exec_count=5)

        service = DatabaseService(mock_hassette_for_db, parent=mock_hassette_for_db)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        mock_hassette_for_db.config.db_max_size_mb = 0.0001

        async def _log_count() -> int:
            cursor = await db.execute("SELECT COUNT(*) FROM log_records")
            row = await cursor.fetchone()
            return row[0] if row else 0

        call_count = [0]

        def mock_size() -> float:
            call_count[0] += 1
            # Stay over limit for all pre-pass iterations AND the re-check after the pre-pass
            # (calls 1 through N+1 where N = pre-pass iterations).
            # Return under limit only after first execution-loop delete.
            # We keep it simple: return over limit for calls 1-5, then 0.
            if call_count[0] <= 5:
                return 10.0
            return 0.0

        service._get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # Execution records should have been deleted (pre-pass was insufficient)
        cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
        exec_remaining = (await cursor.fetchone())[0]
        assert exec_remaining < 5  # some deleted


# ---------------------------------------------------------------------------
# 9. RuntimeQueryService wires LogPersistenceHandler.set_database()
# ---------------------------------------------------------------------------


class TestRuntimeQueryServiceWiring:
    async def test_set_database_wires_db_service_on_persistence_handler(self) -> None:
        """set_database() stores the db_service reference on LogPersistenceHandler."""

        persistence_handler = get_log_persistence_handler()
        if persistence_handler is None:
            pytest.skip("LogPersistenceHandler not installed (enable_logging() not called)")

        mock_db_service = MagicMock()
        persistence_handler.set_database(mock_db_service, asyncio.get_event_loop())
        assert persistence_handler._db_service is mock_db_service  # pyright: ignore[reportPrivateUsage]

    async def test_persistence_handler_dropped_count_starts_at_zero(self) -> None:
        """LogPersistenceHandler.dropped_count starts at 0 after construction."""

        handler = LogPersistenceHandler(persistence_level=20)
        assert handler.dropped_count == 0

    async def test_persistence_handler_drops_records_when_no_db(self) -> None:
        """Records are dropped (counted) before set_database is called."""

        handler = LogPersistenceHandler(persistence_level=logging.INFO)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        # Stamp required attributes
        record.seq = 1  # pyright: ignore[reportAttributeAccessIssue]
        record.app_key = None  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_name = None  # pyright: ignore[reportAttributeAccessIssue]
        record.instance_index = None  # pyright: ignore[reportAttributeAccessIssue]
        record.execution_id = None  # pyright: ignore[reportAttributeAccessIssue]
        record.source_tier = None  # pyright: ignore[reportAttributeAccessIssue]

        handler.emit(record)
        handler.flush_if_pending()

        assert handler.dropped_count == 1

    async def test_persistence_handler_filters_below_persistence_level(self) -> None:
        """Records below persistence_level are not accumulated."""

        handler = LogPersistenceHandler(persistence_level=logging.INFO)
        debug_record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=1,
            msg="debug msg",
            args=(),
            exc_info=None,
        )
        handler.emit(debug_record)
        handler.flush_if_pending()

        # No drop because it was filtered before accumulation
        assert handler.dropped_count == 0
        assert handler._batch == []  # pyright: ignore[reportPrivateUsage]
