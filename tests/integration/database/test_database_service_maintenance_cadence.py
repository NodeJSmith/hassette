"""DatabaseService.serve() wakes for each maintenance task on that task's own interval."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from hassette.core.database_service import DatabaseService


@pytest.mark.parametrize(
    ("method_name", "interval_field"),
    [
        ("run_retention_cleanup", "retention_interval_seconds"),
        ("run_size_failsafe", "size_failsafe_interval_seconds"),
    ],
)
async def test_maintenance_interval_shorter_than_heartbeat_is_honored(
    initialized_service: DatabaseService, method_name: str, interval_field: str
) -> None:
    """A maintenance interval below the heartbeat interval runs on its own cadence.

    Regression: serve() always slept the full heartbeat interval, so a shorter retention or
    size-failsafe interval only ran at the heartbeat cadence. The heartbeat here is far longer
    than the test's timeout, so two maintenance runs can only happen if the loop wakes for the
    maintenance deadline -- and the heartbeat, not yet due, must not run on those wakes.
    """
    svc = initialized_service
    config = svc.hassette.config.database
    config.heartbeat_interval_seconds = 60
    config.retention_interval_seconds = 3600
    config.size_failsafe_interval_seconds = 3600
    setattr(config, interval_field, 0.05)

    calls = 0

    async def spy() -> bool:
        nonlocal calls
        calls += 1
        if calls >= 2:
            svc.shutdown_event.set()
        return True

    heartbeat = AsyncMock()
    with patch.object(svc, method_name, spy), patch.object(svc, "update_heartbeat", heartbeat):
        await asyncio.wait_for(svc.serve(), timeout=5.0)

    assert calls == 2
    heartbeat.assert_not_called()


async def test_reloaded_shorter_retention_interval_applies_at_next_wake(initialized_service: DatabaseService) -> None:
    """A retention interval lowered after serve() starts takes effect at the loop's next wake.

    Regression: serve() fixed each deadline from the interval in effect when it was scheduled, so
    lowering the interval at runtime (a config reload) left cleanup waiting out the old interval.
    """
    svc = initialized_service
    config = svc.hassette.config.database
    config.heartbeat_interval_seconds = 0.1
    config.retention_interval_seconds = 3600
    config.size_failsafe_interval_seconds = 3600

    real_run_retention_cleanup = svc.run_retention_cleanup

    async def run_and_stop() -> bool:
        svc.shutdown_event.set()
        return await real_run_retention_cleanup()

    async def lower_interval() -> None:
        await asyncio.sleep(0.05)
        config.retention_interval_seconds = 0.05

    lower_task = asyncio.create_task(lower_interval())
    with patch.object(svc, "run_retention_cleanup", side_effect=run_and_stop) as run_retention:
        await asyncio.wait_for(svc.serve(), timeout=2.0)
    await lower_task

    run_retention.assert_called_once()
