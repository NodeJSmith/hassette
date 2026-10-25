"""Unit tests for how write progress gates heartbeat strikes in ``DatabaseService``.

A failed heartbeat attempt counts toward ``max_consecutive_heartbeat_failures`` only when
``_write_progress_count`` has not moved since the previous attempt, so a worker busy with a long
maintenance pass is not restarted while a stuck or failing one still is.
"""

import asyncio
import sqlite3
from unittest.mock import patch

import pytest

from hassette.core.database_service import DatabaseService
from tests.unit.core._fixtures_database_service import initialized_service_with_worker, service

__all__ = ["initialized_service_with_worker", "service"]  # re-exposed as fixtures

TEST_HEARTBEAT_TIMEOUT_SECONDS = 0.05
"""Patched heartbeat write timeout: short enough that several attempts expire quickly."""

PROGRESSING_PASS_HEARTBEAT_TIMEOUT_SECONDS = 1.0
"""Patched heartbeat write timeout for the progressing-pass test.

Each timed-out attempt there must see a committed batch, so this keeps a full second of margin over
``BATCH_COMMIT_INTERVAL_SECONDS`` against CI scheduling noise.
"""

BATCH_COMMIT_INTERVAL_SECONDS = 0.01
"""Delay between simulated retention-batch commits in the progressing-pass test."""

PROGRESSING_PASS_DEADLINE_SECONDS = 15.0
"""Outer bound on the progressing-pass test: three full timeouts plus generous headroom."""

TEST_HEARTBEAT_INTERVAL_SECONDS = 0.01
"""Sub-second heartbeat interval so serve() makes attempts back to back."""

TIMEOUTS_OUTLASTED = 3
"""Heartbeat attempts that must time out during the maintenance pass; equals the default strike limit."""


async def failing_execute(*_args: object, **_kwargs: object) -> None:
    """Stand-in for ``aiosqlite.Connection.execute`` on a database whose every write fails.

    A plain coroutine rather than ``AsyncMock(side_effect=...)``: the logged traceback then skips
    ``unittest.mock``'s frames, which a console handler left installed by another test in the same
    worker can take seconds to syntax-highlight.
    """
    raise sqlite3.OperationalError("disk I/O error")


async def test_batched_retention_pass_outlasting_three_heartbeat_timeouts_does_not_restart(
    initialized_service_with_worker: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pass that holds the write worker through three heartbeat timeouts but keeps committing
    batches is busy, not stuck: serve() keeps running and no strike is counted.
    """
    service = initialized_service_with_worker
    service.hassette.config.database.heartbeat_interval_seconds = TEST_HEARTBEAT_INTERVAL_SECONDS  # pyright: ignore[reportAttributeAccessIssue]
    assert service.hassette.config.database.max_consecutive_heartbeat_failures == TIMEOUTS_OUTLASTED

    attempts = 0
    real_update_heartbeat = service.update_heartbeat

    async def counting_update_heartbeat() -> None:
        nonlocal attempts
        attempts += 1
        await real_update_heartbeat()

    monkeypatch.setattr(service, "update_heartbeat", counting_update_heartbeat)

    async def batched_retention_pass() -> None:
        # Each loop stands in for one committed retention batch, which advances the counter
        # exactly as _delete_target_batched() does. The pass ends only once the heartbeat
        # attempt after the third timed-out one has started.
        while attempts <= TIMEOUTS_OUTLASTED:
            service._write_progress_count += 1
            await asyncio.sleep(BATCH_COMMIT_INTERVAL_SECONDS)

    pass_task = asyncio.create_task(service.submit(batched_retention_pass()))
    with patch(
        "hassette.core.database_service._HEARTBEAT_WRITE_TIMEOUT_SECONDS", PROGRESSING_PASS_HEARTBEAT_TIMEOUT_SECONDS
    ):
        serve_task = asyncio.create_task(service.serve())
        try:
            await asyncio.wait(
                {pass_task, serve_task}, timeout=PROGRESSING_PASS_DEADLINE_SECONDS, return_when=asyncio.FIRST_COMPLETED
            )
            assert not serve_task.done(), f"serve() exited during a progressing pass: {serve_task!r}"
            assert pass_task.done(), "maintenance pass never finished"
            assert service._consecutive_heartbeat_failures == 0
        finally:
            service.shutdown_event.set()
            await asyncio.wait_for(serve_task, timeout=5.0)


async def test_responsive_worker_whose_every_write_raises_reaches_strike_limit(
    initialized_service_with_worker: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker that drains the queue but fails every write makes no progress, so serve() restarts."""
    service = initialized_service_with_worker
    assert service._db is not None
    monkeypatch.setattr(service._db, "execute", failing_execute)
    service.hassette.config.database.heartbeat_interval_seconds = TEST_HEARTBEAT_INTERVAL_SECONDS  # pyright: ignore[reportAttributeAccessIssue]

    with pytest.raises(RuntimeError, match="Heartbeat failed 3 consecutive times"):
        await asyncio.wait_for(service.serve(), timeout=5.0)


async def test_stuck_worker_reaches_strike_limit(initialized_service_with_worker: DatabaseService) -> None:
    """A worker parked inside a write commits nothing, so every timed-out heartbeat counts a strike."""
    service = initialized_service_with_worker
    gate = asyncio.Event()
    stuck = asyncio.Event()

    async def wedge() -> None:
        stuck.set()
        await gate.wait()

    assert service.enqueue(wedge()) is True
    await asyncio.wait_for(stuck.wait(), timeout=1.0)
    service.hassette.config.database.heartbeat_interval_seconds = TEST_HEARTBEAT_INTERVAL_SECONDS  # pyright: ignore[reportAttributeAccessIssue]

    try:
        with (
            patch("hassette.core.database_service._HEARTBEAT_WRITE_TIMEOUT_SECONDS", TEST_HEARTBEAT_TIMEOUT_SECONDS),
            pytest.raises(RuntimeError, match="Heartbeat failed 3 consecutive times"),
        ):
            await asyncio.wait_for(service.serve(), timeout=5.0)
    finally:
        gate.set()


async def test_failed_heartbeat_counts_only_when_progress_stalls_since_previous_attempt(
    initialized_service_with_worker: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Progress is measured from the previous attempt, not from the last strike or success."""
    service = initialized_service_with_worker
    assert service._db is not None
    monkeypatch.setattr(service._db, "execute", failing_execute)

    await asyncio.wait_for(service.update_heartbeat(), timeout=5.0)
    assert service._consecutive_heartbeat_failures == 1

    service._write_progress_count += 1  # another write committed between attempts
    await asyncio.wait_for(service.update_heartbeat(), timeout=5.0)
    assert service._consecutive_heartbeat_failures == 1

    await asyncio.wait_for(service.update_heartbeat(), timeout=5.0)
    assert service._consecutive_heartbeat_failures == 2
