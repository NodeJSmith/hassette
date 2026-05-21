"""Integration tests for DB registration using app_key and the non-App owner guard.

Tests verify:
1. ListenerRegistration and ScheduledJobRegistration use app_key/instance_index (not owner_id)
2. Empty app_key (non-App owners like RuntimeQueryService) skips DB registration entirely
3. The guard still routes listeners/jobs through the in-memory path (Router add, Queue enqueue)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.scheduler_service import SchedulerService


@pytest.fixture
async def executor(db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """Create and prepare a CommandExecutor with real DB wired in."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    return exc


def make_mock_listener(
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
    # Must be None to avoid the duration-timer branch in add_listener.
    listener.duration_config = None
    return listener


def make_mock_job(
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


def stub_task_bucket() -> MagicMock:
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


def test_listener_with_app_key_spawns_combined_task(db_hassette: AsyncMock) -> None:
    """add_listener with app_key spawns a single bus:register_listener task.

    Route insertion is synchronous; only the DB registration background task is spawned.
    """
    executor_mock = MagicMock()
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor_mock, parent=db_hassette)
    bus_service.task_bucket = stub_task_bucket()

    listener = make_mock_listener(owner_id="bus:MyApp:0", app_key="my_app", instance_index=2)

    bus_service.add_listener(listener)

    # Single spawn: bus:register_listener (DB registration; route insertion is sync)
    assert bus_service.task_bucket.spawn.call_count == 1
    spawn_kwargs = bus_service.task_bucket.spawn.call_args
    assert spawn_kwargs.kwargs.get("name") == "bus:register_in_db"


def test_job_with_app_key_spawns_combined_task(db_hassette: AsyncMock) -> None:
    """add_job with app_key spawns a single _register_then_enqueue task."""
    executor_mock = MagicMock()
    scheduler_service = SchedulerService(db_hassette, executor=executor_mock, parent=db_hassette)
    scheduler_service.task_bucket = stub_task_bucket()

    job = make_mock_job(owner_id="scheduler:MyApp:0", app_key="my_app", instance_index=3)

    scheduler_service.add_job(job)

    assert scheduler_service.task_bucket.spawn.call_count == 1


def test_listener_with_empty_app_key_spawns_db_registration(db_hassette: AsyncMock) -> None:
    """Listeners with empty app_key (non-App owners) still spawn one DB registration task.

    Route insertion is now synchronous. The single spawn is the DB registration task
    (bus:register_listener), which uses the owner_id as the app_key fallback.
    """
    executor_mock = MagicMock()
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor_mock, parent=db_hassette)
    bus_service.task_bucket = stub_task_bucket()

    listener = make_mock_listener(app_key="", instance_index=0)

    bus_service.add_listener(listener)

    # One spawn call: the DB registration task (route insertion is now synchronous).
    assert bus_service.task_bucket.spawn.call_count == 1
    spawn_kwargs = bus_service.task_bucket.spawn.call_args
    assert spawn_kwargs.kwargs.get("name") == "bus:register_in_db"


def test_listener_with_app_key_triggers_registration(db_hassette: AsyncMock) -> None:
    """Listeners with non-empty app_key spawn a single bus:register_listener task.

    Route insertion is synchronous; the DB registration background task is always spawned.
    """
    executor_mock = MagicMock()
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor_mock, parent=db_hassette)
    bus_service.task_bucket = stub_task_bucket()

    listener = make_mock_listener(app_key="my_app", instance_index=1)

    bus_service.add_listener(listener)

    # Single spawn: bus:register_listener (DB registration; route insertion is now sync)
    assert bus_service.task_bucket.spawn.call_count == 1
    spawn_kwargs = bus_service.task_bucket.spawn.call_args
    assert spawn_kwargs.kwargs.get("name") == "bus:register_in_db"


def test_job_with_empty_app_key_skips_registration(db_hassette: AsyncMock) -> None:
    """Jobs with empty app_key (non-App owners) skip DB registration."""
    executor_mock = MagicMock()
    scheduler_service = SchedulerService(db_hassette, executor=executor_mock, parent=db_hassette)
    scheduler_service.task_bucket = stub_task_bucket()

    job = make_mock_job(app_key="", instance_index=0)

    scheduler_service.add_job(job)

    # Only one spawn call: the _enqueue_job call
    assert scheduler_service.task_bucket.spawn.call_count == 1
    spawn_kwargs = scheduler_service.task_bucket.spawn.call_args
    assert spawn_kwargs.kwargs.get("name") == "scheduler:add_job"


def test_job_with_app_key_triggers_registration(db_hassette: AsyncMock) -> None:
    """Jobs with non-empty app_key use a single combined register-then-enqueue task."""
    executor_mock = MagicMock()
    scheduler_service = SchedulerService(db_hassette, executor=executor_mock, parent=db_hassette)
    scheduler_service.task_bucket = stub_task_bucket()

    job = make_mock_job(app_key="my_app", instance_index=1)

    scheduler_service.add_job(job)

    # Single spawn: _register_then_enqueue (DB registration + enqueue in sequence)
    assert scheduler_service.task_bucket.spawn.call_count == 1


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
