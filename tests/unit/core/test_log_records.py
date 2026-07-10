"""Unit tests for log_records table, insert method, query filters, model, and config validation."""

import sqlite3
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pydantic
import pytest

from hassette.config.config import HassetteConfig
from hassette.config.models import LoggingConfig
from hassette.core.database_service import DatabaseService
from hassette.core.migration_runner import run_migrations
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.telemetry_models import LogRecord

from .conftest import TELEMETRY_TEST_DDL as DDL


def run_migrations_to_head(db_path: str) -> None:
    run_migrations(Path(db_path))


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    """In-memory aiosqlite connection with log_records schema."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(DDL)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def db_service(db: aiosqlite.Connection) -> DatabaseService:
    """DatabaseService with an in-memory test DB connection."""
    mock_hassette = MagicMock()
    svc = DatabaseService.__new__(DatabaseService)
    svc.hassette = mock_hassette
    svc._db = db  # pyright: ignore[reportPrivateUsage]
    return svc


@pytest.fixture
def service(db: aiosqlite.Connection) -> TelemetryQueryService:
    """Minimal TelemetryQueryService wired to the in-memory test DB."""
    hassette = MagicMock()
    hassette.database_service.read_db = db
    hassette.config.database.read_timeout_seconds = 10
    svc = TelemetryQueryService.__new__(TelemetryQueryService)
    svc.hassette = hassette
    return svc


def open_migrated_db(db_path: str) -> sqlite3.Connection:
    run_migrations_to_head(db_path)
    return sqlite3.connect(db_path)


class TestMigration001LogRecords:
    @pytest.fixture
    def migrated_db(self, tmp_path: Path) -> Iterator[sqlite3.Connection]:
        conn = open_migrated_db(str(tmp_path / "test.db"))
        try:
            yield conn
        finally:
            conn.close()

    def test_migration_creates_log_records_table(self, migrated_db: sqlite3.Connection) -> None:
        """Migration 001 creates the log_records table."""
        cursor = migrated_db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
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

    def test_migration_version_is_at_head(self, tmp_path: Path) -> None:
        """After full migration, PRAGMA user_version is at head (9)."""
        db_path = str(tmp_path / "test.db")
        run_migrations_to_head(db_path)

        conn = sqlite3.connect(db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

        assert version == 9


class TestRestartPersistence:
    """After a simulated restart (new DB connection), previously-persisted records are queryable."""

    async def test_records_survive_connection_close_and_reopen(self, tmp_path: Path) -> None:
        """Write records, close the connection, reopen, and confirm they're queryable."""
        db_path = str(tmp_path / "persistence_test.db")
        run_migrations_to_head(db_path)

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
            mock_hassette = MagicMock()
            svc = DatabaseService.__new__(DatabaseService)
            svc.hassette = mock_hassette
            svc._db = db1  # pyright: ignore[reportPrivateUsage]
            await svc._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]
            await db1.commit()

        async with aiosqlite.connect(db_path) as db2:
            db2.row_factory = aiosqlite.Row
            hassette = MagicMock()
            hassette.database_service.read_db = db2
            hassette.config.database.read_timeout_seconds = 10
            svc = TelemetryQueryService.__new__(TelemetryQueryService)
            svc.hassette = hassette
            result = await svc.get_log_records()
            assert len(result) == 5
            messages = {r["message"] for r in result}
            for i in range(5):
                assert f"persist_{i}" in messages


class TestInsertLogRecords:
    async def test_insert_writes_records(self, db: aiosqlite.Connection, db_service: DatabaseService) -> None:
        """_insert_log_records() inserts records that are queryable."""
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
        await db_service._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        row = await cursor.fetchone()
        assert row[0] == 2

    async def test_insert_empty_list_is_noop(self, db: aiosqlite.Connection, db_service: DatabaseService) -> None:
        """_insert_log_records() with empty list does not raise."""
        await db_service._insert_log_records([])  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        row = await cursor.fetchone()
        assert row[0] == 0

    async def test_insert_stores_all_fields(self, db: aiosqlite.Connection, db_service: DatabaseService) -> None:
        """_insert_log_records() stores all specified fields correctly."""
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
        await db_service._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

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

    async def test_insert_framework_record_null_app_key(
        self, db: aiosqlite.Connection, db_service: DatabaseService
    ) -> None:
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
        await db_service._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT app_key, execution_id, source_tier FROM log_records")
        row = await cursor.fetchone()
        assert row["app_key"] is None
        assert row["execution_id"] is None
        assert row["source_tier"] == "framework"


async def seed_log_records(db_service: DatabaseService) -> None:
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
    await db_service._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]


class TestGetLogRecords:
    async def test_returns_all_records_no_filters(
        self, db_service: DatabaseService, service: TelemetryQueryService
    ) -> None:
        """get_log_records() with no filters returns all records."""
        await seed_log_records(db_service)
        results = await service.get_log_records(limit=100)
        assert len(results) == 4

    async def test_ordered_by_timestamp_desc_then_seq_desc(
        self, db_service: DatabaseService, service: TelemetryQueryService
    ) -> None:
        """get_log_records() returns newest records first, using seq as a stable tie-breaker."""
        now = time.time()

        def log(seq: int, timestamp: float, message: str) -> dict[str, object]:
            return {
                "seq": seq,
                "timestamp": timestamp,
                "level": "INFO",
                "logger_name": "hassette.test",
                "func_name": "f",
                "lineno": seq,
                "message": message,
                "exc_info": None,
                "app_key": "app_a",
                "instance_name": "app_a_0",
                "instance_index": 0,
                "execution_id": "exec-1",
                "source_tier": "app",
            }

        records = [
            log(1, now - 10, "oldest"),
            log(2, now, "same-timestamp-lower-seq"),
            log(3, now, "same-timestamp-higher-seq"),
            log(4, now + 10, "newest"),
        ]
        await db_service._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

        results = await service.get_log_records(limit=100)

        assert [r["message"] for r in results] == [
            "newest",
            "same-timestamp-higher-seq",
            "same-timestamp-lower-seq",
            "oldest",
        ]

    async def test_filter_by_app_key(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records() filters by app_key."""
        await seed_log_records(db_service)
        results = await service.get_log_records(limit=100, app_key="app_a")
        assert all(r["app_key"] == "app_a" for r in results)
        assert len(results) == 2

    async def test_filter_by_level(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records() filters by level."""
        await seed_log_records(db_service)
        results = await service.get_log_records(limit=100, level="ERROR")
        assert all(r["level"] == "ERROR" for r in results)
        assert len(results) == 1

    async def test_filter_by_execution_id(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records() filters by execution_id."""
        await seed_log_records(db_service)
        results = await service.get_log_records(limit=100, execution_id="exec-1")
        assert all(r["execution_id"] == "exec-1" for r in results)
        assert len(results) == 2

    async def test_filter_by_since(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records() filters by since (timestamp >= since)."""
        await seed_log_records(db_service)
        now = time.time()
        # Only records newer than now-30 (seq 3 and 4)
        results = await service.get_log_records(limit=100, since=now - 30)
        assert len(results) == 2

    async def test_filter_by_source_tier(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records() filters by source_tier."""
        await seed_log_records(db_service)
        results = await service.get_log_records(limit=100, source_tier="framework")
        assert all(r["source_tier"] == "framework" for r in results)
        assert len(results) == 1

    async def test_limit_applied(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records() respects the limit parameter."""
        await seed_log_records(db_service)
        results = await service.get_log_records(limit=2)
        assert len(results) == 2

    async def test_empty_result(self, service: TelemetryQueryService) -> None:
        """get_log_records() returns empty list when no records match."""
        results = await service.get_log_records(limit=100, app_key="nonexistent")
        assert results == []


class TestGetLogRecordsByExecution:
    async def seed_for_execution(self, db_service: DatabaseService) -> None:
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
        await db_service._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

    async def test_returns_records_for_execution(
        self, db_service: DatabaseService, service: TelemetryQueryService
    ) -> None:
        """get_log_records_by_execution() returns records only for the given execution."""
        await self.seed_for_execution(db_service)
        records, truncated = await service.get_log_records_by_execution("exec-exec", limit=100)
        assert len(records) == 5
        assert not truncated

    async def test_ordered_by_seq_asc(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records_by_execution() returns records ordered by seq ASC."""
        await self.seed_for_execution(db_service)
        records, _ = await service.get_log_records_by_execution("exec-exec", limit=100)
        seqs = [r["seq"] for r in records]
        assert seqs == sorted(seqs)

    async def test_truncated_when_over_limit(self, db_service: DatabaseService, service: TelemetryQueryService) -> None:
        """get_log_records_by_execution() returns truncated=True when count > limit."""
        await self.seed_for_execution(db_service)
        records, truncated = await service.get_log_records_by_execution("exec-exec", limit=3)
        assert len(records) == 3
        assert truncated

    async def test_not_truncated_when_at_limit(
        self, db_service: DatabaseService, service: TelemetryQueryService
    ) -> None:
        """get_log_records_by_execution() returns truncated=False when count == limit."""
        await self.seed_for_execution(db_service)
        records, truncated = await service.get_log_records_by_execution("exec-exec", limit=5)
        assert len(records) == 5
        assert not truncated

    async def test_empty_for_unknown_execution(
        self, db_service: DatabaseService, service: TelemetryQueryService
    ) -> None:
        """get_log_records_by_execution() returns empty list for unknown execution_id."""
        await self.seed_for_execution(db_service)
        records, truncated = await service.get_log_records_by_execution("no-such-exec", limit=100)
        assert records == []
        assert not truncated

    async def test_does_not_include_other_executions(
        self, db_service: DatabaseService, service: TelemetryQueryService
    ) -> None:
        """get_log_records_by_execution() excludes records from other executions."""
        await self.seed_for_execution(db_service)
        records, _ = await service.get_log_records_by_execution("exec-exec", limit=100)
        assert all(r["execution_id"] == "exec-exec" for r in records)


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


class TestConfigValidator:
    def test_log_retention_days_field_exists(self) -> None:
        """LoggingConfig has a log_retention_days field with default=3."""
        fields = LoggingConfig.model_fields
        assert "log_retention_days" in fields
        default = fields["log_retention_days"].default
        assert default == 3

    def test_log_retention_days_ge_1(self) -> None:
        """log_retention_days rejects values < 1."""
        with pytest.raises(pydantic.ValidationError):
            HassetteConfig(
                token="tok",
                logging={"log_retention_days": 0},
                _cli_parse_args=False,
            )

    def test_log_retention_days_gt_db_retention_days_raises(self) -> None:
        """Validator rejects log_retention_days > db_retention_days."""
        with pytest.raises(pydantic.ValidationError, match="log_retention_days"):
            HassetteConfig(
                token="tok",
                database={"retention_days": 3},
                logging={"log_retention_days": 5},
                _cli_parse_args=False,
            )

    def test_log_retention_days_equal_db_retention_days_ok(self) -> None:
        """log_retention_days == db_retention_days is valid."""
        cfg = HassetteConfig(
            token="tok",
            database={"retention_days": 5},
            logging={"log_retention_days": 5},
            _cli_parse_args=False,
        )
        assert cfg.logging.log_retention_days == 5

    def test_log_retention_days_less_than_db_retention_days_ok(self) -> None:
        """log_retention_days < db_retention_days is valid."""
        cfg = HassetteConfig(
            token="tok",
            database={"retention_days": 7},
            logging={"log_retention_days": 3},
            _cli_parse_args=False,
        )
        assert cfg.logging.log_retention_days == 3
