"""Shared fixtures for integration tests."""

import shutil
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette import Hassette
from hassette.config.config import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.test_utils import make_mock_hassette
from hassette.test_utils.helpers import cleanup_hassette_streams
from hassette.types.enums import ExecutionMode

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


_HARNESS_FIXTURES = frozenset(
    {
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


@pytest.fixture
async def hassette_instance(test_config: HassetteConfig):
    """Provide a fresh Hassette instance and restore context afterwards."""
    test_config.reload()
    instance = Hassette(test_config)
    instance.wire_services()
    try:
        yield instance
    finally:
        await cleanup_hassette_streams(instance)


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


def make_mock_job(
    *,
    owner_id: str = "test_owner",
    app_key: str = "my_app",
    instance_index: int = 1,
    name: str = "test_job",
    error_handler: Callable[..., Any] | None = None,
    db_id: int | None = None,
    mode: ExecutionMode = ExecutionMode.SINGLE,
) -> MagicMock:
    """Return a mock ScheduledJob with the union of fields needed across integration tests."""
    job = MagicMock()
    job.owner_id = owner_id
    job.app_key = app_key
    job.instance_index = instance_index
    job.name = name
    job.job = MagicMock(__qualname__="MyApp.my_job")
    job.trigger = None
    job.args = ()
    job.kwargs = {}
    job.db_id = db_id
    job.mode = mode
    job.error_handler = error_handler
    job.group = None
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
