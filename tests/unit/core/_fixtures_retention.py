"""Retention-cleanup fixtures for tests/unit/core/: an in-memory telemetry DB and a real
``DatabaseService`` wired to it.

Also holds the shared size-failsafe arrange/act helpers (``run_size_failsafe``) and the
``count_rows`` assertion helper.

Not re-exported from ``conftest.py`` -- a directory-wide ``db`` fixture name would shadow too
easily. Consumers import directly from this module instead: ``test_log_records_retention.py``,
``test_retention_batch_failure.py`` and ``test_app_manifest_retention.py``.
"""

import logging
import sqlite3
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from hassette.utils.aiosqlite_utils import connect_daemon
from tests.support.helpers import (
    DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS,
    DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
    SIZE_FAILSAFE_TRIGGER_MB,
)
from tests.support.mock_hassette import make_mock_hassette

from .conftest import TELEMETRY_TEST_DDL as DDL

SOURCE_TIER_FRAMEWORK = "framework"
SOURCE_TIER_APP = "app"
RETENTION_DAYS = 7
FRAMEWORK_RETENTION_DAYS = 1
LOG_RETENTION_DAYS = 3
# Live data size reported by the default size mock: far above SIZE_FAILSAFE_TRIGGER_MB, so every
# size check in the failsafe cycle reads as over the limit.
ALWAYS_OVER_LIMIT_MB = 10.0


@pytest.fixture
def mock_hassette_for_db(tmp_path: Path) -> MagicMock:
    """Mock Hassette for DatabaseService tests.

    Retention windows are pinned to distinct values (framework 1 < log 3 < app 7 days) rather than
    taken from the config defaults, so retention tests can tell the three cutoffs apart.
    """
    return make_mock_hassette(
        data_dir=tmp_path,
        set_ready=False,
        database={
            "telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
            "retention_days": RETENTION_DAYS,
            "framework_retention_days": FRAMEWORK_RETENTION_DAYS,
        },
        logging={"log_retention_days": LOG_RETENTION_DAYS},
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
    )


@pytest.fixture
async def db() -> aiosqlite.Connection:
    """In-memory aiosqlite connection with log_records schema."""
    conn = await connect_daemon(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(DDL)
    try:
        yield conn
    finally:
        await conn.close()


async def insert_tiered_execution(db: aiosqlite.Connection, timestamp: float, source_tier: str) -> None:
    """Insert a minimal executions row with an explicit source_tier.

    ``insert_execution_row()`` (``tests/support/sql.py``) deliberately omits ``source_tier`` and
    relies on the schema default — not usable here since tier-aware retention tests need rows in
    both tiers.

    Always ``kind='handler'``, so ``listener_id`` is set to a placeholder id (foreign key
    enforcement is off in these tests) to satisfy the production
    ``CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)`` constraint now mirrored in
    the unit test DDL.
    """
    await db.execute(
        "INSERT INTO executions (kind, listener_id, execution_start_ts, source_tier) VALUES ('handler', 1, ?, ?)",
        (timestamp, source_tier),
    )


def make_failing_execute(db: aiosqlite.Connection, fail_on: str) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Build a ``db.execute`` replacement that raises on the first SQL statement containing
    ``fail_on``, delegating everything else to the real ``db.execute``.

    Used by retention tests that simulate one statement raising ``sqlite3.OperationalError`` to
    verify the rest of the cleanup cycle reacts correctly (isolation, parent-guard gating).
    """
    original_execute = db.execute

    async def failing_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
        if fail_on in sql:
            raise sqlite3.OperationalError("simulated failure")
        return await original_execute(sql, *args, **kwargs)

    return failing_execute


@pytest.fixture
def retention_service(db: aiosqlite.Connection, mock_hassette_for_db: MagicMock) -> DatabaseService:
    """Real DatabaseService wired to the in-memory test DB, for retention/failsafe cleanup tests."""
    svc = DatabaseService(mock_hassette_for_db, parent=None)
    svc._db = db  # pyright: ignore[reportPrivateUsage]
    return svc


async def run_size_failsafe(
    retention_service: DatabaseService,
    mock_hassette_for_db: MagicMock,
    caplog: pytest.LogCaptureFixture | None = None,
    *,
    level: int = logging.INFO,
    live_size: Callable[[], Awaitable[float]] | None = None,
) -> None:
    """Force the size limit to ``SIZE_FAILSAFE_TRIGGER_MB`` and run one size-failsafe cycle.

    ``live_size`` replaces ``get_live_data_size_mb``; when omitted, every size check reports
    ``ALWAYS_OVER_LIMIT_MB``, so the cycle never gets back under the limit. When ``caplog`` is
    given, the cycle runs under ``caplog.at_level(level)``.
    """
    mock_hassette_for_db.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB
    retention_service.get_live_data_size_mb = live_size or AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
        return_value=ALWAYS_OVER_LIMIT_MB
    )
    if caplog is None:
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
        return
    with caplog.at_level(level):
        await retention_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]


async def count_rows(db: aiosqlite.Connection, table: str, **filters: object) -> int:
    """Return ``SELECT COUNT(*)`` for ``table``, AND-ing an equality filter per keyword argument.

    ``await count_rows(db, "executions", source_tier="framework")`` counts framework-tier
    executions. Table and column names are interpolated, so pass only literals from test code.
    """
    sql = f"SELECT COUNT(*) FROM {table}"
    if filters:
        sql += " WHERE " + " AND ".join(f"{column} = ?" for column in filters)
    cursor = await db.execute(sql, tuple(filters.values()))
    row = await cursor.fetchone()
    assert row is not None
    return row[0]
