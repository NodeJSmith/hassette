"""Shared fixtures and constants for tests/unit/core/."""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.router import Router
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.event_filter import EventFilter
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types.enums import ResourceStatus

# Minimal DDL for log_records tests — intentionally omits many real columns.
# See test_database_service_migrations.py for the canonical schema contract.
LOG_RECORDS_TEST_DDL = """
CREATE TABLE log_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seq             INTEGER NOT NULL,
    timestamp       REAL NOT NULL,
    level           TEXT NOT NULL,
    logger_name     TEXT NOT NULL,
    func_name       TEXT,
    lineno          INTEGER,
    message         TEXT NOT NULL,
    exc_info        TEXT,
    app_key         TEXT,
    instance_name   TEXT,
    instance_index  INTEGER,
    execution_id    TEXT,
    source_tier     TEXT
);
CREATE INDEX idx_lr_time ON log_records(timestamp);
CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp);

CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    handler_method        TEXT NOT NULL DEFAULT '',
    topic                 TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    retired_at            REAL
);

CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    job_name              TEXT NOT NULL DEFAULT '',
    handler_method        TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    retired_at            REAL
);

CREATE TABLE handler_invocations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    execution_start_ts    REAL NOT NULL,
    duration_ms           REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'success'
);
CREATE TABLE job_executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    execution_start_ts    REAL NOT NULL,
    duration_ms           REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'success'
);
"""


@pytest.fixture
def mock_hassette() -> AsyncMock:
    """Create a mock Hassette instance with config for AppLifecycleService tests."""
    hassette = make_mock_hassette(
        sealed=False,
        dev_mode=True,
        logging={"app_handler": "DEBUG"},
        lifecycle={"app_startup_timeout_seconds": 30},
    )
    hassette.send_event = AsyncMock()
    hassette.command_executor = MagicMock()
    hassette.command_executor.reconcile_registrations = AsyncMock()
    hassette.bus_service = MagicMock()
    hassette.bus_service.await_registrations_complete = AsyncMock()
    hassette.bus_service.router = MagicMock()
    hassette.bus_service.router.get_listeners_by_owner = Mock(return_value=[])
    hassette.scheduler_service = MagicMock()
    hassette.scheduler_service.await_registrations_complete = AsyncMock()
    hassette.session_id = 1
    return hassette


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create a mock AppRegistry instance."""
    registry = MagicMock()
    registry.record_failure = Mock()
    registry.all_apps = Mock(return_value=[])
    registry.clear_all = Mock()
    registry.get_manifest = Mock(return_value=None)
    registry.get_apps_by_key = Mock(return_value={})
    registry.register_app = Mock()
    registry.unregister_app = Mock(return_value=None)
    registry.set_manifests = Mock()
    registry.set_only_app = Mock()
    registry.apps = {}
    registry.manifests = {}
    registry.enabled_manifests = {}
    registry.active_manifests = {}
    registry.only_app = None
    registry.get_snapshot = Mock()
    registry.block_app = Mock()
    registry.unblock_apps = Mock(return_value=set())
    return registry


@pytest.fixture
def mock_factory() -> MagicMock:
    """Create a mock AppFactory."""
    factory = MagicMock()
    factory.create_instances = Mock()
    factory.check_only_app_decorator = Mock(return_value=False)
    return factory


@pytest.fixture
def mock_manifest() -> MagicMock:
    """Create a mock AppManifest instance."""
    manifest = MagicMock()
    manifest.class_name = "TestApp"
    manifest.app_key = "test_app"
    manifest.full_path = Path("/apps/test_app.py")
    manifest.display_name = "Test App"
    manifest.enabled = True
    return manifest


@pytest.fixture
def mock_app_instance() -> AsyncMock:
    """Create a mock App instance."""
    app = AsyncMock()
    app.app_config = MagicMock()
    app.app_config.instance_name = "test_instance"
    app.status = ResourceStatus.NOT_STARTED
    app.class_name = "MockApp"
    app.initialize = AsyncMock()
    app.shutdown = AsyncMock()
    app.mark_ready = Mock()
    app.logger = Mock()
    app.bus = MagicMock()
    app.bus.get_listeners = Mock(return_value=[])
    app.bus.owner_id = "MockApp.test_instance"
    app.scheduler = MagicMock()
    app.scheduler.get_job_db_ids = Mock(return_value=[])
    return app


@pytest.fixture
def lifecycle_service(
    mock_hassette: MagicMock, mock_registry: MagicMock, mock_factory: MagicMock
) -> AppLifecycleService:
    """Create an AppLifecycleService with mocked dependencies."""
    logging.getLogger("hassette").propagate = True

    with (
        patch("hassette.core.app_lifecycle_service.AppFactory", return_value=mock_factory),
        patch("hassette.core.app_lifecycle_service.AppChangeDetector"),
    ):
        service = AppLifecycleService(mock_hassette, parent=None, registry=mock_registry)
    service.factory = mock_factory
    return service


def make_executor(*, error_handler_timeout: float = 5.0) -> CommandExecutor:
    """Build a CommandExecutor with all dependencies mocked out."""
    hassette = MagicMock()
    hassette.config.database.telemetry_write_queue_max = 1000
    hassette.config.logging.command_executor = "DEBUG"
    hassette.config.lifecycle.error_handler_timeout_seconds = error_handler_timeout
    hassette.database_service = MagicMock()
    hassette.session_id = 42
    executor = CommandExecutor.__new__(CommandExecutor)
    executor._write_queue = asyncio.Queue(maxsize=1000)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._dropped_no_session = 0
    executor._dropped_shutdown = 0
    executor._error_handler_failures = 0
    executor._last_capacity_warn_ts = 0.0
    executor._timeout_warn_timestamps = {}
    executor.repository = MagicMock()
    executor.hassette = hassette
    executor._logger = MagicMock()
    executor.logger = MagicMock()

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    spawned_tasks: list[asyncio.Task] = []

    def spawn(coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        spawned_tasks.append(task)
        return task

    task_bucket.spawn = spawn
    executor.task_bucket = task_bucket
    executor._spawned_tasks = spawned_tasks
    return executor


def make_bus_service(*, config_timeout: float | None = 600.0) -> BusService:
    """Create a BusService with mocked internals, bypassing Resource.__init__."""
    svc = BusService.__new__(BusService)
    svc.hassette = MagicMock()
    svc.hassette.config.lifecycle.event_handler_timeout_seconds = config_timeout
    svc.hassette.config.bus_excluded_domains = ()
    svc.hassette.config.bus_excluded_entities = ()
    svc.hassette.config.logging.all_events = False
    svc.hassette.config.lifecycle.registration_await_timeout = 30
    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()
    svc._executor.register_listener = AsyncMock(return_value=0)
    svc.logger = MagicMock()
    svc._config_resolver = lambda: config_timeout
    svc._event_filter = EventFilter(
        excluded_domains=(),
        excluded_entities=(),
        logger=svc.logger,
    )
    svc.router = Router()
    task_bucket = MagicMock()
    task_bucket.spawn = MagicMock(side_effect=lambda coro, **_kw: asyncio.ensure_future(coro))
    svc.task_bucket = task_bucket
    svc._duration_hold = DurationHoldManager(
        executor=svc._executor,
        config_resolver=svc._config_resolver,
        state_reader=lambda _entity_id: None,
        remove_listener=lambda _listener: None,
        router=svc.router,
        task_bucket=task_bucket,
        logger=svc.logger,
    )
    return svc
