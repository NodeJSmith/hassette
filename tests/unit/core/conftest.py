"""Shared fixtures and constants for tests/unit/core/."""

import asyncio
import logging
import shutil
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiosqlite
import pytest

from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.router import Router
from hassette.commands import ExecuteJob
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.bus_service import BusService, compute_elapsed, make_synthetic_state_event
from hassette.core.command_executor import CommandExecutor, ExecutionMarker
from hassette.core.event_filter import EventFilter
from hassette.core.scheduler_service import SchedulerService
from hassette.core.service_watcher import ServiceWatcher
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types.enums import BlockingIOBehavior, ResourceStatus, RestartType

# Minimal DDL for telemetry tests — intentionally omits many real columns.
# See test_database_service_migrations.py for the canonical schema contract.
TELEMETRY_TEST_DDL = """
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
    hassette.scheduler_service.remove_jobs_by_owner = MagicMock(side_effect=lambda _owner: asyncio.sleep(0))
    hassette.session_id = 1
    hassette.try_session_id.return_value = 1
    return hassette


def set_registry_apps(registry: MagicMock, apps: dict[str, dict[int, Any]]) -> None:
    """Configure a mock AppRegistry's app-lookup methods from an apps-shaped dict.

    Mirrors the real AppRegistry's `__contains__`, `app_keys()`, and
    `get_apps_by_key()` behavior so lifecycle-service code exercising those
    methods sees consistent state.
    """
    registry.__contains__ = Mock(side_effect=lambda key: key in apps)
    registry.app_keys = Mock(side_effect=lambda: list(apps.keys()))
    registry.get_apps_by_key = Mock(side_effect=lambda key: apps.get(key, {}).copy())
    registry.get = Mock(side_effect=lambda key, index=0: apps.get(key, {}).get(index))


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create a mock AppRegistry instance."""
    registry = MagicMock()
    registry.record_failure = Mock()
    registry.all_apps = Mock(return_value=[])
    registry.clear_all = Mock()
    registry.get_manifest = Mock(return_value=None)
    registry.register_app = Mock()
    registry.unregister_app = Mock(return_value=None)
    registry.set_manifests = Mock()
    registry.set_only_app = Mock()
    set_registry_apps(registry, {})
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


def make_mock_app_instance(*, instance_name: str = "test_instance", class_name: str = "MockApp") -> AsyncMock:
    """Create a mock App instance with bus/scheduler stubs."""
    app = AsyncMock()
    app.app_config = MagicMock(instance_name=instance_name)
    app.status = ResourceStatus.NOT_STARTED
    app.class_name = class_name
    app.initialize = AsyncMock()
    app.shutdown = AsyncMock()
    app.mark_ready = Mock()
    app.logger = Mock()
    app.bus = MagicMock()
    app.bus.get_listeners = Mock(return_value=[])
    app.bus.owner_id = f"{class_name}.{instance_name}"
    app.scheduler = MagicMock()
    app.scheduler.get_job_db_ids = Mock(return_value=[])
    return app


@pytest.fixture
def mock_app_instance() -> AsyncMock:
    return make_mock_app_instance()


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
    hassette.try_session_id.return_value = 42
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


def make_mock_cmd_listener(
    *,
    side_effect: Any = None,
    error_handler: Callable[..., Any] | None = None,
) -> MagicMock:
    """Build a MagicMock standing in for a Listener in CommandExecutor tests."""
    listener = MagicMock()
    listener.listener_id = 1
    listener.invoker.error_handler = error_handler
    if side_effect is None:
        listener.invoker.invoke = AsyncMock(return_value=None)
    else:
        listener.invoker.invoke = AsyncMock(side_effect=side_effect)
    listener.__repr__ = lambda _self: "Listener<test>"
    return listener


def make_execute_job_cmd(
    *,
    side_effect: Any = None,
    job_error_handler: Callable[..., Any] | None = None,
    app_level_error_handler: Callable[..., Any] | None = None,
    job_id: int = 99,
) -> MagicMock:
    """Build a MagicMock spec'd to ExecuteJob for CommandExecutor tests."""
    cmd = MagicMock(spec=ExecuteJob)
    cmd.source_tier = "app"
    cmd.job_db_id = 1
    if side_effect is None:
        cmd.callable = AsyncMock(return_value=None)
    else:
        cmd.callable = AsyncMock(side_effect=side_effect)
    cmd.effective_timeout = None
    cmd.job = MagicMock()
    cmd.job.job_id = job_id
    cmd.job.error_handler = job_error_handler
    cmd.job.name = "test_job"
    cmd.job.group = None
    cmd.job.args = ()
    cmd.job.kwargs = {}
    cmd.app_level_error_handler = app_level_error_handler
    return cmd


class DummyService(Service):
    """Minimal concrete Service for watcher-level tests."""

    restart_spec: RestartSpec = RestartSpec(restart_type=RestartType.TRANSIENT)

    async def serve(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise


class TempService(Service):
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


def make_scheduler_service(
    *,
    config_timeout: float | None = 600.0,
    behind_schedule_threshold: float = 60,
) -> SchedulerService:
    """Create a SchedulerService with mocked internals, bypassing Resource.__init__."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.scheduler.behind_schedule_threshold_seconds = behind_schedule_threshold
    svc.hassette.config.scheduler.job_timeout_seconds = config_timeout
    svc._removal_callbacks = {}
    svc.logger = MagicMock()
    svc._wakeup_event = asyncio.Event()

    svc._job_queue = MagicMock()
    svc._job_queue.add = AsyncMock(return_value=None)
    svc._job_queue.remove_job = AsyncMock(return_value=True)

    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()

    svc.task_bucket = MagicMock()
    svc.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    # Close coroutines immediately to avoid "coroutine was never awaited" warnings
    def _spawn(coro, **_kwargs):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    svc.task_bucket.spawn = _spawn

    return svc


def make_blocking_io_hassette(
    *,
    behavior: BlockingIOBehavior | None = None,
    watchdog_enabled: bool = True,
    lag_threshold_seconds: float = 0.10,
    watchdog_interval_seconds: float = 0.25,
    capture_stack_on_block: bool = False,
    dev_mode: bool = True,
    deep_detection_enabled: bool | None = None,
    allow_deep_detection_in_prod: bool = False,
) -> MagicMock:
    """Minimal mock Hassette for blocking-IO guard and watchdog tests."""
    cfg = MagicMock()
    cfg.dev_mode = dev_mode
    cfg.blocking_io.watchdog_enabled = watchdog_enabled
    cfg.blocking_io.lag_threshold_seconds = lag_threshold_seconds
    cfg.blocking_io.watchdog_interval_seconds = watchdog_interval_seconds
    cfg.blocking_io.capture_stack_on_block = capture_stack_on_block
    cfg.blocking_io.deep_detection_enabled = deep_detection_enabled
    cfg.blocking_io.allow_deep_detection_in_prod = allow_deep_detection_in_prod
    cfg.blocking_io.behavior = behavior
    h = MagicMock()
    h.config = cfg
    h.app_handler.get.return_value = None
    # resolve_blocking_io_behavior falls through two hops: per-app → global.
    # None here forces the fallthrough to the global path.
    h.app_config.blocking_io_behavior = None
    h.hassette.config.blocking_io.behavior = behavior
    return h


def make_marker_executor(
    *,
    app_key: str | None = "test_app",
    instance_index: int | None = None,
    stamp_task_id: bool = False,
    execution_id: str = "exec-test",
) -> MagicMock:
    """Build a mock executor with an ExecutionMarker on current_execution.

    For watchdog tests, pass stamp_task_id=True to attribute blocks to the current task.
    For monkeypatch tests, pass instance_index to identify the app instance.
    """
    executor = MagicMock()
    task_id = None
    if stamp_task_id:
        task = asyncio.current_task()
        task_id = id(task) if task is not None else None
    executor.current_execution = ExecutionMarker(
        app_key=app_key,
        instance_name=None,
        execution_id=execution_id,
        started_at=time.monotonic(),
        task_id=task_id,
        instance_index=instance_index,
    )
    return executor


@pytest.fixture
async def telemetry_db(_migrated_db_template: Path, tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Migrated SQLite connection with FK enforcement on."""
    dst = tmp_path / "hassette.db"
    shutil.copy2(_migrated_db_template, dst)
    async with aiosqlite.connect(dst) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
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
