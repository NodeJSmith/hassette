"""Async cache backed by ``aiosqlite``, using a read/write connection pair in WAL mode."""

import asyncio
import contextlib
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar, cast

import aiosqlite

from hassette.cache._helpers import (
    BUSY_TIMEOUT_MS,
    DESERIALIZE_FAILED,
    MISSING,
    SCHEMA_DDL,
    deserialize,
    resolve_ttl,
    serialize,
    validate_key,
)
from hassette.cache.sync import SyncCache
from hassette.utils.aiosqlite_utils import connect_daemon, stop_connection_sync

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CORRUPTION_INDICATORS = ("file is not a database", "database disk image is malformed", "integrity check failed")
"""Best-effort match on SQLite's error text — not a stable API, but these messages have been unchanged for 15+ years."""


def _is_corruption(exc: sqlite3.Error) -> bool:
    """Return True if *exc* indicates SQLite database corruption."""
    msg = str(exc).lower()
    return any(indicator in msg for indicator in _CORRUPTION_INDICATORS)


class AsyncCache:
    """Primary async cache implementation.

    A plain class (not a ``Resource``) -- ``App`` creates it and manages its lifecycle
    explicitly via ``initialize()``/``close()``. Uses two ``aiosqlite`` connections (a
    read/write pair) in WAL mode, matching the pattern in ``database_service.py``.
    """

    def __init__(self, db_path: Path, default_ttl: int | None = None) -> None:
        self.db_path = db_path
        self.default_ttl = default_ttl
        self._write: aiosqlite.Connection | None = None
        self._read: aiosqlite.Connection | None = None
        self.sync: SyncCache | None = None
        """Synchronous facade pointing at the same database file. Set by ``initialize()``."""

    @property
    def _write_conn(self) -> aiosqlite.Connection:
        if self._write is None:
            raise RuntimeError("AsyncCache is not initialized -- call initialize() first")
        return self._write

    @property
    def _read_conn(self) -> aiosqlite.Connection:
        if self._read is None:
            raise RuntimeError("AsyncCache is not initialized -- call initialize() first")
        return self._read

    async def initialize(self) -> None:
        """Open connections, create the schema, and check integrity.

        Steps 1-3 (open connections, create schema, integrity check) are wrapped in a
        single try/except for ``sqlite3.Error``. On failure, connections are closed, the
        SQLite file and its ``-wal``/``-shm`` sidecars are deleted, and the sequence
        retries once from step 1 with a warning log. If the retry also fails, the
        exception propagates -- a second failure on a freshly-created database indicates
        a filesystem or permissions problem, not recoverable corruption.

        Both cleanup calls to ``_close_connections()`` here suppress its own exception --
        it now raises on a failed close (see its docstring), but a connection already known
        to be broken or corrupt failing to close cleanly is not itself actionable here, and
        letting it propagate would replace the ``sqlite3.Error`` being handled (bare ``raise``
        never runs) or abort the corruption retry before it starts. ``_close_connections()``
        already logs the close failure internally, so nothing is silently lost.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            await self._open_connections()
            await self._run_schema()
            await self._check_integrity()
        except sqlite3.Error as exc:
            if not _is_corruption(exc):
                with contextlib.suppress(Exception):
                    await self._close_connections()
                raise

            # Corruption confirmed — delete and retry once.
            logger.warning(
                "Cache database at %s failed to initialize; deleting and recreating", self.db_path, exc_info=True
            )
            with contextlib.suppress(Exception):
                await self._close_connections()
            self._delete_db_files()
            await self._open_connections()
            await self._run_schema()
            await self._check_integrity()

        self.sync = SyncCache(self.db_path, self.default_ttl)

    async def _open_connections(self) -> None:
        self._write = await connect_daemon(self.db_path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
        self._write.row_factory = aiosqlite.Row
        await self._write.execute("PRAGMA journal_mode = WAL")
        await self._write.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

        self._read = await connect_daemon(self.db_path, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
        self._read.row_factory = aiosqlite.Row
        await self._read.execute("PRAGMA query_only = ON")
        await self._read.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

    async def _run_schema(self) -> None:
        for statement in SCHEMA_DDL:
            await self._write_conn.execute(statement)

    async def _check_integrity(self) -> None:
        async with self._write_conn.execute("PRAGMA integrity_check") as cursor:
            row = await cursor.fetchone()
        if row is None or row[0] != "ok":
            raise sqlite3.DatabaseError(f"Cache database integrity check failed: {row!r}")

    async def _close_connections(self) -> None:
        """Close both connections, attempting each even if the other fails.

        Raises the first close error encountered (after both attempts complete) instead of
        swallowing it -- a caller (``App.cleanup()``) relies on this to distinguish a clean
        close from one that left a connection/background thread in an unknown state, so
        ``_run_post_hook_shutdown_stage()`` can record ``TeardownCause.CLEANUP_FAILED`` rather
        than reporting a restart-safe teardown that never actually confirmed the cache closed.

        Handles ``CancelledError`` explicitly: catches it, falls back to synchronous ``stop()``
        for the current connection, continues to the next, and re-raises after both are handled.
        Without this, a cancellation during the first ``close()`` skips the second connection
        entirely -- the leaked connection triggers ``Connection.__del__`` ``ResourceWarning``
        and skips the clean WAL checkpoint (#923, #1900).
        """
        first_error: Exception | None = None
        first_cancel: BaseException | None = None
        for attr in ("_write", "_read"):
            conn: aiosqlite.Connection | None = getattr(self, attr)
            if conn is None:
                continue
            try:
                await conn.close()
            except asyncio.CancelledError as exc:  # noqa: ASYNC103 — re-raised after both connections are handled
                stop_connection_sync(conn)
                if first_cancel is None:
                    first_cancel = exc
            except Exception as exc:
                logger.exception("Error closing cache connection (%s)", attr)
                stop_connection_sync(conn)
                if first_error is None:
                    first_error = exc
            finally:
                setattr(self, attr, None)
        if first_cancel is not None:
            raise first_cancel
        if first_error is not None:
            raise first_error

    def _delete_db_files(self) -> None:
        self.db_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

    async def _delete_stale(self, key: str, value_blob: bytes) -> None:
        """Delete a cache row only if it still holds the observed value blob.

        Prevents a concurrent writer's fresh value from being removed when this
        reader observes a stale or corrupt entry.
        """
        await self._write_conn.execute("DELETE FROM cache_entries WHERE key = ? AND value = ?", (key, value_blob))
        await self._write_conn.commit()

    async def get(self, key: str, default: T | None = None) -> T | None:
        """Return the cached value for *key*, or *default* if missing or expired."""
        validate_key(key)
        async with self._read_conn.execute(
            "SELECT value, expires_at FROM cache_entries WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return default

        value_blob, expires_at = row
        if expires_at is not None and expires_at < time.time():
            await self._delete_stale(key, value_blob)
            return default

        result = deserialize(value_blob, key)
        if result is DESERIALIZE_FAILED:
            await self._delete_stale(key, value_blob)
            return default
        # deserialize() returns the unpickled value untyped (object) since the cache layer
        # never validates what callers stored -- trust the caller's T at this boundary.
        return cast("T", result)

    async def set(self, key: str, value: object, ttl: int | None = None) -> None:
        """Store *value* under *key*.

        ``ttl=None`` falls back to ``self.default_ttl``. ``ttl=0`` deletes any existing
        entry and does not store the new value.
        """
        validate_key(key)
        resolved_ttl = resolve_ttl(ttl, self.default_ttl)
        if resolved_ttl == 0:
            await self.delete(key)
            return

        expires_at = time.time() + resolved_ttl if resolved_ttl is not None else None
        blob = serialize(value)
        await self._write_conn.execute(
            "INSERT INTO cache_entries (key, value, expires_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
            (key, blob, expires_at),
        )
        await self._write_conn.commit()

    async def delete(self, key: str) -> None:
        """Delete the entry at *key*, if any."""
        validate_key(key)
        await self._write_conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
        await self._write_conn.commit()

    async def get_or_set(self, key: str, creator: Callable[[], Awaitable[T]], ttl: int | None = None) -> T:
        """Return the cached value for *key*, computing and storing it via *creator* on miss."""
        validate_key(key)
        cached = await self.get(key, default=cast("T", MISSING))
        if cached is not MISSING:
            return cast("T", cached)
        value = await creator()
        await self.set(key, value, ttl=ttl)
        return value

    async def clear(self) -> None:
        """Delete all entries and run ``PRAGMA incremental_vacuum`` to reclaim disk space."""
        await self._write_conn.execute("DELETE FROM cache_entries")
        await self._write_conn.commit()
        await self._write_conn.execute("PRAGMA incremental_vacuum")
        await self._write_conn.commit()

    async def invalidate(self, *keys: str) -> None:
        """Delete all listed keys in one operation."""
        if not keys:
            return
        for key in keys:
            validate_key(key)
        placeholders = ",".join("?" for _ in keys)
        # placeholders is a fixed count of literal "?" characters, not user input -- not an injection vector.
        await self._write_conn.execute(f"DELETE FROM cache_entries WHERE key IN ({placeholders})", keys)  # noqa: S608
        await self._write_conn.commit()

    async def close(self) -> None:
        """Close both ``aiosqlite`` connections. Attempts both even if one fails; logs and
        raises the first close error encountered, if any.
        """
        await self._close_connections()

    def force_close(self) -> None:
        """Synchronously stop both connections' background threads without the async close protocol.

        Used by ``App._force_terminal()``, which cannot ``await`` anything. See
        ``stop_connection_sync()`` for why this is safe to call from a force-terminal path.
        """
        for attr in ("_write", "_read"):
            stop_connection_sync(getattr(self, attr))
            setattr(self, attr, None)
