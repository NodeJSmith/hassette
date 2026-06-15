"""Integration tests for T01: scheduler mode parameter, resolution, and guard.

Tests verify:
- schedule() resolves None -> single for app tier, parallel for framework tier
- explicit ExecutionMode passthrough
- string coercion to ExecutionMode
- invalid string raises ValueError naming valid values
- mode= accepted on run_in / run_once without error (no overlap effect — one-shot fires once)
- convenience methods forward mode= to schedule()

These tests use HassetteHarness (framework-tier scheduler) via the hassette_with_scheduler fixture.
App-tier tests use AppTestHarness.
"""

import asyncio

import pytest
from whenever import ZonedDateTime

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.execution_mode import ExecutionModeGuard
from hassette.scheduler.triggers import Every
from hassette.test_utils.app_harness import AppTestHarness
from hassette.types.enums import ExecutionMode

# ---------------------------------------------------------------------------
# App for AC#2: one-shot with mode= fires exactly once
# ---------------------------------------------------------------------------


class _OneShotModeConfig(AppConfig):
    """Minimal config for one-shot mode acceptance tests."""


class _RunInModeApp(App[_OneShotModeConfig]):
    """Schedules a run_in job with mode= set; records invocation count."""

    fired_count: int

    async def on_initialize(self) -> None:
        self.fired_count = 0
        # mode= accepted on one-shots — no overlap effect, fires once
        await self.scheduler.run_in(self.task, delay=10, name="oneshot_mode_job", mode="parallel")

    async def task(self) -> None:
        self.fired_count += 1


class _RunOnceModeApp(App[_OneShotModeConfig]):
    """Schedules a run_once job with mode= set; records invocation count."""

    fired_count: int

    async def on_initialize(self) -> None:
        self.fired_count = 0
        await self.scheduler.run_once(
            self.task,
            at=ZonedDateTime.from_system_tz(2030, 6, 15, 7, 0, 0),
            name="runonce_mode_job",
            mode=ExecutionMode.QUEUED,
        )

    async def task(self) -> None:
        self.fired_count += 1


# ---------------------------------------------------------------------------
# AC#2: one-shot with mode= fires exactly once
# ---------------------------------------------------------------------------


async def test_run_in_with_mode_fires_exactly_once() -> None:
    """AC#2: run_in with mode= set still fires exactly once (mode has no overlap effect)."""
    async with AppTestHarness(_RunInModeApp, config={}) as harness:
        scheduler = harness.app.scheduler

        jobs = scheduler.list_jobs()
        assert any(j.name == "oneshot_mode_job" for j in jobs), "oneshot_mode_job should be registered"

        job = next(j for j in jobs if j.name == "oneshot_mode_job")
        assert job.mode is ExecutionMode.PARALLEL, f"Expected PARALLEL, got {job.mode}"

        # Freeze time past the job's due time
        harness.freeze_time(job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1, f"Expected exactly 1 job dispatched, got {count}"
        assert harness.app.fired_count == 1, f"Expected fired_count=1, got {harness.app.fired_count}"

        # Job is exhausted after firing — should be removed from the scheduler
        remaining = scheduler.list_jobs()
        assert not any(j.name == "oneshot_mode_job" for j in remaining), (
            "One-shot job should be removed after exhaustion"
        )


async def test_run_once_with_mode_fires_exactly_once() -> None:
    """AC#2: run_once with mode= set still fires exactly once (mode has no overlap effect)."""
    async with AppTestHarness(_RunOnceModeApp, config={}) as harness:
        scheduler = harness.app.scheduler

        jobs = scheduler.list_jobs()
        assert any(j.name == "runonce_mode_job" for j in jobs), "runonce_mode_job should be registered"

        job = next(j for j in jobs if j.name == "runonce_mode_job")
        assert job.mode is ExecutionMode.QUEUED, f"Expected QUEUED, got {job.mode}"

        harness.freeze_time(job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1, f"Expected exactly 1 job dispatched, got {count}"
        assert harness.app.fired_count == 1, f"Expected fired_count=1, got {harness.app.fired_count}"

        remaining = scheduler.list_jobs()
        assert not any(j.name == "runonce_mode_job" for j in remaining), (
            "One-shot job should be removed after exhaustion"
        )


# ---------------------------------------------------------------------------
# Integration tests via hassette_with_scheduler (framework-tier scheduler)
# ---------------------------------------------------------------------------


class TestSchedulerModeViaHarness:
    """Test the full schedule() path including mode resolution and job creation."""

    async def test_framework_tier_omitted_mode_resolves_to_parallel(self, hassette_with_scheduler) -> None:
        """Framework-tier schedule with mode=None resolves to ExecutionMode.PARALLEL."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.schedule(noop, Every(seconds=3600))
        assert job.mode is ExecutionMode.PARALLEL
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_explicit_mode_enum_passes_through(self, hassette_with_scheduler) -> None:
        """An explicit ExecutionMode enum is stored unchanged."""

        async def noop() -> None:
            pass

        for mode in ExecutionMode:
            job = await hassette_with_scheduler.scheduler.schedule(
                noop, Every(seconds=3600), mode=mode, name=f"passthrough_{mode.value}"
            )
            assert job.mode is mode
            hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_string_coercion_all_modes(self, hassette_with_scheduler) -> None:
        """Each valid mode string is coerced to the corresponding ExecutionMode member."""

        async def noop() -> None:
            pass

        cases = [
            ("single", ExecutionMode.SINGLE),
            ("parallel", ExecutionMode.PARALLEL),
            ("restart", ExecutionMode.RESTART),
            ("queued", ExecutionMode.QUEUED),
        ]
        for string_val, expected in cases:
            job = await hassette_with_scheduler.scheduler.schedule(
                noop, Every(seconds=3600), mode=string_val, name=f"coerce_{string_val}"
            )
            assert job.mode is expected, f"mode={string_val!r}: expected {expected}, got {job.mode}"
            hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_invalid_string_raises_value_error(self, hassette_with_scheduler) -> None:
        """An invalid mode string raises ValueError naming all valid values."""

        async def noop() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid execution mode") as exc_info:
            await hassette_with_scheduler.scheduler.schedule(noop, Every(seconds=60), mode="bogus")
        msg = str(exc_info.value)
        for valid in ("'single'", "'restart'", "'queued'", "'parallel'"):
            assert valid in msg

    async def test_invalid_string_raises_before_job_registered(self, hassette_with_scheduler) -> None:
        """ValueError is raised before any job is registered."""

        async def noop() -> None:
            pass

        count_before = len(hassette_with_scheduler.scheduler.list_jobs())
        with pytest.raises(ValueError, match="Invalid execution mode"):
            await hassette_with_scheduler.scheduler.schedule(noop, Every(seconds=60), mode="not_a_mode")
        assert len(hassette_with_scheduler.scheduler.list_jobs()) == count_before

    async def test_guard_present_on_scheduled_job(self, hassette_with_scheduler) -> None:
        """The scheduled job has an ExecutionModeGuard created from its mode."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.schedule(
            noop, Every(seconds=3600), mode=ExecutionMode.SINGLE, name="guard_check"
        )
        assert isinstance(job.guard, ExecutionModeGuard)
        hassette_with_scheduler.scheduler.cancel_job(job)


# ---------------------------------------------------------------------------
# One-shot acceptance tests — run_in / run_once accept mode= without error
# ---------------------------------------------------------------------------


class TestOneShotModeAcceptance:
    async def test_run_in_accepts_mode_no_error(self, hassette_with_scheduler) -> None:
        """run_in accepts mode= keyword argument without raising."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_in(noop, delay=3600, mode=ExecutionMode.QUEUED)
        assert job.mode is ExecutionMode.QUEUED
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_once_accepts_mode_no_error(self, hassette_with_scheduler) -> None:
        """run_once accepts mode= keyword argument without raising."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_once(noop, at="23:59", mode=ExecutionMode.RESTART)
        assert job.mode is ExecutionMode.RESTART
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_in_string_mode_coerced(self, hassette_with_scheduler) -> None:
        """run_in accepts a string mode and coerces it correctly."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_in(noop, delay=3600, mode="parallel")
        assert job.mode is ExecutionMode.PARALLEL
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_in_invalid_string_raises(self, hassette_with_scheduler) -> None:
        """run_in with an invalid mode string raises ValueError (delegates to schedule())."""

        async def noop() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid execution mode"):
            await hassette_with_scheduler.scheduler.run_in(noop, delay=3600, mode="bad_mode")

    async def test_run_in_mode_stored_on_job(self, hassette_with_scheduler) -> None:
        """A run_in job with mode= stores the resolved mode and a guard on the job object."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_in(
            noop, delay=3600, mode=ExecutionMode.QUEUED, name="oneshot_mode_stored"
        )
        assert job.mode is ExecutionMode.QUEUED
        assert isinstance(job.guard, ExecutionModeGuard)
        hassette_with_scheduler.scheduler.cancel_job(job)


# ---------------------------------------------------------------------------
# Convenience method forwarding
# ---------------------------------------------------------------------------


class TestConvenienceMethodModeForwarding:
    async def test_run_every_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_every forwards mode= and the resolved mode appears on the job."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_every(
            noop, seconds=60, mode=ExecutionMode.RESTART, name="every_restart"
        )
        assert job.mode is ExecutionMode.RESTART
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_daily_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_daily forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_daily(noop, at="03:00", mode="queued", name="daily_queued")
        assert job.mode is ExecutionMode.QUEUED
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_cron_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_cron forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_cron(
            noop, "0 * * * *", mode=ExecutionMode.SINGLE, name="cron_single"
        )
        assert job.mode is ExecutionMode.SINGLE
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_minutely_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_minutely forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_minutely(
            noop, minutes=5, mode="restart", name="minutely_restart"
        )
        assert job.mode is ExecutionMode.RESTART
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_hourly_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_hourly forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_hourly(
            noop, hours=2, mode=ExecutionMode.QUEUED, name="hourly_queued"
        )
        assert job.mode is ExecutionMode.QUEUED
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_omitted_mode_default_is_parallel_for_framework(self, hassette_with_scheduler) -> None:
        """Omitting mode= on the framework-tier harness scheduler gives PARALLEL."""

        async def noop() -> None:
            pass

        jobs = await asyncio.gather(
            hassette_with_scheduler.scheduler.run_every(noop, seconds=60, name="fw_j1"),
            hassette_with_scheduler.scheduler.run_daily(noop, at="04:00", name="fw_j2"),
            hassette_with_scheduler.scheduler.run_cron(noop, "0 0 * * *", name="fw_j3"),
            hassette_with_scheduler.scheduler.run_minutely(noop, name="fw_j4"),
            hassette_with_scheduler.scheduler.run_hourly(noop, name="fw_j5"),
        )
        for job in jobs:
            assert job.mode is ExecutionMode.PARALLEL, (
                f"{job.name} expected PARALLEL (framework default), got {job.mode}"
            )
            hassette_with_scheduler.scheduler.cancel_job(job)
