"""Integration tests for AppTestHarness time control (WP04).

Tests freeze_time, advance_time, trigger_due_jobs, and the _TestClock internals.
"""

import pytest
from whenever import Instant, ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
from hassette.test_utils.app_harness import AppTestHarness

# ---------------------------------------------------------------------------
# Test app with both state change handlers and scheduler jobs
# ---------------------------------------------------------------------------


class SimConfig(AppConfig):
    """Minimal AppConfig for simulation tests."""


class SimTestApp(App[SimConfig]):
    """Test app with handler and scheduler job."""

    handler_call_count: int
    service_calls: list[tuple[str, str, dict]]

    async def on_initialize(self) -> None:
        self.handler_call_count = 0
        self.service_calls = []
        self.bus.on_state_change("sensor.temp", handler=self._on_temp)
        self.scheduler.run_daily(self._daily_task, at="07:00", name="daily")

    async def _on_temp(self, event: RawStateChangeEvent) -> None:
        await self.api.turn_on("light.alert")
        self.handler_call_count += 1

    async def _daily_task(self) -> None:
        await self.api.call_service("cover", "open_cover", entity_id="cover.blinds")
        self.service_calls.append(("cover", "open_cover", {"entity_id": "cover.blinds"}))


# ---------------------------------------------------------------------------
# freeze_time / advance_time / trigger_due_jobs tests
# ---------------------------------------------------------------------------


async def test_freeze_time_patches_now():
    """freeze_time patches hassette's now() to return the frozen time."""
    frozen = Instant.from_utc(2026, 4, 7, 6, 0)
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(frozen)
        result = date_utils.now()
        expected = frozen.to_system_tz()
        assert result == expected, f"Expected {expected}, got {result}"


async def test_freeze_time_idempotent():
    """freeze_time can be called multiple times; second call replaces the first."""
    frozen1 = Instant.from_utc(2026, 4, 7, 6, 0)
    frozen2 = Instant.from_utc(2026, 4, 7, 8, 0)
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(frozen1)
        harness.freeze_time(frozen2)
        result = date_utils.now()
        expected = frozen2.to_system_tz()
        assert result == expected


async def test_advance_time_without_freeze_raises():
    """advance_time raises RuntimeError if freeze_time has not been called."""
    async with AppTestHarness(SimTestApp, config={}) as harness:
        with pytest.raises(RuntimeError, match="freeze_time"):
            harness.advance_time(seconds=60)


async def test_advance_time_moves_clock():
    """After freeze_time + advance_time, now() returns the advanced time."""
    frozen = Instant.from_utc(2026, 4, 7, 6, 0)
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(frozen)
        harness.advance_time(seconds=60)
        result = date_utils.now()
        expected = frozen.to_system_tz().add(seconds=60)
        assert result == expected


async def test_advance_time_hours_and_minutes():
    """advance_time accepts hours and minutes parameters."""
    frozen = Instant.from_utc(2026, 4, 7, 6, 0)
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(frozen)
        harness.advance_time(hours=1, minutes=30)
        result = date_utils.now()
        expected = frozen.to_system_tz().add(hours=1, minutes=30)
        assert result == expected


async def test_trigger_due_jobs_fires_scheduled():
    """Freeze at 6:00, advance to 7:00, trigger — daily job fires."""
    # The app registers run_daily at 7:00 during on_initialize.
    async with AppTestHarness(SimTestApp, config={}) as harness:
        # Freeze before app init so run_daily uses frozen time when scheduling
        # Actually app is already initialized; we need to ensure job fires.
        # The job was scheduled at "today at 7:00" using real now() during on_initialize.
        # We need to freeze to a time after that scheduled run time.
        # Let's get the job's next_run time, then freeze past it.
        jobs = await harness._harness.hassette._scheduler_service._job_queue.get_all()
        assert len(jobs) > 0, "No jobs registered"
        daily_job = next((j for j in jobs if j.name == "daily"), None)
        assert daily_job is not None, "daily job not found"

        # Freeze time to 1 second after the job's scheduled run time
        job_run_at = daily_job.next_run
        # Advance by setting frozen time to just after job's run time
        # Use the job's ZonedDateTime directly as a ZonedDateTime
        harness.freeze_time(job_run_at.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1
        # call_service records domain+service as args, entity_id as kwargs
        harness.api_recorder.assert_called("call_service", entity_id="cover.blinds")


async def test_trigger_due_jobs_returns_count():
    """trigger_due_jobs returns the number of jobs fired."""
    async with AppTestHarness(SimTestApp, config={}) as harness:
        jobs = await harness._harness.hassette._scheduler_service._job_queue.get_all()
        daily_job = next((j for j in jobs if j.name == "daily"), None)
        assert daily_job is not None

        harness.freeze_time(daily_job.next_run.add(seconds=1))
        count = await harness.trigger_due_jobs()
        assert count == 1


async def test_trigger_due_jobs_snapshot_prevents_infinite_loop():
    """trigger_due_jobs fires a repeating job exactly once per call, not infinitely."""
    async with AppTestHarness(SimTestApp, config={}) as harness:
        jobs = await harness._harness.hassette._scheduler_service._job_queue.get_all()
        daily_job = next((j for j in jobs if j.name == "daily"), None)
        assert daily_job is not None

        # Freeze time far in the future so the rescheduled job would also be due
        harness.freeze_time(daily_job.next_run.add(hours=48))

        count = await harness.trigger_due_jobs()
        # Should fire exactly 1 job (snapshot-based), not loop infinitely
        assert count == 1


async def test_trigger_due_jobs_no_due_jobs_returns_zero():
    """trigger_due_jobs returns 0 when no jobs are due at the frozen time."""
    frozen_past = Instant.from_utc(2000, 1, 1, 0, 0)  # very far in the past
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(frozen_past)
        count = await harness.trigger_due_jobs()
        assert count == 0


async def test_freeze_time_cleanup_on_exit():
    """After exiting AppTestHarness, now() returns real time (not frozen)."""
    frozen = Instant.from_utc(2000, 1, 1, 0, 0)
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(frozen)
        assert date_utils.now() == frozen.to_system_tz()

    # After exit, now() returns real time (not the frozen 2000-01-01)
    real_now = date_utils.now()
    frozen_time = frozen.to_system_tz()
    assert real_now != frozen_time, f"now() is still returning frozen time after harness exit: {real_now}"


async def test_freeze_time_accepts_zoned_datetime():
    """freeze_time accepts a ZonedDateTime directly (not just Instant)."""
    zdt = ZonedDateTime.from_system_tz(2026, 4, 7, 6, 0)
    async with AppTestHarness(SimTestApp, config={}) as harness:
        harness.freeze_time(zdt)
        result = date_utils.now()
        assert result == zdt


class SimTestApp2(App[SimConfig]):
    """Second test app class — avoids per-class lock contention with SimTestApp."""

    async def on_initialize(self) -> None:
        pass


async def test_freeze_time_concurrent_lock_raises():
    """A second harness calling freeze_time while the first holds the lock raises RuntimeError."""
    from hassette.test_utils.app_harness import _FREEZE_TIME_LOCK

    frozen = Instant.from_utc(2026, 4, 7, 6, 0)

    async with AppTestHarness(SimTestApp, config={}) as harness1:
        harness1.freeze_time(frozen)
        # Lock should be held by harness1
        assert _FREEZE_TIME_LOCK.locked()

        # Use a different App class to avoid per-class asyncio.Lock deadlock
        async with AppTestHarness(SimTestApp2, config={}) as harness2:
            with pytest.raises(RuntimeError, match="freeze_time is already held"):
                harness2.freeze_time(frozen)

    # After both harnesses exit, lock should be released
    assert not _FREEZE_TIME_LOCK.locked()
