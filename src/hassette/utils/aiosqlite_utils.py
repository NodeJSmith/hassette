"""aiosqlite lifecycle helpers: daemon-thread connection opening, and async/sync teardown."""

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
    *,
    reraise_non_cancel: bool,
) -> None:
    """Close a read/write aiosqlite connection pair, tolerating ``CancelledError``.

    Always attempts both connections even if the first raises. On ``CancelledError``, falls back to
    synchronous ``stop()`` for the current connection and continues to the next, re-raising the
    first ``CancelledError`` after both are handled (unconditionally -- a cancelled close always
    means an aborted shutdown and callers always need to know). Non-cancel exceptions are logged via
    ``logger.exception()``; whether they are also re-raised is controlled by ``reraise_non_cancel``
    so each caller keeps the re-raise contract its own shutdown/cleanup accounting depends on (see
    #1902 for why both callers currently re-raise).

    Joins each connection's background thread (bounded by ``CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS``,
    off the event loop thread via ``asyncio.to_thread``) whenever it is still alive after handling --
    including the clean-close path, since ``close()`` returning does not guarantee the background
    thread has fully exited.

    Args:
        owner: The object holding the connection attributes (e.g. an ``AsyncCache`` or
            ``DatabaseService`` instance).
        attrs: The two attribute names on *owner* holding ``aiosqlite.Connection | None``.
        logger: Logger to report non-cancel close failures and slow thread exits to.
        reraise_non_cancel: Whether to re-raise the first non-cancel exception after both
            connections are handled.
    """
    first_error: Exception | None = None
    first_cancel: BaseException | None = None
    for attr in attrs:
        conn: aiosqlite.Connection | None = getattr(owner, attr)
        if conn is None:
            continue
        try:
            await conn.close()
        except asyncio.CancelledError as exc:  # noqa: ASYNC103 — re-raised after both connections are handled
            conn.stop()
            if first_cancel is None:
                first_cancel = exc
        except Exception as exc:
            logger.exception("Failed to close %s — falling back to sync stop()", attr)
            conn.stop()
            if first_error is None:
                first_error = exc
        finally:
            thread = getattr(conn, "_thread", None)
            if thread is not None and thread.is_alive():
                await asyncio.to_thread(thread.join, CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS)
                if thread.is_alive():
                    logger.warning(
                        "aiosqlite background thread for %s did not exit within %.1fs",
                        attr,
                        CONNECTION_CLOSE_JOIN_TIMEOUT_SECONDS,
                    )
            setattr(owner, attr, None)
    if first_cancel is not None:
        raise first_cancel
    if reraise_non_cancel and first_error is not None:
        raise first_error
