"""aiosqlite lifecycle helpers: daemon-thread connection opening and async/sync teardown."""

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite

STOP_JOIN_TIMEOUT_SECONDS = 0.1
"""Bound on ``Thread.join()`` while stopping a connection synchronously.

Closing a local sqlite handle is normally sub-millisecond; this timeout exists only to avoid the
cross-thread ``RuntimeError`` race described in ``stop_connection_sync()``'s docstring, not to
tolerate a slow close. Kept short because the caller blocks the event loop thread for the
duration.
"""

CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS = 5.0
"""Bound on awaiting a closed aiosqlite connection's background thread via ``asyncio.to_thread()``.

Unlike ``STOP_JOIN_TIMEOUT_SECONDS``, this join runs off the event loop thread, so it can afford to
wait longer for a clean exit before giving up and just logging a warning.
"""


async def connect_daemon(database: str | Path, **kwargs: Any) -> aiosqlite.Connection:
    """Open an aiosqlite connection whose worker thread is a daemon.

    aiosqlite creates a non-daemon background thread per connection. If the connection
    is not closed cleanly (e.g. CancelledError during shutdown), the thread blocks
    interpreter exit indefinitely. Setting daemon=True before start() lets the interpreter
    exit even if the thread is still alive.

    No public API exists for this — see aiosqlite#299.
    """
    conn = aiosqlite.connect(database, **kwargs)
    conn._thread.daemon = True
    return await conn


def stop_connection_sync(conn: aiosqlite.Connection | None) -> None:
    """Synchronously stop an aiosqlite connection's background thread, bypassing the async close protocol.

    ``Connection.stop()`` (unlike ``close()``) is synchronous -- it queues a close on the
    connection's own background thread and returns immediately. Used on force-terminal paths that
    cannot ``await`` anything (``App._force_terminal()``, ``DatabaseService._force_terminal()``).

    Joins the thread (bounded, brief) after calling ``stop()``. ``stop()`` hands the actual close
    off to the connection's background thread, which reports back to the *current* event loop via
    ``call_soon_threadsafe()`` once done. If that loop closes before the thread gets scheduled, the
    callback raises ``RuntimeError: Event loop is closed`` on the background thread -- unrelated to
    whether the underlying sqlite3 connection actually closed (it did; the close runs before the
    callback). Joining here keeps this call blocking only until the thread finishes, which happens
    on the *current* loop's own thread and therefore guarantees the loop cannot close out from
    under it in the interim.

    No-op when ``conn`` is ``None``.
    """
    if conn is None:
        return
    conn.stop()
    thread = getattr(conn, "_thread", None)
    if thread is not None and thread.is_alive():
        thread.join(timeout=STOP_JOIN_TIMEOUT_SECONDS)


async def close_connection_pair(
    owner: object,
    attrs: tuple[str, str],
    logger: logging.Logger,
) -> None:
    """Close a read/write aiosqlite connection pair, tolerating ``CancelledError``.

    Every connection is always attempted, always joined, and always cleared, whatever the one
    before it did. Each is then handled one of three ways:

    - **Clean close:** join the background thread, bounded by
      ``CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS`` and run off the event loop via
      ``asyncio.to_thread()``. ``close()`` returning does not mean the thread has exited.
    - **Close raised:** log it, ``stop()`` the connection, then join as above. There is still a
      time budget, so it is worth waiting for the worker to wind down.
    - **Cancelled** (during either the close or that join): ``stop_connection_sync()``'s short
      blocking join instead of the long one, and on to the next connection.

    Re-raises the first failure once both connections are handled, a ``CancelledError`` taking
    precedence over a non-cancel error regardless of which connection raised first. Nothing is
    swallowed: both callers feed teardown accounting that has to tell a clean close from one that
    left a connection in an unknown state, and a close that never confirmed must not be recorded as
    a restart-safe teardown.

    Args:
        owner: The object holding the connection attributes (e.g. an ``AsyncCache`` or
            ``DatabaseService`` instance).
        attrs: The two attribute names on *owner* holding ``aiosqlite.Connection | None``, closed
            in the order given. Order is load-bearing: the connection closed last is the one that
            performs the WAL checkpoint, and an earlier connection's failure is the one re-raised.
        logger: Logger to report non-cancel close failures and slow thread exits to.

    Raises:
        BaseException: The first ``CancelledError`` if either connection's close or join was
            cancelled, otherwise the first non-cancel close exception, if any.
    """
    first_error: Exception | None = None
    first_cancel: BaseException | None = None
    for attr in attrs:
        conn: aiosqlite.Connection | None = getattr(owner, attr)
        if conn is None:
            continue

        cancelled: BaseException | None = None
        try:
            await conn.close()
        except asyncio.CancelledError as exc:  # noqa: ASYNC103 — re-raised after both connections are handled
            cancelled = exc
        except Exception as exc:
            logger.exception("Failed to close %s — falling back to sync stop()", attr)
            conn.stop()
            if first_error is None:
                first_error = exc

        if cancelled is None:
            cancelled = await _join_worker_thread_or_cancellation(conn, attr, logger)

        if cancelled is not None:
            # Cancellation means the caller's shutdown deadline has already expired, and asyncio
            # cancellation is edge-triggered -- an expired asyncio.timeout() will not interrupt any
            # further await here. Force the worker down with the short blocking join rather than
            # silently overrunning the caller's hook/cleanup budget by seconds per connection.
            stop_connection_sync(conn)
            if first_cancel is None:
                first_cancel = cancelled

        setattr(owner, attr, None)
    if first_cancel is not None:
        raise first_cancel
    if first_error is not None:
        raise first_error


async def _join_worker_thread_or_cancellation(
    conn: aiosqlite.Connection,
    attr: str,
    logger: logging.Logger,
) -> asyncio.CancelledError | None:
    """Wait off the event loop for *conn*'s background thread to exit, bounded and non-fatal.

    **Returns** a ``CancelledError`` rather than raising it, so the caller can finish handling this
    connection and move on to the next instead of unwinding mid-teardown. Turning that return into
    a ``raise`` -- the otherwise idiomatic thing to do -- silently breaks
    ``close_connection_pair()``'s guarantee that both connections are always closed and cleared.

    A thread still alive at the timeout is logged and left alone: ``connect_daemon()`` makes these
    threads daemons precisely so a wedged one cannot block interpreter exit.
    """
    thread = getattr(conn, "_thread", None)
    if thread is None or not thread.is_alive():
        return None
    try:
        await asyncio.to_thread(thread.join, CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS)
    except asyncio.CancelledError as exc:  # noqa: ASYNC103 — returned to the caller, which re-raises it
        return exc  # noqa: ASYNC104 — close_connection_pair() re-raises this once both connections are handled
    if thread.is_alive():
        logger.warning(
            "aiosqlite background thread for %s did not exit within %.1fs",
            attr,
            CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS,
        )
    return None
