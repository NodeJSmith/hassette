"""In-memory dummy cache for test isolation.

``DummyCache``/``DummySyncCache`` implement the same interface as
``AsyncCache``/``SyncCache`` backed by a plain dict instead of SQLite, so test code
exercises the same default-TTL-resolution and expiry behavior without temp directory
management.
"""

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from hassette.cache._helpers import MISSING, guard_not_in_event_loop, resolve_ttl, validate_key

T = TypeVar("T")

CacheEntry = tuple[object, float | None]
"""A stored (value, expires_at) pair. ``expires_at`` is ``None`` for entries that persist indefinitely."""


class DummySyncCache:
    """In-memory sync facade for ``DummyCache``. Shares the same backing dict."""

    def __init__(self, store: dict[str, CacheEntry], default_ttl: int | None = None) -> None:
        self._store = store
        self.default_ttl = default_ttl

    def get(self, key: str, default: T | None = None) -> T | None:
        guard_not_in_event_loop("DummySyncCache.get")
        validate_key(key)
        entry = self._store.get(key)
        if entry is None:
            return default
        value, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            self._store.pop(key, None)
            return default
        # The store holds values untyped (CacheEntry = tuple[object, ...]) since it never
        # validates what callers stored -- trust the caller's T at this boundary.
        return cast("T", value)

    def set(self, key: str, value: object, ttl: int | None = None) -> None:
        guard_not_in_event_loop("DummySyncCache.set")
        validate_key(key)
        resolved_ttl = resolve_ttl(ttl, self.default_ttl)
        if resolved_ttl == 0:
            self.delete(key)
            return
        expires_at = time.time() + resolved_ttl if resolved_ttl is not None else None
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        guard_not_in_event_loop("DummySyncCache.delete")
        validate_key(key)
        self._store.pop(key, None)

    def get_or_set(self, key: str, creator: Callable[[], T], ttl: int | None = None) -> T:
        guard_not_in_event_loop("DummySyncCache.get_or_set")
        validate_key(key)
        cached = self.get(key, default=cast("T", MISSING))
        if cached is not MISSING:
            return cast("T", cached)
        value = creator()
        self.set(key, value, ttl=ttl)
        return value

    def clear(self) -> None:
        guard_not_in_event_loop("DummySyncCache.clear")
        self._store.clear()

    def invalidate(self, *keys: str) -> None:
        guard_not_in_event_loop("DummySyncCache.invalidate")
        for key in keys:
            validate_key(key)
            self._store.pop(key, None)


class DummyCache:
    """In-memory async cache for test isolation. Stores ``(value, expires_at)`` tuples."""

    def __init__(self, default_ttl: int | None = None) -> None:
        self.default_ttl = default_ttl
        self._store: dict[str, CacheEntry] = {}
        self.sync = DummySyncCache(self._store, default_ttl)

    async def initialize(self) -> None:
        """No-op -- DummyCache has no backing store to initialize."""

    async def get(self, key: str, default: T | None = None) -> T | None:
        """Return the cached value for *key*, or *default* if missing or expired."""
        validate_key(key)
        entry = self._store.get(key)
        if entry is None:
            return default
        value, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            self._store.pop(key, None)
            return default
        # The store holds values untyped (CacheEntry = tuple[object, ...]) since it never
        # validates what callers stored -- trust the caller's T at this boundary.
        return cast("T", value)

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
        self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        """Delete the entry at *key*, if any."""
        validate_key(key)
        self._store.pop(key, None)

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
        """Delete all entries."""
        self._store.clear()

    async def invalidate(self, *keys: str) -> None:
        """Delete all listed keys in one operation."""
        for key in keys:
            validate_key(key)
            self._store.pop(key, None)

    async def close(self) -> None:
        """No-op -- DummyCache has no connections to close."""
