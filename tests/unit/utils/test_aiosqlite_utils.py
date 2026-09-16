"""Unit tests for ``close_connection_pair()``'s cancellation contract.

Covers the two guarantees the helper documents and that both call sites
(``AsyncCache._close_connections()`` and ``DatabaseService.close_connections()``) depend on:

    - both connections are always attempted and cleared, even when cancellation arrives while
      the *first* connection's background thread is being joined
    - a cancelled close does not spend the long off-loop join budget on a connection whose
      caller has already blown its shutdown deadline
"""

import asyncio
import logging

import pytest

from hassette.utils.aiosqlite_utils import (
    CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS,
    STOP_JOIN_TIMEOUT_SECONDS,
    close_connection_pair,
)

ATTRS = ("_write", "_read")
logger = logging.getLogger("tests.aiosqlite_utils")


class FakeThread:
    """Stand-in for an ``aiosqlite.Connection`` background thread.

    ``join()`` records the timeout it was given so tests can assert *which* join ran, and can be
    told to raise ``CancelledError``. Raising from inside the callable is a faithful stand-in for
    cancellation arriving mid-join: ``concurrent.futures`` propagates ``BaseException`` from a
    worker callable to the awaiting coroutine, so ``await asyncio.to_thread(...)`` sees the exact
    same ``CancelledError`` it would see from a real cancellation.
    """

    def __init__(self, *, alive: bool = True, cancel_on_join: bool = False, wedged: bool = False) -> None:
        self.daemon = True
        self._alive = alive
        self._cancel_on_join = cancel_on_join
        self._wedged = wedged
        self.join_timeouts: list[float | None] = []

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self.join_timeouts.append(timeout)
        if self._cancel_on_join:
            # One-shot: real cancellation is delivered once, not on every subsequent await.
            self._cancel_on_join = False
            raise asyncio.CancelledError
        if self._wedged:
            # A worker stuck on a long query outlives its join timeout.
            return
        self._alive = False


class FakeConnection:
    """Stand-in for an ``aiosqlite.Connection`` exposing only what the helper touches."""

    def __init__(self, *, close_raises: BaseException | None = None, thread: FakeThread | None = None) -> None:
        self._thread = thread if thread is not None else FakeThread(alive=False)
        self._close_raises = close_raises
        self.close_called = False
        self.stop_called = 0

    async def close(self) -> None:
        self.close_called = True
        if self._close_raises is not None:
            raise self._close_raises

    def stop(self) -> None:
        self.stop_called += 1


class FakeOwner:
    def __init__(self, write: FakeConnection | None, read: FakeConnection | None) -> None:
        self._write = write
        self._read = read


async def test_cancelled_join_still_closes_and_clears_second_connection() -> None:
    """Cancellation during the *join* must not abandon the second connection.

    The join runs after the close attempt, so a ``CancelledError`` escaping it skips both the
    attribute reset and the remaining connection -- leaking a connection whose ``__del__`` raises
    ``ResourceWarning`` and never checkpoints the WAL (#923, #1900).
    """
    write = FakeConnection(thread=FakeThread(alive=True, cancel_on_join=True))
    read = FakeConnection(thread=FakeThread(alive=True))
    owner = FakeOwner(write, read)

    with pytest.raises(asyncio.CancelledError):
        await close_connection_pair(owner, ATTRS, logger)

    assert read.close_called, "read connection must still be closed when the write join is cancelled"
    assert write.stop_called >= 1, "a cancelled join must still force the worker thread to stop"
    assert write._thread.join_timeouts == [CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS, STOP_JOIN_TIMEOUT_SECONDS]
    assert owner._write is None
    assert owner._read is None


async def test_cancelled_close_skips_the_long_join() -> None:
    """A cancelled close falls back to the short synchronous stop, not the 5s off-loop join.

    Cancellation means the caller's shutdown deadline already expired. Because asyncio
    cancellation is edge-triggered, a subsequent ``await`` is not interrupted, so a long join here
    would silently overrun the caller's hook/cleanup budget.
    """
    write = FakeConnection(close_raises=asyncio.CancelledError(), thread=FakeThread(alive=True))
    read = FakeConnection(thread=FakeThread(alive=True))
    owner = FakeOwner(write, read)

    with pytest.raises(asyncio.CancelledError):
        await close_connection_pair(owner, ATTRS, logger)

    assert write.stop_called >= 1, "a cancelled close must still force the worker thread to stop"
    assert write._thread.join_timeouts == [STOP_JOIN_TIMEOUT_SECONDS], (
        "cancelled close must use the short blocking join, never the long off-loop join"
    )
    assert read.close_called
    assert owner._write is None
    assert owner._read is None


async def test_clean_close_joins_with_the_long_timeout() -> None:
    """A clean close still joins a lingering worker thread off the event loop."""
    write = FakeConnection(thread=FakeThread(alive=True))
    read = FakeConnection(thread=FakeThread(alive=True))
    owner = FakeOwner(write, read)

    await close_connection_pair(owner, ATTRS, logger)

    assert write._thread.join_timeouts == [CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS]
    assert read._thread.join_timeouts == [CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS]
    assert owner._write is None
    assert owner._read is None


async def test_cancel_takes_precedence_over_a_non_cancel_error() -> None:
    """A non-cancel failure on the first connection never masks a later cancellation."""
    write = FakeConnection(close_raises=RuntimeError("write boom"))
    read = FakeConnection(close_raises=asyncio.CancelledError())
    owner = FakeOwner(write, read)

    with pytest.raises(asyncio.CancelledError):
        await close_connection_pair(owner, ATTRS, logger)

    assert owner._write is None
    assert owner._read is None


async def test_non_cancel_error_is_raised_after_both_connections_are_handled() -> None:
    """A close failure propagates, but only once the second connection has been closed too.

    Both callers record a ``TeardownCause`` from the escaping exception; swallowing it would let a
    connection left in an unknown state be reported as a restart-safe teardown.
    """
    write = FakeConnection(close_raises=RuntimeError("write boom"))
    read = FakeConnection()
    owner = FakeOwner(write, read)

    with pytest.raises(RuntimeError, match="write boom"):
        await close_connection_pair(owner, ATTRS, logger)

    assert write.stop_called >= 1
    assert read.close_called
    assert owner._write is None
    assert owner._read is None


async def test_missing_connection_is_skipped_without_blocking_the_other() -> None:
    """A half-open owner (one connection never opened) still closes the one it has.

    Reachable whenever connection setup fails partway through.
    """
    read = FakeConnection(thread=FakeThread(alive=True))
    owner = FakeOwner(None, read)

    await close_connection_pair(owner, ATTRS, logger)

    assert read.close_called
    assert owner._read is None


async def test_already_exited_thread_is_not_joined() -> None:
    """No join is attempted when the worker thread has already exited."""
    write = FakeConnection(thread=FakeThread(alive=False))
    read = FakeConnection(thread=FakeThread(alive=False))
    owner = FakeOwner(write, read)

    await close_connection_pair(owner, ATTRS, logger)

    assert write._thread.join_timeouts == []
    assert read._thread.join_timeouts == []
    assert owner._write is None
    assert owner._read is None


async def test_wedged_thread_does_not_block_the_remaining_connection() -> None:
    """A worker still alive after its bounded join is abandoned, not waited on further.

    ``connect_daemon()`` makes these threads daemons precisely so a wedged one cannot block
    interpreter exit, so timing out here must not raise or strand the second connection.
    """
    write = FakeConnection(thread=FakeThread(alive=True, wedged=True))
    read = FakeConnection(thread=FakeThread(alive=True))
    owner = FakeOwner(write, read)

    await close_connection_pair(owner, ATTRS, logger)

    assert write._thread.join_timeouts == [CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS]
    assert write._thread.is_alive(), "the fake must still be wedged -- otherwise this tests nothing"
    assert read.close_called
    assert owner._write is None
    assert owner._read is None
