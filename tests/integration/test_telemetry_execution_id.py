"""Integration tests for execution_id, trigger_context_id, trigger_origin persist/query roundtrip.

Covers the new columns added to handler_invocations and job_executions in migration 007.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.core.telemetry_repository import TelemetryRepository, _inv_insert_params, _job_insert_params
from hassette.scheduler.classes import JobExecutionRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.web_api_log_level = "INFO"
    hassette.config.run_web_api = True
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a DatabaseService with all migrations applied and a seeded session row."""
    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    mock_hassette.session_id = session_id
    mock_hassette.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def repo(db: tuple[DatabaseService, int]) -> TelemetryRepository:
    db_service, _ = db
    return TelemetryRepository(db_service)


@pytest.fixture
def svc(mock_hassette: MagicMock, db: tuple[DatabaseService, int]) -> TelemetryQueryService:  # noqa: ARG001
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = mock_hassette
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_listener(db_svc: DatabaseService, *, app_key: str = "test_app") -> int:
    """Insert a minimal listener row and return its id."""
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, 'test.py:1', 'app')""",
        (app_key, 0, "on_event", "hass.event.state_changed"),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_job(db_svc: DatabaseService, *, app_key: str = "test_app") -> int:
    """Insert a minimal scheduled_job row and return its id."""
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, repeat,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, 'interval', 1, 'test.py:1', 'app')""",
        (app_key, 0, "my_job", "run_job"),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _make_inv_record(
    listener_id: int | None,
    session_id: int,
    *,
    execution_id: str | None = None,
    trigger_context_id: str | None = None,
    trigger_origin: str | None = None,
) -> HandlerInvocationRecord:
    return HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=10.0,
        status="success",
        execution_id=execution_id,
        trigger_context_id=trigger_context_id,
        trigger_origin=trigger_origin,
    )


def _make_job_record(
    job_id: int | None,
    session_id: int,
    *,
    execution_id: str | None = None,
) -> JobExecutionRecord:
    return JobExecutionRecord(
        job_id=job_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=20.0,
        status="success",
        execution_id=execution_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHandlerInvocationExecutionId:
    async def test_persist_and_query_handler_invocation_with_execution_id(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, svc: TelemetryQueryService
    ) -> None:
        """Persist a HandlerInvocationRecord with all three new fields and query them back."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)
        record = _make_inv_record(
            listener_id,
            session_id,
            execution_id="abc-123",
            trigger_context_id="ctx-456",
            trigger_origin="LOCAL",
        )

        await repo.persist_batch([record], [])

        results = await svc.get_handler_invocations(listener_id, limit=10)
        assert len(results) == 1
        inv = results[0]
        assert inv.execution_id == "abc-123"
        assert inv.trigger_context_id == "ctx-456"
        assert inv.trigger_origin == "LOCAL"

    async def test_null_execution_id_persists_and_queries(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, svc: TelemetryQueryService
    ) -> None:
        """Persist a record with execution_id=None and confirm it comes back as None (not empty string)."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)
        record = _make_inv_record(listener_id, session_id, execution_id=None)

        await repo.persist_batch([record], [])

        results = await svc.get_handler_invocations(listener_id, limit=10)
        assert len(results) == 1
        assert results[0].execution_id is None

    async def test_fk_fallback_preserves_execution_id(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, svc: TelemetryQueryService
    ) -> None:
        """On FK violation, only listener_id is nulled; execution_id/context/origin are preserved."""
        db_svc, session_id = db
        # Use a non-existent listener_id to trigger FK violation
        nonexistent_listener_id = 99999
        record = _make_inv_record(
            nonexistent_listener_id,
            session_id,
            execution_id="abc-123",
            trigger_context_id="ctx-456",
            trigger_origin="REMOTE",
        )

        dropped = await repo.persist_batch_with_fk_fallback([record], [])
        assert dropped == 0  # Row persisted with null FK, not dropped

        # Query all invocations where listener_id IS NULL (orphaned rows)
        async with db_svc.db.execute(
            "SELECT execution_id, trigger_context_id, trigger_origin, listener_id FROM handler_invocations"
        ) as cursor:
            rows = await cursor.fetchall()

        assert len(rows) == 1
        row = rows[0]
        assert row[0] == "abc-123"  # execution_id preserved
        assert row[1] == "ctx-456"  # trigger_context_id preserved
        assert row[2] == "REMOTE"  # trigger_origin preserved
        assert row[3] is None  # listener_id nulled

    async def test_shared_params_match_persist_batch_columns(self, db: tuple[DatabaseService, int]) -> None:
        """_inv_insert_params() keys must match the column list used in persist_batch() INSERT."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)
        record = _make_inv_record(listener_id, session_id)
        params = _inv_insert_params(record)

        # Verify params has all expected keys including the new execution_id columns
        assert "execution_id" in params
        assert "trigger_context_id" in params
        assert "trigger_origin" in params
        assert "listener_id" in params
        assert "session_id" in params
        assert "is_di_failure" in params

        # is_di_failure must be int-converted (not bool)
        assert isinstance(params["is_di_failure"], int)

        # Build actual column list from keys — same as persist_batch() does
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params)

        # Verify the constructed INSERT works against a real DB
        await db_svc.db.execute(
            f"INSERT INTO handler_invocations ({cols}) VALUES ({vals})",
            params,
        )
        await db_svc.db.commit()

        # Count rows — should have exactly 1
        async with db_svc.db.execute("SELECT COUNT(*) FROM handler_invocations") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 1


class TestJobExecutionExecutionId:
    async def test_persist_and_query_job_execution_with_execution_id(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, svc: TelemetryQueryService
    ) -> None:
        """Persist a JobExecutionRecord with execution_id and query it back."""
        db_svc, session_id = db
        job_id = await _insert_job(db_svc)
        record = _make_job_record(job_id, session_id, execution_id="def-789")

        await repo.persist_batch([], [record])

        results = await svc.get_job_executions(job_id, limit=10)
        assert len(results) == 1
        je = results[0]
        assert je.execution_id == "def-789"
        assert not hasattr(je, "trigger_context_id"), "JobExecution must not have trigger_context_id"

    async def test_job_shared_params_match_persist_batch_columns(self, db: tuple[DatabaseService, int]) -> None:
        """_job_insert_params() keys must match the column list used in persist_batch() INSERT."""
        db_svc, session_id = db
        job_id = await _insert_job(db_svc)
        record = _make_job_record(job_id, session_id)
        params = _job_insert_params(record)

        # Verify params has all expected keys including execution_id
        assert "execution_id" in params
        assert "job_id" in params
        assert "session_id" in params
        assert "is_di_failure" in params

        # is_di_failure must be int-converted (not bool)
        assert isinstance(params["is_di_failure"], int)

        # Build actual column list from keys — same as persist_batch() does
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params)

        # Verify the constructed INSERT works against a real DB
        await db_svc.db.execute(
            f"INSERT INTO job_executions ({cols}) VALUES ({vals})",
            params,
        )
        await db_svc.db.commit()

        # Count rows — should have exactly 1
        async with db_svc.db.execute("SELECT COUNT(*) FROM job_executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 1
