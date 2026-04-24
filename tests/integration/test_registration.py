"""Integration tests for DB registration using app_key and the non-App owner guard.

Tests verify:
1. ListenerRegistration and ScheduledJobRegistration use app_key/instance_index (not owner_id)
2. Empty app_key (non-App owners like RuntimeQueryService) skips DB registration entirely
3. The guard still routes listeners/jobs through the in-memory path (Router add, Queue enqueue)
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.scheduler_service import SchedulerService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config pointing to tmp_path."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.command_executor_log_level = "INFO"
    hassette.config.bus_service_log_level = "INFO"
    hassette.config.scheduler_service_log_level = "INFO"
    hassette.config.scheduler_min_delay_seconds = 0.1
    hassette.config.scheduler_max_delay_seconds = 60.0
    hassette.config.scheduler_default_delay_seconds = 1.0
    hassette.config.bus_excluded_domains = ()
    hassette.config.bus_excluded_entities = ()
    hassette.config.log_all_events = False
    hassette.config.log_all_hass_events = False
    hassette.config.log_all_hassette_events = False
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def initialized_db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a real DatabaseService and create a session row."""
    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    try:
        ts = time.time()
        cursor = await db_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (ts, ts),
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        mock_hassette.session_id = session_id
        await db_service.db.commit()
        mock_hassette.database_service = db_service
        yield db_service, session_id
    finally:
        await db_service.on_shutdown()


@pytest.fixture
async def executor(mock_hassette: MagicMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """Create and prepare a CommandExecutor with real DB wired in."""
    mock_hassette.wait_for_ready = AsyncMock(return_value=True)
    exc = CommandExecutor(mock_hassette, parent=mock_hassette)
    await exc.on_initialize()
    return exc


def _make_mock_listener(
    *, owner_id: str = "test_owner", app_key: str = "my_app", instance_index: int = 1, topic: str = "hass.event.test"
) -> MagicMock:
    """Return a mock Listener with configurable app_key and instance_index."""
    listener = MagicMock()
    listener.owner_id = owner_id
    listener.app_key = app_key
    listener.instance_index = instance_index
    listener.topic = topic
    listener.handler_name = "MyApp.on_event"
    listener.debounce = None
    listener.throttle = None
    listener.rate_limiter = None
    listener.once = False
    listener.priority = 0
    listener.predicate = None
    listener.listener_id = 1
    listener.db_id = None
    return listener


def _make_mock_job(
    *, owner_id: str = "test_owner", app_key: str = "my_app", instance_index: int = 1, name: str = "test_job"
) -> MagicMock:
    """Return a mock ScheduledJob."""
    job = MagicMock()
    job.owner_id = owner_id
    job.app_key = app_key
    job.instance_index = instance_index
    job.name = name
    job.job = MagicMock(__qualname__="MyApp.my_job")
    job.trigger = None
    job.args = ()
    job.kwargs = {}
    job.db_id = None
    return job


def _stub_task_bucket() -> MagicMock:
    """Create a task_bucket stub whose spawn() captures and closes coroutines.

    Coroutines passed to spawn() are closed immediately to avoid RuntimeWarning.
    """
    bucket = MagicMock()
    task = MagicMock()
    task.done.return_value = True

    def _spawn(coro: object, **kwargs: object) -> MagicMock:  # noqa: ARG001
        if asyncio.iscoroutine(coro):
            coro.close()
        return task

    bucket.spawn.side_effect = _spawn
    return bucket


# ---------------------------------------------------------------------------
# Listener registration uses app_key and instance_index
# ---------------------------------------------------------------------------


async def test_listener_registration_persists_correct_app_key(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """register_listener() on CommandExecutor persists the correct app_key and instance_index."""
    db_service, _ = initialized_db
    reg = ListenerRegistration(
        app_key="my_app",
        instance_index=2,
        handler_method="MyApp.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_registration.py:1",
        registration_source=None,
    )
    listener_id = await executor.register_listener(reg)
    assert listener_id > 0

    cursor = await db_service.db.execute(
        "SELECT app_key, instance_index FROM listeners WHERE id = ?",
        (listener_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "my_app", f"Expected app_key='my_app', got {row[0]!r}"
    assert row[1] == 2, f"Expected instance_index=2, got {row[1]}"


async def test_job_registration_persists_correct_app_key(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """register_job() on CommandExecutor persists the correct app_key and instance_index."""
    db_service, _ = initialized_db
    reg = ScheduledJobRegistration(
        app_key="my_app",
        instance_index=3,
        job_name="test_job",
        handler_method="MyApp.my_job",
        trigger_type=None,
        trigger_label="once",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test_registration.py:1",
        registration_source=None,
    )
    job_id = await executor.register_job(reg)
    assert job_id > 0

    cursor = await db_service.db.execute(
        "SELECT app_key, instance_index FROM scheduled_jobs WHERE id = ?",
        (job_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "my_app", f"Expected app_key='my_app', got {row[0]!r}"
    assert row[1] == 3, f"Expected instance_index=3, got {row[1]}"


# ---------------------------------------------------------------------------
# BusService._register_then_add_route registers listener then adds route
# ---------------------------------------------------------------------------


def test_listener_with_app_key_spawns_combined_task(mock_hassette: MagicMock) -> None:
    """add_listener with app_key spawns a single _register_then_add_route task."""
    executor_mock = MagicMock()
    stream = MagicMock()
    bus_service = BusService(mock_hassette, stream=stream, executor=executor_mock, parent=mock_hassette)
    bus_service.task_bucket = _stub_task_bucket()

    listener = _make_mock_listener(owner_id="bus:MyApp:0", app_key="my_app", instance_index=2)

    bus_service.add_listener(listener)

    # Single combined spawn: _register_then_add_route
    assert bus_service.task_bucket.spawn.call_count == 1


# ---------------------------------------------------------------------------
# SchedulerService._register_then_enqueue registers job then enqueues
# ---------------------------------------------------------------------------


def test_job_with_app_key_spawns_combined_task(mock_hassette: MagicMock) -> None:
    """add_job with app_key spawns a single _register_then_enqueue task."""
    executor_mock = MagicMock()
    scheduler_service = SchedulerService(mock_hassette, executor=executor_mock, parent=mock_hassette)
    scheduler_service.task_bucket = _stub_task_bucket()

    job = _make_mock_job(owner_id="scheduler:MyApp:0", app_key="my_app", instance_index=3)

    scheduler_service.add_job(job)

    assert scheduler_service.task_bucket.spawn.call_count == 1


# ---------------------------------------------------------------------------
# Non-App owner guard: empty app_key skips DB registration
# ---------------------------------------------------------------------------


def test_listener_with_empty_app_key_skips_registration(mock_hassette: MagicMock) -> None:
    """Listeners with empty app_key (non-App owners) skip DB registration."""
    executor_mock = MagicMock()
    stream = MagicMock()
    bus_service = BusService(mock_hassette, stream=stream, executor=executor_mock, parent=mock_hassette)
    bus_service.task_bucket = _stub_task_bucket()

    listener = _make_mock_listener(app_key="", instance_index=0)

    bus_service.add_listener(listener)

    # Only one spawn call should have happened: the router.add_route call
    # The _register_listener_to_db call should NOT have happened
    assert bus_service.task_bucket.spawn.call_count == 1
    # The single spawn call should be for the router, not for registration
    spawn_kwargs = bus_service.task_bucket.spawn.call_args
    assert spawn_kwargs.kwargs.get("name") == "bus:add_listener"


def test_listener_with_app_key_triggers_registration(mock_hassette: MagicMock) -> None:
    """Listeners with non-empty app_key use a single combined register-then-route task."""
    executor_mock = MagicMock()
    stream = MagicMock()
    bus_service = BusService(mock_hassette, stream=stream, executor=executor_mock, parent=mock_hassette)
    bus_service.task_bucket = _stub_task_bucket()

    listener = _make_mock_listener(app_key="my_app", instance_index=1)

    bus_service.add_listener(listener)

    # Single spawn: _register_then_add_route (DB registration + router add in sequence)
    assert bus_service.task_bucket.spawn.call_count == 1


def test_job_with_empty_app_key_skips_registration(mock_hassette: MagicMock) -> None:
    """Jobs with empty app_key (non-App owners) skip DB registration."""
    executor_mock = MagicMock()
    scheduler_service = SchedulerService(mock_hassette, executor=executor_mock, parent=mock_hassette)
    scheduler_service.task_bucket = _stub_task_bucket()

    job = _make_mock_job(app_key="", instance_index=0)

    scheduler_service.add_job(job)

    # Only one spawn call: the _enqueue_job call
    assert scheduler_service.task_bucket.spawn.call_count == 1
    spawn_kwargs = scheduler_service.task_bucket.spawn.call_args
    assert spawn_kwargs.kwargs.get("name") == "scheduler:add_job"


def test_job_with_app_key_triggers_registration(mock_hassette: MagicMock) -> None:
    """Jobs with non-empty app_key use a single combined register-then-enqueue task."""
    executor_mock = MagicMock()
    scheduler_service = SchedulerService(mock_hassette, executor=executor_mock, parent=mock_hassette)
    scheduler_service.task_bucket = _stub_task_bucket()

    job = _make_mock_job(app_key="my_app", instance_index=1)

    scheduler_service.add_job(job)

    # Single spawn: _register_then_enqueue (DB registration + enqueue in sequence)
    assert scheduler_service.task_bucket.spawn.call_count == 1


# ---------------------------------------------------------------------------
# Group persistence at registration
# ---------------------------------------------------------------------------


async def test_group_persisted_at_registration(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """A job registered with group='morning' has the value written to the DB."""
    db_service, _ = initialized_db
    reg = ScheduledJobRegistration(
        app_key="my_app",
        instance_index=0,
        job_name="morning_job",
        handler_method="MyApp.morning_job",
        trigger_type="cron",
        trigger_label="daily at 07:00",
        trigger_detail="0 7 * * *",
        args_json="[]",
        kwargs_json="{}",
        source_location="test_registration.py:1",
        registration_source=None,
        group="morning",
    )
    job_id = await executor.register_job(reg)
    assert job_id > 0

    cursor = await db_service.db.execute(
        'SELECT "group" FROM scheduled_jobs WHERE id = ?',
        (job_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "morning", f"Expected group='morning' in DB, got {row[0]!r}"
