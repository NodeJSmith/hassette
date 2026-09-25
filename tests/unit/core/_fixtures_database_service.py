"""DatabaseService fixtures for tests/unit/core/.

Not re-exported from ``conftest.py`` like this directory's other ``_fixtures_*.py`` modules --
``conftest.py`` already re-exports a differently-configured ``mock_hassette`` fixture from
``_fixtures_app_lifecycle.py`` (sealed=False, dev_mode=True, no database/lifecycle overrides),
and importing a second fixture under the same name into that flat namespace would silently
shadow it for the rest of the directory. Consumers import directly from this module instead:
``test_database_service.py`` and ``test_database_service_toctou_regression.py``.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.database_service import DatabaseService
from tests.support.helpers import DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS, DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX
from tests.support.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config defaults."""
    return make_mock_hassette(
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX},
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
    )


@pytest.fixture
def service(mock_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance."""
    return DatabaseService(mock_hassette, parent=None)


@pytest.fixture
async def initialized_service_with_worker(service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize DatabaseService with the worker running; cancel worker in cleanup.

    Does NOT call on_shutdown — leaves worker task and connection management to the test.
    """
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    mock_conn.close = AsyncMock()
    # stop() is aiosqlite's *synchronous* counterpart to close() (see stop_connection_sync()) --
    # an unconfigured attribute on an AsyncMock defaults to AsyncMock too, which would return an
    # unawaited coroutine here and fail the suite via PytestUnraisableExceptionWarning. Same
    # reasoning applies to `_thread`: stop_connection_sync() checks `thread.is_alive()` and would
    # otherwise get an unawaited coroutine back instead of a real bool.
    mock_conn.stop = MagicMock()
    mock_conn._thread = None

    async def fake_connect(*_args: object, **_kwargs: object) -> AsyncMock:
        return mock_conn

    with (
        patch.object(service, "run_migrations"),
        patch("hassette.core.database_service.connect_daemon", side_effect=fake_connect),
    ):
        await service.on_initialize()
    try:
        yield service
    finally:
        if service._db_worker_task is not None and not service._db_worker_task.done():
            service._db_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await service._db_worker_task
