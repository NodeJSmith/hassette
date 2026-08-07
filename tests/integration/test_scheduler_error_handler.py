"""Integration tests for scheduler error handler precedence and routing via HassetteHarness."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.test_utils.helpers import settle

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.scheduler import Scheduler
    from hassette.test_utils.harness import HassetteHarness

ERROR_TIMEOUT = 2.0
"""Seconds to wait for an error handler that fires without a duration timer in front of it."""


class _SchedulerErrorCollector:
    """Records the `SchedulerErrorContext` values an `on_error` handler receives."""

    def __init__(self, hassette: "Hassette") -> None:
        self.hassette = hassette
        self.contexts: list[SchedulerErrorContext] = []
        self.ran = asyncio.Event()

    async def record(self, ctx: SchedulerErrorContext) -> None:
        self.contexts.append(ctx)
        self.hassette.task_bucket.post_to_loop(self.ran.set)

    async def wait(self, timeout: float = ERROR_TIMEOUT) -> None:
        """Block until the first error is recorded."""
        await asyncio.wait_for(self.ran.wait(), timeout=timeout)

    def single(self, exc_type: type[Exception]) -> SchedulerErrorContext:
        """Assert exactly one error of `exc_type` was recorded, and return its context."""
        assert len(self.contexts) == 1
        assert isinstance(self.contexts[0].exception, exc_type)
        return self.contexts[0]


@pytest.fixture
def scheduler(hassette_with_scheduler: "HassetteHarness") -> "Scheduler":
    """Return the Scheduler resource for the running Hassette harness."""
    return hassette_with_scheduler.scheduler


async def test_app_level_error_handler_called_on_job_failure(hassette_with_scheduler: "HassetteHarness") -> None:
    """App-level handler registered via scheduler.on_error() is called when a job raises."""
    hassette = hassette_with_scheduler
    scheduler = hassette.scheduler

    errors = _SchedulerErrorCollector(hassette)

    async def bad_job() -> None:
        raise ValueError("job failed")

    scheduler.on_error(errors.record)
    await scheduler.run_in(bad_job, delay=0.01, name="app_level_error_handler_called_on_job_fa_run_in")

    await errors.wait()
    await settle()

    ctx = errors.single(ValueError)
    assert str(ctx.exception) == "job failed"


async def test_per_job_error_handler_wins(hassette_with_scheduler: "HassetteHarness") -> None:
    """Per-registration on_error= on the job takes precedence over the app-level handler."""
    hassette = hassette_with_scheduler
    scheduler = hassette.scheduler

    app_level = _SchedulerErrorCollector(hassette)
    per_job = _SchedulerErrorCollector(hassette)

    async def bad_job() -> None:
        raise RuntimeError("per-job failure")

    scheduler.on_error(app_level.record)
    await scheduler.run_in(bad_job, delay=0.01, on_error=per_job.record, name="per_job_error_handler_wins_run_in")

    await per_job.wait()
    await settle()

    per_job.single(RuntimeError)
    assert not app_level.contexts, "App-level handler should not be called when per-job handler wins"


async def test_no_handler_framework_default(hassette_with_scheduler: "HassetteHarness") -> None:
    """When no error handler is registered, job failure does not crash the harness."""
    hassette = hassette_with_scheduler
    scheduler = hassette.scheduler

    ran = asyncio.Event()

    async def bad_job() -> None:
        hassette.task_bucket.post_to_loop(ran.set)
        raise KeyError("unhandled job error")

    await scheduler.run_in(bad_job, delay=0.01, name="no_handler_framework_default_run_in")

    # Job ran (exception was raised) and harness didn't crash
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    await settle()


async def test_error_context_contains_args_kwargs(hassette_with_scheduler: "HassetteHarness") -> None:
    """SchedulerErrorContext carries the args and kwargs the job was scheduled with."""
    hassette = hassette_with_scheduler
    scheduler = hassette.scheduler

    errors = _SchedulerErrorCollector(hassette)

    async def bad_job(sensor_id: str, *, count: int) -> None:  # noqa: ARG001
        raise ValueError(f"failed for {sensor_id}")

    scheduler.on_error(errors.record)
    await scheduler.run_in(
        bad_job,
        delay=0.01,
        args=("sensor.kitchen",),
        kwargs={"count": 3},
        name="error_context_contains_args_kwargs_run_in",
    )

    await errors.wait()
    await settle()

    ctx = errors.single(ValueError)
    assert ctx.args == ("sensor.kitchen",)
    assert ctx.kwargs == {"count": 3}
