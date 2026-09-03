"""Shared fixtures for telemetry integration tests."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.telemetry.query_service import TelemetryQueryService
from tests.support.factories import make_mock_hassette

from .helpers import DbFixture, open_db_with_session


@pytest.fixture
def db_hassette(premigrated_db_path: Path) -> MagicMock:
    """Variant of integration/conftest.db_hassette with web_api enabled for telemetry query tests."""
    return make_mock_hassette(
        data_dir=premigrated_db_path.parent,
        set_ready=False,
        database={"telemetry_write_queue_max": 500, "max_size_mb": 0},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
        web_api={"run": True},
    )


@pytest.fixture
async def db(db_hassette: MagicMock) -> AsyncIterator[DbFixture]:
    """Initialize a DatabaseService with a seeded session row.

    Yields:
        Tuple of (DatabaseService instance, session_id).
    """
    db_service, session_id = await open_db_with_session(db_hassette)
    db_hassette.session_id = session_id
    db_hassette.try_session_id.return_value = session_id
    db_hassette.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def query_service(db_hassette: MagicMock, db: DbFixture) -> TelemetryQueryService:  # noqa: ARG001
    """Create a TelemetryQueryService with DatabaseService already wired.

    Skips on_initialize (which waits on DatabaseService) since the fixture
    provides it directly via db_hassette.database_service.
    """
    # Bypass __init__ to avoid waiting on DatabaseService readiness (already wired via db fixture).
    # Required attrs: hassette, logger, _snapshot_lock — update if TelemetryQueryService.__init__ changes.
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = db_hassette
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service
