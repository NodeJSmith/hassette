"""System tests for the scheduler — real job execution through a running Hassette instance."""

import asyncio

import pytest

import hassette.utils.date_utils as date_utils
from hassette.test_utils import wait_for

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]


async def test_run_in_fires_after_delay(ha_container: str, tmp_path):
    """A run_in job fires after its configured delay."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        scheduler.run_in(_callback, 1)
        await wait_for(lambda: len(fired) >= 1, timeout=5.0, desc="run_in callback to fire")


async def test_run_every_fires_multiple_times(ha_container: str, tmp_path):
    """A run_every job fires at least twice within the timeout window."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        scheduler.run_every(_callback, seconds=1)
        await wait_for(lambda: len(fired) >= 2, timeout=5.0, desc="run_every callback to fire at least twice")


async def test_run_once_at_time(ha_container: str, tmp_path):
    """A run_once job fires at the specified ZonedDateTime target."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        # Schedule ~2 seconds in the future using an absolute ZonedDateTime so
        # there is no ambiguity from HH:MM rounding to the nearest minute.
        target = date_utils.now().add(seconds=2).round(unit="second")
        scheduler.run_once(_callback, at=target)
        await wait_for(lambda: len(fired) >= 1, timeout=8.0, desc="run_once callback to fire at target time")


async def test_job_cancellation(ha_container: str, tmp_path):
    """A cancelled job does not fire after cancellation."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        job = scheduler.run_in(_callback, 2)
        job.cancel()

        # Wait past the job's scheduled time to confirm it never fired.
        await asyncio.sleep(3)
        assert len(fired) == 0


async def test_group_cancellation(ha_container: str, tmp_path):
    """All jobs in a group are cancelled before any fires."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        scheduler.run_in(_callback, 2, group="test_group")
        scheduler.run_in(_callback, 3, group="test_group")
        scheduler.run_in(_callback, 4, group="test_group")

        scheduler.cancel_group("test_group")

        # Wait past the last job's scheduled time to confirm none fired.
        await asyncio.sleep(5)
        assert len(fired) == 0


async def test_job_execution_persisted(ha_container: str, tmp_path):
    """A completed job execution is persisted to the job_executions table."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        scheduler = hassette._scheduler  # pyright: ignore[reportPrivateUsage]
        session_id = hassette.session_id
        fired: list[int] = []

        async def _callback() -> None:
            fired.append(1)

        scheduler.run_in(_callback, 1)

        # Wait for the callback to fire first.
        await wait_for(lambda: len(fired) >= 1, timeout=5.0, desc="run_in callback to fire before DB check")

        # The telemetry write pipeline is async and batched; poll the DB directly
        # until a row with the correct session_id appears. wait_for only accepts a
        # synchronous predicate, so we use an explicit poll loop here.
        deadline = asyncio.get_running_loop().time() + 10.0
        row_found = False
        while asyncio.get_running_loop().time() < deadline:
            async with hassette.database_service.read_db.execute(
                "SELECT COUNT(*) FROM job_executions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is not None and row[0] > 0:
                    row_found = True
                    break
            await asyncio.sleep(0.1)

        assert row_found, f"No job_executions row found for session_id={session_id} within 10s"
