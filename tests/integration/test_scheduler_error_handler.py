"""Integration tests for scheduler error handler precedence and routing via HassetteHarness."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from hassette.scheduler.error_context import SchedulerErrorContext

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.scheduler import Scheduler


@pytest.fixture
def scheduler(hassette_with_scheduler: "Hassette") -> "Scheduler":
    """Return the Scheduler resource for the running Hassette harness."""
    return hassette_with_scheduler._scheduler


async def test_app_level_error_handler_called_on_job_failure(hassette_with_scheduler: "Hassette") -> None:
    """App-level handler registered via scheduler.on_error() is called when a job raises."""
    hassette = hassette_with_scheduler
    scheduler = hassette._scheduler

    error_contexts: list[SchedulerErrorContext] = []
    handler_ran = asyncio.Event()

    async def on_error(ctx: SchedulerErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(handler_ran.set)

    async def bad_job() -> None:
        raise ValueError("job failed")

    scheduler.on_error(on_error)
    scheduler.run_in(bad_job, delay=0.01)

    await asyncio.wait_for(handler_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, ValueError)
    assert str(error_contexts[0].exception) == "job failed"


async def test_per_job_error_handler_wins(hassette_with_scheduler: "Hassette") -> None:
    """Per-registration on_error= on the job takes precedence over the app-level handler."""
    hassette = hassette_with_scheduler
    scheduler = hassette._scheduler

    app_level_calls: list[SchedulerErrorContext] = []
    per_job_calls: list[SchedulerErrorContext] = []
    per_job_ran = asyncio.Event()

    async def app_level_handler(ctx: SchedulerErrorContext) -> None:
        app_level_calls.append(ctx)

    async def per_job_handler(ctx: SchedulerErrorContext) -> None:
        per_job_calls.append(ctx)
        hassette.task_bucket.post_to_loop(per_job_ran.set)

    async def bad_job() -> None:
        raise RuntimeError("per-job failure")

    scheduler.on_error(app_level_handler)
    scheduler.run_in(bad_job, delay=0.01, on_error=per_job_handler)

    await asyncio.wait_for(per_job_ran.wait(), timeout=2.0)

    # Brief window to confirm app-level was NOT called
    await asyncio.sleep(0.05)

    assert len(per_job_calls) == 1, f"Expected 1 per-job call, got {len(per_job_calls)}"
    assert len(app_level_calls) == 0, "App-level handler should not be called when per-job handler wins"
    assert isinstance(per_job_calls[0].exception, RuntimeError)


async def test_no_handler_framework_default(hassette_with_scheduler: "Hassette") -> None:
    """When no error handler is registered, job failure does not crash the harness."""
    hassette = hassette_with_scheduler
    scheduler = hassette._scheduler

    ran = asyncio.Event()

    async def bad_job() -> None:
        hassette.task_bucket.post_to_loop(ran.set)
        raise KeyError("unhandled job error")

    scheduler.run_in(bad_job, delay=0.01)

    # Job ran (exception was raised) and harness didn't crash
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    # A brief yield lets any spawned tasks complete; harness must still be alive
    await asyncio.sleep(0.05)


async def test_error_context_contains_args_kwargs(hassette_with_scheduler: "Hassette") -> None:
    """SchedulerErrorContext carries the args and kwargs the job was scheduled with."""
    hassette = hassette_with_scheduler
    scheduler = hassette._scheduler

    error_contexts: list[SchedulerErrorContext] = []
    handler_ran = asyncio.Event()

    async def on_error(ctx: SchedulerErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(handler_ran.set)

    async def bad_job(sensor_id: str, *, count: int) -> None:  # noqa: ARG001
        raise ValueError(f"failed for {sensor_id}")

    scheduler.on_error(on_error)
    scheduler.run_in(bad_job, delay=0.01, args=("sensor.kitchen",), kwargs={"count": 3})

    await asyncio.wait_for(handler_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    ctx = error_contexts[0]
    assert ctx.args == ("sensor.kitchen",)
    assert ctx.kwargs == {"count": 3}
    assert isinstance(ctx.exception, ValueError)
