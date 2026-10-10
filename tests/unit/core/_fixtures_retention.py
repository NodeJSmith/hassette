"""Retention-cleanup fixtures for tests/unit/core/: an in-memory telemetry DB and a real
``DatabaseService`` wired to it.

Not re-exported from ``conftest.py`` -- a directory-wide ``db`` fixture name would shadow too
easily. Consumers import directly from this module instead: ``test_log_records_retention.py``
and ``test_retention_batch_failure.py``.
"""

from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from hassette.utils.aiosqlite_utils import connect_daemon
from tests.support.helpers import DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS, DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX
from tests.support.mock_hassette import make_mock_hassette

from .conftest import TELEMETRY_TEST_DDL as DDL

SOURCE_TIER_FRAMEWORK = "framework"
SOURCE_TIER_APP = "app"


@pytest.fixture
def mock_hassette_for_db(tmp_path: Path) -> MagicMock:
    """Mock Hassette for DatabaseService tests."""
    return make_mock_hassette(
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX},
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


@pytest.fixture
def retention_service(db: aiosqlite.Connection, mock_hassette_for_db: MagicMock) -> DatabaseService:
    """Real DatabaseService wired to the in-memory test DB, for retention/failsafe cleanup tests."""
    svc = DatabaseService(mock_hassette_for_db, parent=None)
    svc._db = db  # pyright: ignore[reportPrivateUsage]
    return svc
