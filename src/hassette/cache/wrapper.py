"""Async cache backed by ``aiosqlite``, using a read/write connection pair in WAL mode."""

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

logger = logging.getLogger(__name__)

T = TypeVar("T")


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
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            await self._open_connections()
            await self._run_schema()
            await self._check_integrity()
        except sqlite3.Error:
            logger.warning(
                "Cache database at %s failed to initialize; deleting and recreating", self.db_path, exc_info=True
            )
            await self._close_connections()
            self._delete_db_files()
            await self._open_connections()
            await self._run_schema()
            await self._check_integrity()

        self.sync = SyncCache(self.db_path, self.default_ttl)

    async def _open_connections(self) -> None:
        self._write = await aiosqlite.connect(self.db_path, isolation_level=None)
        self._write.row_factory = aiosqlite.Row
        await self._write.execute("PRAGMA journal_mode = WAL")
        await self._write.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

        self._read = await aiosqlite.connect(self.db_path, isolation_level=None)
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
        for attr in ("_write", "_read"):
            conn: aiosqlite.Connection | None = getattr(self, attr)
            if conn is None:
                continue
            try:
                await conn.close()
            except Exception:
                logger.exception("Error closing cache connection (%s)", attr)
            finally:
                setattr(self, attr, None)

    def _delete_db_files(self) -> None:
        self.db_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

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
            await self.delete(key)
            return default

        result = deserialize(value_blob, key)
        if result is DESERIALIZE_FAILED:
            await self.delete(key)
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
        """Close both ``aiosqlite`` connections. Swallows and logs close errors."""
        await self._close_connections()
