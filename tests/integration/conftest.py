"""Shared fixtures for integration tests."""

import shutil
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx2 import ASGITransport, AsyncClient

from hassette import Hassette
from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.scheduler.classes import ScheduledJob
from hassette.test_utils import make_mock_hassette
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
        "hassette_with_sync_executor",
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
    """Create an httpx2 AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def premigrated_db_path(_migrated_db_template: Path, tmp_path: Path) -> Path:
    """Copy the pre-migrated DB template into a fresh tmp_path for test isolation."""
    dst = tmp_path / "hassette.db"
    shutil.copy2(_migrated_db_template, dst)
    return dst


@pytest.fixture
def db_hassette(premigrated_db_path: Path) -> AsyncMock:
    """Provide a mock Hassette with real validated config pointing to a pre-migrated DB.

    Note: telemetry/conftest.py defines a variant with web_api={"run": True} for telemetry tests.
    """
    return make_mock_hassette(
        data_dir=premigrated_db_path.parent,
        set_ready=False,
        sealed=False,
        database={"telemetry_write_queue_max": 500, "max_size_mb": 0},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
        scheduler={"min_delay_seconds": 0.1, "max_delay_seconds": 60.0, "default_delay_seconds": 1.0},
    )


@pytest.fixture
async def initialized_db(db_hassette: AsyncMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a real DatabaseService and create a session row.

    Yields:
        Tuple of (DatabaseService instance, session_id).
    """
    db_service = DatabaseService(db_hassette, parent=db_hassette)
    await db_service.on_initialize()
    try:
        now = time.time()
        cursor = await db_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        db_hassette.session_id = session_id
        db_hassette.try_session_id.return_value = session_id
        await db_service.db.commit()
        db_hassette.database_service = db_service
        yield db_service, session_id
    finally:
        await db_service.on_shutdown()


def make_mock_listener(*, error_handler=None) -> MagicMock:
    """Return a mock Listener whose invoke() is an awaitable coroutine."""
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.invoker.invoke = AsyncMock()
    listener.error_handler = error_handler
    listener.invoker.error_handler = error_handler
    return listener


def make_mock_job(*, error_handler=None) -> MagicMock:
    """Return a mock ScheduledJob with optional error handler."""
    job = MagicMock(spec=ScheduledJob)
    job.error_handler = error_handler
    job.name = "test_job"
    job.group = None
    job.args = ()
    job.kwargs = {}
    return job


def make_manifest_mock(
    app_key: str = "my_app",
    filename: str = "my_app.py",
    class_name: str = "MyApp",
    enabled: bool = True,
    autostart: bool = True,
    app_config: dict | list[dict] | None = None,
    app_dir: Path | None = None,
    full_path: Path | None = None,
) -> MagicMock:
    """Build a manifest mock for config/source endpoint tests."""
    m = MagicMock()
    m.app_key = app_key
    m.filename = filename
    m.class_name = class_name
    m.enabled = enabled
    m.autostart = autostart
    m.app_config = app_config if app_config is not None else {"instance_name": f"{class_name}.0"}
    m.app_dir = app_dir or Path("/apps")
    m.full_path = full_path or (m.app_dir / filename)
    return m
