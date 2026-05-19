"""Shared fixtures for integration tests."""

import asyncio
import shutil
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from hassette import Hassette
from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.test_utils.web_mocks import create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig):
    """Provide a fresh Hassette instance and restore context afterwards."""
    test_config.reload()
    instance = Hassette(test_config)
    instance.wire_services()
    try:
        yield instance
    finally:
        with suppress(Exception):
            if not instance._event_stream_service.event_streams_closed:
                await instance._event_stream_service.close_streams()

        with suppress(Exception):
            if not instance._bus_service.stream._closed:
                await instance._bus_service.stream.aclose()


_HARNESS_FIXTURES = frozenset(
    {
        "hassette_with_nothing",
        "hassette_with_bus",
        "hassette_with_scheduler",
        "hassette_with_file_watcher",
        "hassette_with_state_proxy",
        "hassette_with_state_registry",
        "hassette_with_app_handler",
        # hassette_with_mock_api excluded: yields (Api, SimpleTestServer), not HassetteHarness.
        # hassette_with_app_handler_custom_config excluded: function-scoped, recreated fresh per test.
    }
)


@pytest.fixture(autouse=True)
async def cleanup_harness(request: pytest.FixtureRequest) -> None:
    """Reset all active module-scoped harness components before each test.

    Function-scoped fixtures (hassette_with_app_handler_custom_config)
    are recreated fresh per test and don't need cleanup.
    """
    for name in _HARNESS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        await harness.reset()


@pytest.fixture
def runtime_query_service(mock_hassette):
    """Create a RuntimeQueryService with mocked Hassette."""
    return create_mock_runtime_query_service(mock_hassette)


@pytest.fixture
def app(mock_hassette, runtime_query_service):  # noqa: ARG001
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)


@pytest.fixture
async def client(app):
    """Create an httpx AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session")
def _migrated_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run Alembic migrations once per pytest worker and return the migrated DB file path.

    Under xdist (-n 2), each worker runs this independently — still a large win since each
    worker has ~75+ DB-heavy tests. Copying this file (~135KB) takes <1ms vs ~700ms for
    running migrations from scratch.
    """
    tmpl_dir = tmp_path_factory.mktemp("db_template")
    mock = MagicMock()
    mock.config.data_dir = tmpl_dir
    mock.config.db_path = None
    mock.config.db_retention_days = 7
    mock.config.log_retention_days = 3
    mock.config.telemetry_write_queue_max = 500
    mock.config.db_write_queue_max = 2000
    mock.config.database_service_log_level = "INFO"
    mock.config.log_level = "INFO"
    mock.config.task_bucket_log_level = "INFO"
    mock.config.resource_shutdown_timeout_seconds = 5
    mock.config.task_cancellation_timeout_seconds = 5
    mock.config.web_api_log_level = "INFO"
    mock.config.run_web_api = True
    mock.config.db_migration_timeout_seconds = 120
    mock.config.db_max_size_mb = 0
    mock.ready_event = asyncio.Event()

    db_service = DatabaseService(mock, parent=mock)

    async def _migrate() -> None:
        await db_service.on_initialize()
        await db_service.on_shutdown()

    asyncio.run(_migrate())

    return tmpl_dir / "hassette.db"


@pytest.fixture
def premigrated_db_path(_migrated_db_template: Path, tmp_path: Path) -> Path:
    """Copy the pre-migrated DB template into a fresh tmp_path for test isolation."""
    dst = tmp_path / "hassette.db"
    shutil.copy2(_migrated_db_template, dst)
    return dst
