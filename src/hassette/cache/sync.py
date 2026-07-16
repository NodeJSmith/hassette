"""Hand-written synchronous cache facade using stdlib ``sqlite3``.

Not a ``Resource`` -- a plain object owned by :class:`~hassette.cache.wrapper.AsyncCache`,
created during ``AsyncCache.initialize()``. Accessed via ``cache.sync``.

Opens a fresh ``sqlite3`` connection per method call (connect -> execute -> close) --
no shared connection, trivially thread-safe for the multi-worker ``AppSync`` thread
pool. Every public method guards against being called from inside a running event
loop, matching the safety contract of ``ApiSyncFacade``/``BusSyncFacade``/``SchedulerSyncFacade``.
"""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from hassette.cache._helpers import (
    BUSY_TIMEOUT_MS,
    DESERIALIZE_FAILED,
    MISSING,
    deserialize,
    guard_not_in_event_loop,
    resolve_ttl,
    serialize,
    validate_key,
)

T = TypeVar("T")


class SyncCache:
    """Synchronous cache facade backed by stdlib ``sqlite3``.

    Assumes the ``cache_entries`` table already exists -- schema creation is
    ``AsyncCache.initialize()``'s responsibility, run once before this facade is handed out.
    """

    def __init__(self, db_path: Path, default_ttl: int | None = None) -> None:
        self.db_path = db_path
        self.default_ttl = default_ttl

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return conn

    def get(self, key: str, default: T | None = None) -> T | None:
        guard_not_in_event_loop("SyncCache.get")
        validate_key(key)
        conn = self._connect()
        try:
            cursor = conn.execute("SELECT value, expires_at FROM cache_entries WHERE key = ?", (key,))
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            return default

        value_blob, expires_at = row
        if expires_at is not None and expires_at < time.time():
            self.delete(key)
            return default

        result = deserialize(value_blob, key)
        if result is DESERIALIZE_FAILED:
            self.delete(key)
            return default
        # deserialize() returns the unpickled value untyped (object) since the cache layer
        # never validates what callers stored -- trust the caller's T at this boundary.
        return cast("T", result)

    def set(self, key: str, value: object, ttl: int | None = None) -> None:
        guard_not_in_event_loop("SyncCache.set")
        validate_key(key)
        resolved_ttl = resolve_ttl(ttl, self.default_ttl)
        if resolved_ttl == 0:
            self.delete(key)
            return

        expires_at = time.time() + resolved_ttl if resolved_ttl is not None else None
        blob = serialize(value)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO cache_entries (key, value, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
                (key, blob, expires_at),
            )
        finally:
            conn.close()

    def delete(self, key: str) -> None:
        guard_not_in_event_loop("SyncCache.delete")
        validate_key(key)
        conn = self._connect()
        try:
            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
        finally:
            conn.close()

    def get_or_set(self, key: str, creator: Callable[[], T], ttl: int | None = None) -> T:
        guard_not_in_event_loop("SyncCache.get_or_set")
        validate_key(key)
        cached = self.get(key, default=cast("T", MISSING))
        if cached is not MISSING:
            return cast("T", cached)
        value = creator()
        self.set(key, value, ttl=ttl)
        return value

    def clear(self) -> None:
        guard_not_in_event_loop("SyncCache.clear")
        conn = self._connect()
        try:
            conn.execute("DELETE FROM cache_entries")
            conn.execute("PRAGMA incremental_vacuum")
        finally:
            conn.close()

    def invalidate(self, *keys: str) -> None:
        guard_not_in_event_loop("SyncCache.invalidate")
        if not keys:
            return
        for key in keys:
            validate_key(key)
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in keys)
            # placeholders is a fixed count of literal "?" characters, not user input -- not an injection vector.
            conn.execute(f"DELETE FROM cache_entries WHERE key IN ({placeholders})", keys)  # noqa: S608
        finally:
            conn.close()
