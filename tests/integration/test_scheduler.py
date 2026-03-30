import asyncio
import typing
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from whenever import ZonedDateTime

if typing.TYPE_CHECKING:
    import pytest

from hassette import Hassette
from hassette.core.commands import ExecuteJob
from hassette.scheduler import ScheduledJob
from hassette.utils.date_utils import now

TZ = ZoneInfo("America/Chicago")


async def test_run_in_passes_args_kwargs_async(hassette_with_scheduler: Hassette) -> None:
    """run_in forwards args/kwargs to async callables."""
    job_executed = asyncio.Event()
    captured_arguments: list[tuple[int, int, bool]] = []

    async def target(a: int, b: int, *, flag: bool) -> None:
        captured_arguments.append((a, b, flag))
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01, args=(1, 2), kwargs={"flag": True})

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert captured_arguments == [(1, 2, True)], f"Expected [(1, 2, True)], got {captured_arguments}"


async def test_run_in_passes_args_kwargs_sync(hassette_with_scheduler: Hassette) -> None:
    """run_in forwards args/kwargs to sync callables."""
    event_loop = asyncio.get_running_loop()
    job_executed = asyncio.Event()
    captured_arguments: list[tuple[str, int]] = []

    def target(name: str, *, count: int) -> None:
        captured_arguments.append((name, count))
        event_loop.call_soon_threadsafe(job_executed.set)

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01, args=("sensor",), kwargs={"count": 3})

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert captured_arguments == [("sensor", 3)], f"Expected [('sensor', 3)], got {captured_arguments}"


def test_scheduled_job_copies_args_kwargs() -> None:
    """ScheduledJob stores copies so external mutations do not leak in."""
    args = [1, 2]
    kwargs = {"alpha": 99}

    job = ScheduledJob(
        owner_id="owner",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda *a, **kw: None,  # noqa
        args=args,  # pyright: ignore[reportArgumentType]
        kwargs=kwargs,
    )

    args.append(3)
    kwargs["alpha"] = 0

    assert job.args == (1, 2), f"Expected (1, 2), got {job.args}"
    assert job.kwargs == {"alpha": 99}, f"Expected {{'alpha': 99}}, got {job.kwargs}"


async def test_run_job_calls_executor(hassette_with_scheduler: Hassette) -> None:
    """run_job() delegates execution to CommandExecutor.execute() with an ExecuteJob command."""
    job_executed = asyncio.Event()

    async def target() -> None:
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    # Reset the mock call history and set up a stub that also runs the job
    scheduler_service = hassette_with_scheduler._scheduler_service
    assert scheduler_service is not None
    executor = scheduler_service._executor

    executed_cmds: list[ExecuteJob] = []

    async def _capturing_execute(cmd: object) -> None:
        if isinstance(cmd, ExecuteJob):
            executed_cmds.append(cmd)
            await cmd.callable()

    executor.execute.side_effect = _capturing_execute
    executor.execute.reset_mock()

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.05)
    # Simulate an app-owned job by setting db_id (internal jobs have db_id=None and bypass executor)
    scheduled_job.mark_registered(99)

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert len(executed_cmds) == 1, f"Expected executor.execute() called once, got {len(executed_cmds)} calls"
    assert isinstance(executed_cmds[0], ExecuteJob), "Expected ExecuteJob command"
    assert executed_cmds[0].job is scheduled_job, "ExecuteJob.job should be the scheduled job"


async def test_run_job_internal_bypasses_executor(hassette_with_scheduler: Hassette) -> None:
    """Internal jobs (db_id=None) run directly, bypassing CommandExecutor."""
    job_executed = asyncio.Event()

    async def target() -> None:
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    scheduler_service = hassette_with_scheduler._scheduler_service
    executor = scheduler_service._executor
    executor.execute.reset_mock()

    # Use the internal scheduler (no app_key) — job gets db_id=None
    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01)

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    # Executor should NOT have been called for internal jobs
    executor.execute.assert_not_called()


async def test_job_registration_sets_db_id(hassette_with_scheduler: Hassette) -> None:
    """Adding a job triggers register_job() and sets job.db_id.

    The scheduler's parent must have app_key set so the job gets a non-empty
    app_key and triggers DB registration (empty app_key skips registration).
    """
    db_id = 99

    scheduler = hassette_with_scheduler._scheduler
    assert scheduler is not None
    # Set app_key on the scheduler's parent so the job has a non-empty app_key
    # and triggers DB registration (without this, the guard skips registration).
    scheduler.parent.app_key = "test_app"  # pyright: ignore[reportOptionalMemberAccess]
    scheduler.parent.index = 0  # pyright: ignore[reportOptionalMemberAccess]
    try:
        scheduler_service = hassette_with_scheduler._scheduler_service
        assert scheduler_service is not None
        executor = scheduler_service._executor
        executor.register_job = AsyncMock(return_value=db_id)

        job_executed = asyncio.Event()

        async def target() -> None:
            hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

        scheduled_job = scheduler.run_in(target, delay=0.5)

        # Give the background registration task time to complete
        await asyncio.sleep(0.1)

        assert scheduled_job.db_id is not None, "job.db_id should be set after registration"
        assert scheduled_job.db_id == db_id, f"Expected db_id={db_id}, got {scheduled_job.db_id}"

        scheduled_job.cancel()
    finally:
        # Clean up: reset app_key and index so other tests using this module-scoped fixture aren't affected
        scheduler.parent.app_key = ""  # pyright: ignore[reportOptionalMemberAccess]
        scheduler.parent.index = 0  # pyright: ignore[reportOptionalMemberAccess]


async def test_jobs_execute_in_run_order(hassette_with_scheduler: Hassette) -> None:
    """run_once executes jobs according to their scheduled time."""
    execution_order: list[str] = []
    early_job_complete = asyncio.Event()
    late_job_complete = asyncio.Event()

    def make_job(label: str, signal: asyncio.Event):
        def _job() -> None:
            execution_order.append(label)
            hassette_with_scheduler.task_bucket.post_to_loop(signal.set)

        return _job

    reference = now()
    hassette_with_scheduler._scheduler.run_once(
        make_job("late", late_job_complete), start=reference.add(seconds=0.4), name="late_job"
    )
    hassette_with_scheduler._scheduler.run_once(
        make_job("early", early_job_complete), start=reference.add(seconds=0.1), name="early_job"
    )

    await asyncio.wait_for(early_job_complete.wait(), timeout=2)
    await asyncio.wait_for(late_job_complete.wait(), timeout=2)

    actual = set(execution_order[:2])
    expected = {"early", "late"}
    assert actual == expected, f"Expected {expected}, got {actual}"


def test_scheduled_job_has_app_key_and_instance_index() -> None:
    """Create a ScheduledJob with app_key and instance_index, verify fields are set."""
    job = ScheduledJob(
        owner_id="MyApp.MyApp.0",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
        app_key="my_app",
        instance_index=2,
    )

    assert job.app_key == "my_app"
    assert job.instance_index == 2
    assert job.owner_id == "MyApp.MyApp.0"


def test_scheduled_job_defaults_empty_app_key() -> None:
    """Create a ScheduledJob without app_key, verify it defaults to empty string."""
    job = ScheduledJob(
        owner_id="test",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
    )

    assert job.app_key == ""
    assert job.instance_index == 0


def test_scheduled_job_mark_registered_sets_db_id() -> None:
    """mark_registered() sets db_id on first call."""
    job = ScheduledJob(
        owner_id="test",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
    )
    assert job.db_id is None

    job.mark_registered(42)
    assert job.db_id == 42


def test_scheduled_job_mark_registered_warns_on_double_call(caplog: "pytest.LogCaptureFixture") -> None:
    """mark_registered() logs a warning and keeps the original db_id on second call."""
    import logging

    job = ScheduledJob(
        owner_id="test",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
    )
    job.mark_registered(42)

    with caplog.at_level(logging.WARNING, logger="hassette.scheduler.classes"):
        job.mark_registered(99)

    assert job.db_id == 42
    assert "already registered" in caplog.text
