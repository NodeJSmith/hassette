"""Integration tests for session queries and telemetry health checks.

Covers get_session_list(), check_health(), and read-timeout behavior of execute().
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.exceptions import TelemetryUnavailableError
from hassette.schemas.summary_models import SessionRecord
from hassette.test_utils.mock_hassette import make_mock_hassette

from .helpers import BASE_TS, DbFixture, open_db_with_session


class TestGetSessionList:
    async def test_get_session_list(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """3 sessions with different statuses — ordered by started_at DESC, correct duration."""
        db_svc, session_id = db

        base_ts = BASE_TS

        # Update the existing running session's started_at for predictability
        await db_svc.db.execute(
            "UPDATE sessions SET started_at = ?, last_heartbeat_at = ? WHERE id = ?",
            (base_ts + 200.0, base_ts + 300.0, session_id),
        )
        # Insert two more sessions
        await db_svc.db.execute(
            "INSERT INTO sessions (started_at, stopped_at, last_heartbeat_at, status) VALUES (?, ?, ?, 'stopped')",
            (base_ts + 100.0, base_ts + 150.0, base_ts + 150.0),
        )
        await db_svc.db.execute(
            "INSERT INTO sessions (started_at, stopped_at, last_heartbeat_at, status) VALUES (?, ?, ?, 'stopped')",
            (base_ts + 0.0, base_ts + 50.0, base_ts + 50.0),
        )
        await db_svc.db.commit()

        rows = await query_service.get_session_list(limit=20)
        assert len(rows) == 3

        # Returns typed SessionRecord models
        assert all(isinstance(r, SessionRecord) for r in rows)

        # Most recent first: started_at DESC
        assert rows[0].started_at == pytest.approx(base_ts + 200.0)
        assert rows[1].started_at == pytest.approx(base_ts + 100.0)
        assert rows[2].started_at == pytest.approx(base_ts + 0.0)

        # duration_seconds for stopped sessions = stopped_at - started_at
        assert rows[1].duration_seconds == pytest.approx(50.0)
        assert rows[2].duration_seconds == pytest.approx(50.0)

        # Running session uses last_heartbeat_at for duration
        assert rows[0].duration_seconds == pytest.approx(100.0)

        # Field types are correct
        assert isinstance(rows[0].id, int)
        assert isinstance(rows[0].status, str)
        assert rows[0].stopped_at is None  # running session
        assert rows[1].stopped_at is not None  # stopped session


class TestCheckHealth:
    async def test_check_health_succeeds_on_live_db(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """check_health() completes without raising when the database is live."""
        # Should not raise
        await query_service.check_health()

    async def test_check_health_raises_on_closed_db(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """check_health() raises TelemetryUnavailableError when the read_db connection is closed."""
        db_svc, _session_id = db
        # Close the read connection to simulate a failed connection
        await db_svc._read_db.close()
        try:
            with pytest.raises(TelemetryUnavailableError):
                await query_service.check_health()
        finally:
            # Restore so fixture teardown doesn't crash
            db_svc._read_db = await aiosqlite.connect(db_svc._db_path, isolation_level=None)
            db_svc._read_db.row_factory = aiosqlite.Row


class TestReadTimeout:
    @pytest.fixture
    def short_timeout_hassette(self, premigrated_db_path: Path) -> MagicMock:
        return make_mock_hassette(
            data_dir=premigrated_db_path.parent,
            set_ready=False,
            database={"telemetry_write_queue_max": 500, "max_size_mb": 0, "read_timeout_seconds": 0.1},
            lifecycle={"resource_shutdown_timeout_seconds": 5},
            web_api={"run": True},
        )

    @pytest.fixture
    async def short_timeout_db(self, short_timeout_hassette: MagicMock) -> AsyncIterator[DbFixture]:
        db_service, session_id = await open_db_with_session(short_timeout_hassette)
        short_timeout_hassette.session_id = session_id
        short_timeout_hassette.try_session_id.return_value = session_id
        short_timeout_hassette.database_service = db_service
        yield db_service, session_id
        await db_service.on_shutdown()

    @pytest.fixture
    def short_timeout_query_service(
        self, short_timeout_hassette: MagicMock, short_timeout_db: DbFixture
    ) -> TelemetryQueryService:
        service = TelemetryQueryService.__new__(TelemetryQueryService)
        service.hassette = short_timeout_hassette
        service.logger = MagicMock()
        service._snapshot_lock = asyncio.Lock()
        return service

    async def test_execute_raises_timeout_error(
        self, short_timeout_query_service: TelemetryQueryService, short_timeout_db: DbFixture
    ) -> None:
        """execute() raises TelemetryUnavailableError when a query exceeds read_timeout_seconds."""
        db_svc, _ = short_timeout_db

        # Register a custom SQLite function that sleeps, forcing the query to exceed the 100ms timeout
        await db_svc.read_db.create_function("sleep_ms", 1, lambda ms: time.sleep(ms / 1000))

        with pytest.raises(TelemetryUnavailableError):
            async with short_timeout_query_service.execute("SELECT sleep_ms(300)") as cursor:
                await cursor.fetchone()

    async def test_normal_query_succeeds_within_timeout(
        self, short_timeout_query_service: TelemetryQueryService, short_timeout_db: DbFixture
    ) -> None:
        """A fast query completes within even a short timeout."""
        await short_timeout_query_service.check_health()
