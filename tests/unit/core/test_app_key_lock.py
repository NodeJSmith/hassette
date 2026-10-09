"""AppKeyLock reports busy across the release-to-waiter handoff that ``locked()`` misses."""

import asyncio

from hassette.core.app_key_lock import AppKeyLock
from hassette.testing import wait_for

WAIT_TIMEOUT_SECONDS = 1


async def test_busy_through_handoff_to_a_queued_waiter() -> None:
    """Between release() and the woken waiter re-taking the lock, locked() is false but busy is not."""
    lock = AppKeyLock()
    await lock.acquire()
    waiter = asyncio.create_task(lock.acquire())
    await wait_for(lambda: bool(lock._waiters), desc="waiter queued on the lock")

    lock.release()

    assert not lock.locked()
    assert lock.busy
    await asyncio.wait_for(waiter, WAIT_TIMEOUT_SECONDS)
    lock.release()
    assert not lock.busy


async def test_cancelled_waiter_drops_its_claim() -> None:
    """A task cancelled while waiting for the lock no longer counts toward busy."""
    lock = AppKeyLock()
    await lock.acquire()
    waiter = asyncio.create_task(lock.acquire())
    await wait_for(lambda: bool(lock._waiters), desc="waiter queued on the lock")

    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    lock.release()

    assert not lock.busy


async def test_async_with_counts_the_holder() -> None:
    """``async with`` routes through acquire()/release(), so a holder is busy and frees on exit."""
    lock = AppKeyLock()
    async with lock:
        assert lock.busy
    assert not lock.busy
