"""System tests for the scheduler — real job execution through a running Hassette instance."""

import asyncio

import pytest

import hassette.utils.date_utils as date_utils
from hassette.scheduler import EntityTime, ScheduleStatus
from hassette.testing import wait_for

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]


async def test_run_in_fires_after_delay(ha_container: str, tmp_path) -> None:
    """A run_in job fires after its configured delay."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        await scheduler.run_in(_callback, 1, name="run_in_fires_after_delay_run_in")
        await wait_for(lambda: len(fired) >= 1, timeout=5.0, desc="run_in callback to fire")


async def test_run_every_fires_multiple_times(ha_container: str, tmp_path) -> None:
    """A run_every job fires at least twice within the timeout window."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        await scheduler.run_every(_callback, seconds=1, name="run_every_fires_multiple_times_run_every")
        await wait_for(lambda: len(fired) >= 2, timeout=5.0, desc="run_every callback to fire at least twice")


async def test_run_once_at_time(ha_container: str, tmp_path) -> None:
    """A run_once job fires at the specified ZonedDateTime target."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        # Schedule ~2 seconds in the future using an absolute ZonedDateTime so
        # there is no ambiguity from HH:MM rounding to the nearest minute.
        target = date_utils.now().add(seconds=2).round("second")
        await scheduler.run_once(_callback, at=target, name="run_once_at_time_run_once")
        await wait_for(lambda: len(fired) >= 1, timeout=8.0, desc="run_once callback to fire at target time")


async def test_job_removal(ha_container: str, tmp_path) -> None:
    """A removed job does not fire after removal."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        job = await scheduler.run_in(_callback, 2, name="job_removal_run_in")
        job.remove()

        # Wait past the job's scheduled time to confirm it never fired.
        await asyncio.sleep(3)
        assert len(fired) == 0


async def test_group_removal(ha_container: str, tmp_path) -> None:
    """All jobs in a group are removed before any fires."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        await scheduler.run_in(_callback, 2, group="test_group", name="group_removal_run_in")
        await scheduler.run_in(_callback, 3, group="test_group", name="group_removal_run_in_2")
        await scheduler.run_in(_callback, 4, group="test_group", name="group_removal_run_in_3")

        scheduler.remove_group("test_group")

        # Wait past the last job's scheduled time to confirm none fired.
        await asyncio.sleep(5)
        assert len(fired) == 0


async def test_job_execution_persisted(ha_container: str, tmp_path) -> None:
    """A completed job execution is persisted to the unified executions table (kind='job')."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        session_id = hassette.session_id
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        await scheduler.run_in(_callback, 1, name="job_execution_persisted_run_in")

        # Wait for the callback to fire first.
        await wait_for(lambda: len(fired) >= 1, timeout=5.0, desc="run_in callback to fire before DB check")

        async def _row_exists() -> bool:
            async with hassette.database_service.read_db.execute(
                "SELECT COUNT(*) FROM executions WHERE session_id = ? AND kind = 'job'",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None and row[0] > 0

        await wait_for(
            _row_exists, timeout=10.0, interval=0.1, desc=f"executions(kind=job) row for session_id={session_id}"
        )


async def test_run_cron_fires(ha_container: str, tmp_path) -> None:
    """A cron job with a per-second expression fires within a few seconds."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        # 6-field cron: every 2 seconds (minute hour dom month dow second)
        await scheduler.run_cron(_callback, "* * * * * */2", name="run_cron_fires_run_cron")
        await wait_for(lambda: len(fired) >= 1, timeout=10.0, desc="cron callback to fire")


async def test_owner_cleanup_removes_all_job_statuses(ha_container: str, tmp_path) -> None:
    """Scheduler.remove_all_jobs() (the owner-cleanup path used by on_shutdown() and app
    reload) removes every live registration regardless of schedule status — scheduled,
    completed, waiting, and manual — not just heap-resident scheduled jobs. Confirms via
    the persisted ``removed_at`` column, since waiting/completed/manual jobs never touch
    the heap and would be invisible to a heap-only removal scan.
    """
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]

        async def _noop() -> None:
            pass

        scheduled_job = await scheduler.run_every(_noop, seconds=3600, name="owner_cleanup_scheduled")
        assert scheduled_job.schedule_status is ScheduleStatus.SCHEDULED

        completed_job = await scheduler.run_in(_noop, 1, name="owner_cleanup_completed")
        await wait_for(
            lambda: completed_job.schedule_status is ScheduleStatus.COMPLETED,
            timeout=5.0,
            desc="one-shot job to complete",
        )

        waiting_job = await scheduler.schedule(
            _noop, EntityTime("sensor.owner_cleanup_nonexistent"), name="owner_cleanup_waiting"
        )
        assert waiting_job.schedule_status is ScheduleStatus.WAITING

        manual_job = await scheduler.register(_noop, name="owner_cleanup_manual")
        assert manual_job.schedule_status is ScheduleStatus.MANUAL

        jobs = (scheduled_job, completed_job, waiting_job, manual_job)
        db_ids = [job.db_id for job in jobs]
        assert all(db_id is not None for db_id in db_ids), "every job must have persisted before cleanup"

        await scheduler.remove_all_jobs()

        for job in jobs:
            assert job._dequeued is True  # pyright: ignore[reportPrivateUsage]

        async def _all_removed() -> bool:
            placeholders = ",".join("?" for _ in db_ids)
            async with hassette.database_service.read_db.execute(
                f"SELECT COUNT(*) FROM scheduled_jobs WHERE id IN ({placeholders}) AND removed_at IS NULL",
                db_ids,
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None and row[0] == 0

        await wait_for(
            _all_removed,
            timeout=5.0,
            interval=0.1,
            desc="all four jobs (scheduled/completed/waiting/manual) to have removed_at set",
        )


async def test_jitter_applied(ha_container: str, tmp_path) -> None:
    """A job with jitter fires — confirming jitter doesn't prevent execution."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        await scheduler.run_in(_callback, 1, jitter=0.5, name="jitter_applied_run_in")
        await wait_for(lambda: len(fired) >= 1, timeout=5.0, desc="jittered run_in callback to fire")
