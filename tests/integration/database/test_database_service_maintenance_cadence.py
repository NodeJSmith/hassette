"""DatabaseService.serve() wakes for each maintenance task on that task's own interval."""

import asyncio
from unittest.mock import patch

import pytest

from hassette.core.database_service import CleanupAttempt, DatabaseService


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

    session_id = svc.hassette.session_id
    initial_heartbeat = await read_last_heartbeat(svc, session_id)

    real_method = getattr(svc, method_name)
    calls = 0

    async def run_and_count() -> bool:
        nonlocal calls
        calls += 1
        if calls >= 2:
            svc.shutdown_event.set()
        return await real_method()

    with patch.object(svc, method_name, side_effect=run_and_count):
        await asyncio.wait_for(svc.serve(), timeout=5.0)
    await svc._db_write_queue.join()

    assert calls == 2
    assert await read_last_heartbeat(svc, session_id) == initial_heartbeat


async def test_reloaded_shorter_retention_interval_applies_at_next_wake(initialized_service: DatabaseService) -> None:
    """A retention interval lowered after serve() starts takes effect at the loop's next wake.

    A config reload can lower an interval at runtime, so deadlines must follow the current config
    rather than the interval in effect when the previous attempt ran.
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


async def test_shutdown_requested_with_overdue_deadline_skips_maintenance(initialized_service: DatabaseService) -> None:
    """A shutdown already requested exits serve() even when a maintenance deadline is overdue.

    An overdue deadline clamps the wait to zero, and ``asyncio.wait_for(event.wait(), timeout=0)``
    raises ``TimeoutError`` even when the event is already set, so the loop must check the event
    itself rather than rely on the wait to report it.
    """
    svc = initialized_service
    config = svc.hassette.config.database
    config.heartbeat_interval_seconds = 60
    config.retention_interval_seconds = 0
    config.size_failsafe_interval_seconds = 3600
    svc.shutdown_event.set()

    with patch.object(svc, "run_retention_cleanup", return_value=True) as run_retention:
        await asyncio.wait_for(svc.serve(), timeout=2.0)

    run_retention.assert_not_called()


@pytest.mark.parametrize(("enqueued", "expected"), [(True, 3600.0), (False, 300.0)])
def test_cleanup_attempt_retries_dropped_enqueue_at_retry_interval(enqueued: bool, expected: float) -> None:
    """A dropped cleanup enqueue retries after the shorter retry interval instead of a full interval."""
    attempt = CleanupAttempt(attempted_at=0.0, enqueued=enqueued)

    assert attempt.next_due(3600, retry_interval=300) == expected


async def read_last_heartbeat(svc: DatabaseService, session_id: int | None) -> float:
    cursor = await svc.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    return row[0]
