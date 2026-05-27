"""Unit tests for log_records retention, size failsafe pre-pass, and LogPersistenceHandler wiring."""

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from hassette.logging_ import LogPersistenceHandler
from hassette.test_utils.config import SECONDS_PER_DAY
from hassette.test_utils.mock_hassette import make_mock_hassette

from .conftest import LOG_RECORDS_TEST_DDL as DDL


@pytest.fixture
def mock_hassette_for_db(tmp_path: Path) -> MagicMock:
    """Mock Hassette for DatabaseService tests."""
    return make_mock_hassette(
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": 500},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
    )


@pytest.fixture
async def db() -> aiosqlite.Connection:
    """In-memory aiosqlite connection with log_records schema."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(DDL)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def db_service_writer(db: aiosqlite.Connection) -> DatabaseService:
    """DatabaseService with an in-memory test DB connection for seeding records."""
    mock_hassette = MagicMock()
    svc = DatabaseService.__new__(DatabaseService)
    svc.hassette = mock_hassette
    svc._db = db  # pyright: ignore[reportPrivateUsage]
    return svc


class TestRetentionCleanup:
    async def test_retention_deletes_old_log_records(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, mock_hassette_for_db: MagicMock
    ) -> None:
        """_do_run_retention_cleanup() deletes log_records older than log_retention_days."""

        # Seed: one old record (5 days ago), one recent (now)
        now = time.time()
        old_ts = now - (5 * SECONDS_PER_DAY)  # 5 days ago (older than log_retention_days=3)
        recent_ts = now - (1 * SECONDS_PER_DAY)  # 1 day ago (within log_retention_days=3)

        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
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

        service = DatabaseService(mock_hassette_for_db, parent=None)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT message FROM log_records ORDER BY seq")
        remaining = [row[0] for row in await cursor.fetchall()]
        assert remaining == ["recent"]

    async def test_retention_keeps_within_log_retention_days(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, mock_hassette_for_db: MagicMock
    ) -> None:
        """Retention cleanup keeps records within log_retention_days."""

        now = time.time()
        # Use half-day offsets to avoid exact boundary ambiguity with log_retention_days=3:
        # 0.5, 1.5, 2.5 days → within 3 days (kept); 3.5, 4.5 days → older than 3 days (deleted)
        ages_days = [0.5, 1.5, 2.5, 3.5, 4.5]
        records = [
            {
                "seq": i + 1,
                "timestamp": now - (age * SECONDS_PER_DAY),
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
        await db_service_writer._insert_log_records(records)  # pyright: ignore[reportPrivateUsage]

        service = DatabaseService(mock_hassette_for_db, parent=None)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        # log_retention_days=3: records at 0.5, 1.5, 2.5 days old are kept;
        # records at 3.5 and 4.5 days old are deleted
        await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        count = (await cursor.fetchone())[0]
        assert count == 3  # 0.5, 1.5, 2.5 day records remain

    async def test_retention_uses_log_retention_days_not_db_retention_days(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, mock_hassette_for_db: MagicMock
    ) -> None:
        """Retention for log_records uses log_retention_days, not db_retention_days."""

        # log_retention_days=3, db_retention_days=7
        # A record 5 days old is within db_retention_days but outside log_retention_days
        now = time.time()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [
                {
                    "seq": 1,
                    "timestamp": now - (5 * SECONDS_PER_DAY),
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

        service = DatabaseService(mock_hassette_for_db, parent=None)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

        # Should be deleted (5 days > 3 day log_retention_days)
        cursor = await db.execute("SELECT COUNT(*) FROM log_records")
        count = (await cursor.fetchone())[0]
        assert count == 0


class TestSizeFailsafePrePass:
    async def seed_both_tables(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, log_count: int = 10, exec_count: int = 5
    ) -> None:
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
        await db_service_writer._insert_log_records(logs)  # pyright: ignore[reportPrivateUsage]

        for i in range(exec_count):
            await db.execute(
                "INSERT INTO handler_invocations (execution_start_ts) VALUES (?)",
                (now - i * 10,),
            )
        await db.commit()

    async def test_size_failsafe_deletes_log_records_before_execution_records(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, mock_hassette_for_db: MagicMock
    ) -> None:
        """Size failsafe pre-pass deletes from log_records before handler_invocations."""

        await self.seed_both_tables(db, db_service_writer, log_count=10, exec_count=5)

        service = DatabaseService(mock_hassette_for_db, parent=None)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        mock_hassette_for_db.config.database.max_size_mb = 0.0001  # tiny limit

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            if calls <= 2:
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
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, mock_hassette_for_db: MagicMock
    ) -> None:
        """If log pre-pass can't bring size under limit, execution records are also deleted.

        Mock sizing: pre-pass exhausts log_records but DB remains over limit.
        The re-check after the pre-pass still returns over limit, so the failsafe
        proceeds to delete execution records.
        """

        # Seed a small number of logs (all get deleted in pre-pass but still over limit)
        await self.seed_both_tables(db, db_service_writer, log_count=2, exec_count=5)

        service = DatabaseService(mock_hassette_for_db, parent=None)
        service._db = db  # pyright: ignore[reportPrivateUsage]
        mock_hassette_for_db.config.database.max_size_mb = 0.0001

        async def _log_count() -> int:
            cursor = await db.execute("SELECT COUNT(*) FROM log_records")
            row = await cursor.fetchone()
            return row[0] if row else 0

        calls = 0

        def mock_size() -> float:
            nonlocal calls
            calls += 1
            if calls <= 5:
                return 10.0
            return 0.0

        service._get_db_size_mb = mock_size  # pyright: ignore[reportAttributeAccessIssue]
        await service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

        # Execution records should have been deleted (pre-pass was insufficient)
        cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
        exec_remaining = (await cursor.fetchone())[0]
        assert exec_remaining < 5  # some deleted


class TestRuntimeQueryServiceWiring:
    async def test_constructor_injection_stores_db_service_and_loop(self) -> None:
        """LogPersistenceHandler stores db_service and loop at construction."""
        mock_db_service = MagicMock()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=logging.INFO)
        assert handler._db_service is mock_db_service  # pyright: ignore[reportPrivateUsage]
        assert handler._loop is loop  # pyright: ignore[reportPrivateUsage]

    async def test_persistence_handler_dropped_count_starts_at_zero(self) -> None:
        """LogPersistenceHandler.dropped_count starts at 0 after construction."""
        mock_db_service = MagicMock()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=20)
        assert handler.dropped_count == 0

    async def test_persistence_handler_enqueues_records_on_flush(self) -> None:
        """Records are enqueued to db_service when flushed."""
        mock_db_service = MagicMock()
        mock_db_service.enqueue = MagicMock(return_value=True)
        mock_db_service._insert_log_records = MagicMock(return_value=MagicMock())
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=logging.INFO)

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

        # _flush schedules via call_soon_threadsafe; yield to the loop to process it
        await asyncio.sleep(0)
        assert mock_db_service.enqueue.called

    async def test_persistence_handler_filters_below_persistence_level(self) -> None:
        """Records below persistence_level are not accumulated."""
        mock_db_service = MagicMock()
        loop = asyncio.get_running_loop()
        handler = LogPersistenceHandler(mock_db_service, loop, persistence_level=logging.INFO)
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

        # No enqueue because it was filtered before accumulation
        assert handler.dropped_count == 0
        assert handler._batch == []  # pyright: ignore[reportPrivateUsage]
