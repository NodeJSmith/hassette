"""Regression tests for issue #2283 (TOCTOU race between update_heartbeat's guard and submit()).

Split out from test_database_service.py to avoid growing that already-oversized file further --
see tools/check_file_size_regressions.py.
"""

import asyncio

import pytest

from hassette.core.database_service import DatabaseService, _WriteQueueItem
from tests.unit.core._fixtures_database_service import initialized_service_with_worker, mock_hassette, service

__all__ = ["initialized_service_with_worker", "mock_hassette", "service"]  # re-exposed as fixtures


def _queue_detached_after_n_reads(
    monkeypatch: pytest.MonkeyPatch,
    real_queue: asyncio.Queue[_WriteQueueItem],
    reads_before_detach: int,
) -> None:
    """Patch ``DatabaseService._db_write_queue`` to return ``real_queue`` for the first
    ``reads_before_detach`` reads, then ``None`` for every read after -- simulating a teardown
    path detaching the queue partway through a caller's own sequence of reads. Restored
    automatically at test teardown by ``monkeypatch``.
    """
    reads = 0

    def _read(_service: DatabaseService) -> asyncio.Queue[_WriteQueueItem] | None:
        nonlocal reads
        reads += 1
        return real_queue if reads <= reads_before_detach else None

    # raising=False: _db_write_queue is a bare class-level annotation (no default), so it's
    # never actually present in DatabaseService.__dict__ until an instance sets it in __init__.
    monkeypatch.setattr(DatabaseService, "_db_write_queue", property(_read), raising=False)


async def test_update_heartbeat_counts_write_queue_unavailable_error_as_failure(
    initialized_service_with_worker: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A WriteQueueUnavailableError raised by submit() must count as a heartbeat failure,
    identically to a timeout or a sqlite3 error, instead of propagating out of
    update_heartbeat() and crashing serve(). Drives the real submit() path rather than mocking
    it, so this also proves update_heartbeat()'s except clause catches the exact type submit()
    raises.
    """
    service = initialized_service_with_worker
    real_queue = service._db_write_queue
    assert real_queue is not None
    assert service._consecutive_heartbeat_failures == 0

    _queue_detached_after_n_reads(monkeypatch, real_queue, reads_before_detach=1)
    await asyncio.wait_for(service.update_heartbeat(), timeout=5.0)

    assert service._consecutive_heartbeat_failures == 1


async def test_update_heartbeat_survives_write_queue_detached_between_guard_and_submit_put(
    initialized_service_with_worker: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the TOCTOU race (audit Finding 3): update_heartbeat() checks
    ``_db_write_queue is not None`` once and then calls submit(). Before the fix, submit()
    re-read ``self._db_write_queue`` a second time instead of reusing the value its own entry
    check had just observed, so a detach landing in that window crashed with
    ``AttributeError`` from ``None.put(...)`` instead of raising a heartbeat-countable error.

    Models the race via ``_queue_detached_after_n_reads()``: the queue is present for the
    first two reads (update_heartbeat()'s guard, then submit()'s captured-local read) and gone
    from the third read onward. Post-fix, submit() never reads the attribute a third time, so
    it never observes the simulated detach and the heartbeat completes normally.
    """
    service = initialized_service_with_worker
    real_queue = service._db_write_queue
    assert real_queue is not None

    _queue_detached_after_n_reads(monkeypatch, real_queue, reads_before_detach=2)
    await asyncio.wait_for(service.update_heartbeat(), timeout=5.0)

    assert service._consecutive_heartbeat_failures == 0
