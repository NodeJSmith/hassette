"""Shared fixtures and constants for tests/unit/core/."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiosqlite
import pytest

from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.router import Router
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.bus_service import BusService, compute_elapsed, make_synthetic_state_event
from hassette.core.command_executor import CommandExecutor
from hassette.core.event_filter import EventFilter
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types.enums import ResourceStatus, RestartType

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

CREATE TABLE sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            REAL NOT NULL DEFAULT 0,
    last_heartbeat_at     REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    name                  TEXT NOT NULL DEFAULT '',
    handler_method        TEXT NOT NULL DEFAULT '',
    topic                 TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    mode                  TEXT NOT NULL DEFAULT 'single',
    retired_at            REAL
);

CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    job_name              TEXT NOT NULL DEFAULT '',
    handler_method        TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    retired_at            REAL,
    mode                  TEXT NOT NULL DEFAULT 'single'
);

CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT NOT NULL DEFAULT 'handler',
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL DEFAULT 0,
    execution_start_ts    REAL NOT NULL,
    duration_ms           REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'success',
    thread_leaked         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE blocking_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER REFERENCES sessions(id),
    app_key          TEXT,
    instance_name    TEXT,
    instance_index   INTEGER,
    execution_id     TEXT,
    tier             TEXT NOT NULL
        CHECK (tier IN ('watchdog', 'monkeypatch')),
    primitive        TEXT,
    source_location  TEXT,
    stall_duration_ms REAL,
    detected_ts      REAL NOT NULL,
    source_tier      TEXT NOT NULL
        CHECK (source_tier IN ('app', 'framework')),
    reason           TEXT
        CHECK (reason IN ('attributed', 'framework', 'displaced'))
);
CREATE INDEX idx_be_ts      ON blocking_events(detected_ts);
CREATE INDEX idx_be_app_ts  ON blocking_events(app_key, detected_ts);
CREATE INDEX idx_be_session ON blocking_events(session_id);
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
    hassette.bus_service.router = MagicMock()
    hassette.bus_service.router.get_listeners_by_owner = Mock(return_value=[])
    hassette.scheduler_service = MagicMock()
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
    registry.autostart_manifests = {}
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


class _DummyService(Service):
    """Minimal concrete Service for watcher-level tests."""

    restart_spec: RestartSpec = RestartSpec(restart_type=RestartType.TRANSIENT)

    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


class _TempService(Service):
    """TEMPORARY restart type service for EXHAUSTED_DEAD tests."""

    restart_spec: RestartSpec = RestartSpec(restart_type=RestartType.TEMPORARY)

    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


def build_watcher_hassette(*, strict_lifecycle: bool = False) -> AsyncMock:
    """Minimal Hassette stub for ServiceWatcher unit tests."""
    hassette = make_mock_hassette(
        sealed=False,
        strict_lifecycle=strict_lifecycle,
        lifecycle={"resource_shutdown_timeout_seconds": 1, "task_cancellation_timeout_seconds": 1},
    )
    hassette.send_event = AsyncMock()
    hassette.shutdown = AsyncMock()
    return hassette


def make_watcher(hassette: MagicMock) -> ServiceWatcher:
    """Build a ServiceWatcher bypassing __init__ (no real Bus child needed)."""
    watcher = ServiceWatcher.__new__(ServiceWatcher)
    watcher.ready_event = asyncio.Event()
    watcher.shutdown_event = asyncio.Event()
    watcher._ready_reason = None
    watcher._status = ResourceStatus.NOT_STARTED
    watcher._previous_status = ResourceStatus.NOT_STARTED
    watcher.shutdown_completed = False
    watcher.shutting_down = False
    watcher.initializing = False
    watcher._init_task = None
    watcher._cache = None
    watcher.hassette = hassette
    watcher.parent = hassette
    watcher.children = []
    watcher._budgets = {}
    watcher._restarting = set()
    watcher._cooldown_tasks = {}
    watcher._cooldown_cycles = {}
    watcher.logger = logging.getLogger("hassette.test.service_watcher")
    task_bucket = MagicMock()
    task_bucket.spawn = Mock(side_effect=lambda coro, **_kw: asyncio.create_task(coro))
    watcher.task_bucket = task_bucket
    watcher.bus = MagicMock()
    watcher.bus.on = AsyncMock()
    return watcher


def make_bus_service(*, config_timeout: float | None = 600.0, max_concurrent_dispatches: int = 50) -> BusService:
    """Create a BusService with mocked internals, bypassing Resource.__init__."""
    svc = BusService.__new__(BusService)
    svc.hassette = MagicMock()
    svc.hassette.config.lifecycle.event_handler_timeout_seconds = config_timeout
    svc.hassette.config.lifecycle.max_concurrent_dispatches = max_concurrent_dispatches
    svc.hassette.config.bus_excluded_domains = ()
    svc.hassette.config.bus_excluded_entities = ()
    svc.hassette.config.logging.all_events = False
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
    task_bucket.spawn = MagicMock(side_effect=lambda coro, **_kw: asyncio.create_task(coro))
    svc.task_bucket = task_bucket
    svc._duration_hold = DurationHoldManager(
        executor=svc._executor,
        config_resolver=svc._config_resolver,
        state_reader=lambda _entity_id: None,
        remove_listener=lambda _listener: None,
        router=svc.router,
        task_bucket=task_bucket,
        logger=svc.logger,
        make_synthetic_event=make_synthetic_state_event,
        compute_elapsed=compute_elapsed,
    )
    svc._dispatch_pending = 0
    svc._dispatch_idle_event = asyncio.Event()
    svc._dispatch_idle_event.set()
    svc._dispatch_semaphore = asyncio.Semaphore(max_concurrent_dispatches)
    svc._last_saturation_warn_ts = 0.0
    return svc


# DDL mirrors 001.sql — keep in sync with src/hassette/migrations_sql/001.sql
TELEMETRY_REPO_DDL = """
CREATE TABLE sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            REAL    NOT NULL,
    stopped_at            REAL,
    last_heartbeat_at     REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT
);

CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,
    instance_index        INTEGER NOT NULL,
    name                  TEXT    NOT NULL,
    handler_method        TEXT    NOT NULL,
    topic                 TEXT    NOT NULL,
    debounce              REAL,
    throttle              REAL,
    once                  INTEGER NOT NULL DEFAULT 0,
    priority              INTEGER NOT NULL DEFAULT 0,
    mode                  TEXT    NOT NULL DEFAULT 'single',
    backpressure          TEXT    NOT NULL DEFAULT 'block' CHECK (backpressure IN ('block', 'drop_newest')),
    predicate_description TEXT,
    human_description     TEXT,
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    source_tier           TEXT    NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework')),
    retired_at            REAL,
    cancelled_at          REAL,
    immediate             INTEGER NOT NULL DEFAULT 0,
    duration              REAL,
    entity_id             TEXT
);

CREATE UNIQUE INDEX idx_listeners_natural
    ON listeners(app_key, instance_index, name, topic);

CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index);

CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,
    instance_index        INTEGER NOT NULL,
    job_name              TEXT    NOT NULL,
    handler_method        TEXT    NOT NULL,
    trigger_type          TEXT
        CHECK (trigger_type IN ('interval', 'cron', 'once', 'after', 'custom')),
    trigger_label         TEXT    NOT NULL DEFAULT '',
    trigger_detail        TEXT,
    repeat                INTEGER NOT NULL DEFAULT 0,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    source_tier           TEXT    NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework')),
    retired_at            REAL,
    "group"               TEXT,
    cancelled_at          REAL,
    name_auto             INTEGER NOT NULL DEFAULT 0,
    mode                  TEXT    NOT NULL DEFAULT 'single'
        CHECK (mode IN ('single', 'restart', 'queued', 'parallel'))
);

CREATE UNIQUE INDEX idx_scheduled_jobs_natural
    ON scheduled_jobs(app_key, instance_index, job_name);

CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index);

CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT    NOT NULL CHECK (kind IN ('handler', 'job')),
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT,
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
    source_tier           TEXT    NOT NULL DEFAULT 'app',
    execution_id          TEXT UNIQUE,
    trigger_context_id    TEXT,
    trigger_origin        TEXT,
    trigger_mode          TEXT,
    retry_count           INTEGER NOT NULL DEFAULT 0,
    attempt_number        INTEGER NOT NULL DEFAULT 1,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    thread_leaked         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_exec_listener_time
    ON executions(listener_id, execution_start_ts DESC)
    WHERE listener_id IS NOT NULL;
CREATE INDEX idx_exec_job_time
    ON executions(job_id, execution_start_ts DESC)
    WHERE job_id IS NOT NULL;

CREATE VIEW active_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL;

CREATE VIEW active_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL;
"""


@pytest.fixture
async def telemetry_db() -> AsyncIterator[aiosqlite.Connection]:
    """In-memory SQLite connection with the full telemetry schema applied."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(TELEMETRY_REPO_DDL)
        await conn.commit()
        yield conn


@pytest.fixture
async def telemetry_repo(telemetry_db: aiosqlite.Connection) -> TelemetryRepository:
    """TelemetryRepository backed by an in-memory SQLite connection."""
    mock_db_service = MagicMock()
    mock_db_service.db = telemetry_db
    return TelemetryRepository(mock_db_service)


@pytest.fixture
async def telemetry_session_id(telemetry_db: aiosqlite.Connection) -> int:
    """Insert a session row and return its ID (needed for FK constraints)."""
    now = time.time()
    cursor = await telemetry_db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await telemetry_db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid
