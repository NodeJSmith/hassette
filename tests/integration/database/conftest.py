"""Shared fixtures for the real-SQLite DatabaseService integration tests."""

import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from tests.support.helpers import (
    DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS,
    DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
)
from tests.support.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette_fresh(tmp_path: Path) -> AsyncMock:
    """Create a mock Hassette with a fresh (empty) data_dir for migration-from-scratch tests."""
    return make_mock_hassette(
        sealed=False,
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX},
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
    )


@pytest.fixture
def service(db_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance (not yet initialized)."""
    return DatabaseService(db_hassette, parent=None)


@pytest.fixture
def fresh_service(mock_hassette_fresh: MagicMock) -> DatabaseService:
    """Create a DatabaseService against a fresh (empty) data_dir — no pre-migrated DB."""
    return DatabaseService(mock_hassette_fresh, parent=None)


@pytest.fixture
async def initialized_fresh_service(fresh_service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize a DatabaseService from scratch (runs real migrations) with a seeded session."""
    await fresh_service.on_initialize()
    try:
        now = time.time()
        cursor = await fresh_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        fresh_service.hassette.session_id = cursor.lastrowid
        await fresh_service.db.commit()
        yield fresh_service
    finally:
        await fresh_service.on_shutdown()


@pytest.fixture
async def initialized_service(service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize a DatabaseService and create a session row for heartbeat tests."""
    await service.on_initialize()
    try:
        # Manually create a session row so heartbeat/retention tests have a valid session_id
        now = time.time()
        cursor = await service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        service.hassette.session_id = cursor.lastrowid
        await service.db.commit()
        yield service
    finally:
        await service.on_shutdown()
