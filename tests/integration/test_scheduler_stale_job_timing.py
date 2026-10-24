"""SchedulerService clears timing left on job rows not registered this session once apps finish loading."""

import typing
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.scheduler_service import SchedulerService
from hassette.events.hassette import HassetteSimpleEvent
from hassette.scheduler.triggers import Every
from hassette.testing import HassetteHarness, wait_for
from hassette.types.enums import Topic
from tests.support.factories import make_job_registration, make_scheduled_job

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import HassetteConfig


@pytest.fixture
async def executor(db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """Create and prepare a CommandExecutor with real DB wired in."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    return exc


async def fetch_timing(db_service: DatabaseService, job_id: int) -> tuple[object, ...]:
    """Return the (next_run, fire_at, jitter) columns of a scheduled_jobs row."""
    cursor = await db_service.db.execute("SELECT next_run, fire_at, jitter FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    return tuple(row)


async def test_app_load_completed_clears_timing_of_unregistered_job(
    db_hassette: AsyncMock,
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """A removed app's job row loses its timing; a job registered this session keeps its timing."""
    db_service, _ = initialized_db
    scheduler_service = SchedulerService(db_hassette, executor=executor, parent=db_hassette)

    live_job = make_scheduled_job(name="live_job", trigger=Every(minutes=5), jitter=30.0)
    live_job.app_key = "my_app"
    await scheduler_service.add_job(live_job)
    assert live_job.db_id is not None
    live_timing = await fetch_timing(db_service, live_job.db_id)
    assert live_timing[0] is not None

    removed_reg = replace(
        make_job_registration(app_key="removed_app", job_name="removed_job"), next_run=500.0, fire_at=502.0, jitter=5.0
    )
    removed_id = await executor.register_job(removed_reg)

    await scheduler_service.on_app_load_completed()

    assert await fetch_timing(db_service, removed_id) == (None, None, None)
    assert await fetch_timing(db_service, live_job.db_id) == live_timing


async def test_app_load_completed_event_triggers_clear_with_live_job_ids(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> None:
    """The listener registered in on_initialize() routes APP_LOAD_COMPLETED to the clear with every live job id."""
    async with hassette_harness(test_config).with_scheduler() as harness:
        job = await harness.scheduler.run_in(lambda: None, delay=600, name="stale_timing_live_job")
        service = harness.scheduler_service
        clear = service._executor.clear_stale_job_timing

        await harness.hassette.send_event(HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED))
        await wait_for(lambda: clear.await_count == 1, desc="clear_stale_job_timing call")

        (live_ids,) = clear.await_args.args
        assert job.db_id in live_ids
        assert sorted(live_ids) == sorted(service._jobs_by_id)
        job.remove()
