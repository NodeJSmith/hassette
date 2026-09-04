"""aiosqlite lifecycle helpers: daemon-thread connection opening and synchronous teardown."""

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
