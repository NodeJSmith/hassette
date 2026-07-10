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
from hassette.test_utils.factories import make_job_registration, make_listener_registration, make_mock_listener
from hassette.types.enums import ExecutionMode

from .conftest import make_mock_job


@pytest.fixture
async def executor(db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """Create and prepare a CommandExecutor with real DB wired in."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    return exc


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
    reg = make_listener_registration(
        app_key="my_app",
        instance_index=2,
        handler_method="MyApp.on_event",
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


@pytest.mark.parametrize("mode", ["single", "restart", "queued", "parallel"])
async def test_listener_registration_persists_mode(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    mode: str,
) -> None:
    """register_listener() persists the resolved execution mode."""
    db_service, _ = initialized_db
    reg = make_listener_registration(
        app_key="my_app",
        handler_method="MyApp.on_event",
        name=f"listener_{mode}",
        mode=mode,
    )
    listener_id = await executor.register_listener(reg)

    cursor = await db_service.db.execute("SELECT mode FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == mode


async def test_listener_mode_updates_on_reregistration(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """A mode-only change updates the persisted mode on the same row via the upsert."""
    db_service, _ = initialized_db

    def make_reg(mode: str) -> ListenerRegistration:
        return make_listener_registration(
            app_key="my_app",
            handler_method="MyApp.on_event",
            name="reg_mode_listener",
            mode=mode,
        )

    first_id = await executor.register_listener(make_reg("single"))
    second_id = await executor.register_listener(make_reg("queued"))

    # Same natural key -> same row preserved, mode updated in place.
    assert second_id == first_id
    cursor = await db_service.db.execute("SELECT mode FROM listeners WHERE id = ?", (first_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "queued"


async def test_job_registration_persists_correct_app_key(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """register_job() on CommandExecutor persists the correct app_key and instance_index."""
    db_service, _ = initialized_db
    reg = make_job_registration(
        app_key="my_app",
        instance_index=3,
        handler_method="MyApp.my_job",
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


async def test_listener_with_app_key_spawns_combined_task(db_hassette: AsyncMock) -> None:
    """add_listener with app_key registers the listener in DB inline and inserts the route.

    DB registration is now awaited inline (not spawned). Route insertion is synchronous.
    """
    executor_mock = MagicMock()
    executor_mock.register_listener = AsyncMock(return_value=99)
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor_mock, parent=db_hassette)
    bus_service.task_bucket = stub_task_bucket()

    listener = make_mock_listener(owner_id="bus:MyApp:0", app_key="my_app", instance_index=2)

    await bus_service.add_listener(listener)

    # DB registration is awaited inline — executor.register_listener must be called once.
    executor_mock.register_listener.assert_called_once()


async def test_job_with_app_key_spawns_combined_task(db_hassette: AsyncMock) -> None:
    """add_job with app_key registers the job in DB inline, then enqueues it.

    DB registration and enqueue are now awaited inline (not spawned).
    """
    executor_mock = MagicMock()
    executor_mock.register_job = AsyncMock(return_value=55)
    scheduler_service = SchedulerService(db_hassette, executor=executor_mock, parent=db_hassette)
    scheduler_service.task_bucket = stub_task_bucket()
    scheduler_service._job_queue = AsyncMock()

    job = make_mock_job(owner_id="scheduler:MyApp:0", app_key="my_app", instance_index=3)

    await scheduler_service.add_job(job)

    # DB registration is awaited inline — executor.register_job must be called once.
    executor_mock.register_job.assert_called_once()
    reg_arg = executor_mock.register_job.call_args.args[0]
    assert reg_arg.app_key == "my_app"
    assert reg_arg.instance_index == 3
    # mode threads through from job.mode.value to the registration
    assert reg_arg.mode == "single"


async def test_listener_with_empty_app_key_spawns_db_registration(db_hassette: AsyncMock) -> None:
    """Listeners with empty app_key (non-App owners) are registered in DB inline.

    DB registration is awaited inline regardless of app_key. Route insertion is synchronous.
    """
    executor_mock = MagicMock()
    executor_mock.register_listener = AsyncMock(return_value=10)
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor_mock, parent=db_hassette)
    bus_service.task_bucket = stub_task_bucket()

    listener = make_mock_listener(app_key="", instance_index=0)

    await bus_service.add_listener(listener)

    # DB registration is awaited inline — executor.register_listener must be called once.
    executor_mock.register_listener.assert_called_once()


async def test_listener_with_app_key_triggers_registration(db_hassette: AsyncMock) -> None:
    """Listeners with non-empty app_key trigger executor.register_listener inline.

    DB registration is awaited inline; the route is inserted synchronously after.
    """
    executor_mock = MagicMock()
    executor_mock.register_listener = AsyncMock(return_value=7)
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor_mock, parent=db_hassette)
    bus_service.task_bucket = stub_task_bucket()

    listener = make_mock_listener(app_key="my_app", instance_index=1)

    await bus_service.add_listener(listener)

    executor_mock.register_listener.assert_called_once()


async def test_job_with_empty_app_key_skips_registration(db_hassette: AsyncMock) -> None:
    """Jobs with empty app_key (non-App owners) are registered in DB inline (#547).

    All jobs now go through DB registration regardless of app_key.
    """
    executor_mock = MagicMock()
    executor_mock.register_job = AsyncMock(return_value=0)
    scheduler_service = SchedulerService(db_hassette, executor=executor_mock, parent=db_hassette)
    scheduler_service.task_bucket = stub_task_bucket()
    scheduler_service._job_queue = AsyncMock()

    job = make_mock_job(app_key="", instance_index=0)

    await scheduler_service.add_job(job)

    # executor.register_job is always called — empty app_key is no longer a skip signal.
    executor_mock.register_job.assert_called_once()
    reg_arg = executor_mock.register_job.call_args.args[0]
    assert reg_arg.app_key == ""


async def test_job_with_app_key_triggers_registration(db_hassette: AsyncMock) -> None:
    """Jobs with non-empty app_key trigger executor.register_job inline, then enqueue."""
    executor_mock = MagicMock()
    executor_mock.register_job = AsyncMock(return_value=42)
    scheduler_service = SchedulerService(db_hassette, executor=executor_mock, parent=db_hassette)
    scheduler_service.task_bucket = stub_task_bucket()
    scheduler_service._job_queue = AsyncMock()

    job = make_mock_job(app_key="my_app", instance_index=1)

    await scheduler_service.add_job(job)

    executor_mock.register_job.assert_called_once()
    reg_arg = executor_mock.register_job.call_args.args[0]
    assert reg_arg.app_key == "my_app"
    assert reg_arg.instance_index == 1


@pytest.mark.parametrize("mode_str", ["single", "restart", "queued", "parallel"])
async def test_job_registration_persists_mode(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    mode_str: str,
) -> None:
    """register_job() persists the resolved execution mode to scheduled_jobs.mode.

    Memory→DB only: mode is written via the upsert and is display/telemetry only.
    The column is never read back to reconstruct the guard.
    """
    db_service, _ = initialized_db
    reg = make_job_registration(
        app_key="my_app",
        job_name=f"mode_job_{mode_str}",
        handler_method="MyApp.my_job",
        mode=ExecutionMode(mode_str),
    )
    job_id = await executor.register_job(reg)
    assert job_id > 0

    cursor = await db_service.db.execute(
        "SELECT mode FROM scheduled_jobs WHERE id = ?",
        (job_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == mode_str, f"Expected mode={mode_str!r}, got {row[0]!r}"


async def test_job_mode_updates_on_reregistration(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """A mode-only change updates the persisted mode on the same row via the upsert."""
    db_service, _ = initialized_db

    def make_reg(mode: str) -> ScheduledJobRegistration:
        return make_job_registration(
            app_key="my_app",
            job_name="rereg_mode_job",
            handler_method="MyApp.my_job",
            mode=ExecutionMode(mode),
        )

    first_id = await executor.register_job(make_reg("single"))
    second_id = await executor.register_job(make_reg("queued"))

    # Same natural key → same row preserved, mode updated in place.
    assert second_id == first_id
    cursor = await db_service.db.execute("SELECT mode FROM scheduled_jobs WHERE id = ?", (first_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "queued", f"Expected mode='queued' after re-registration, got {row[0]!r}"


async def test_group_persisted_at_registration(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """A job registered with group='morning' has the value written to the DB."""
    db_service, _ = initialized_db
    reg = make_job_registration(
        app_key="my_app",
        job_name="morning_job",
        handler_method="MyApp.morning_job",
        trigger_type="cron",
        trigger_label="daily at 07:00",
        trigger_detail="0 7 * * *",
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
