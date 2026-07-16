"""Unit tests for hassette.cache.dummy.DummyCache and DummySyncCache."""

import asyncio

import pytest

from hassette.cache.dummy import DummyCache, DummySyncCache
from hassette.cache.protocol import CacheProtocol


@pytest.fixture
def cache() -> DummyCache:
    return DummyCache()


def test_dummy_cache_satisfies_cache_protocol(cache: DummyCache) -> None:
    """DummyCache is a CacheProtocol-conforming instance."""
    assert isinstance(cache, CacheProtocol)


def test_dummy_sync_cache_does_not_satisfy_cache_protocol(cache: DummyCache) -> None:
    """DummySyncCache does not satisfy CacheProtocol -- it's accessed via `.sync`, never polymorphically."""
    assert not isinstance(cache.sync, CacheProtocol)


async def test_initialize_and_close_are_no_ops(cache: DummyCache) -> None:
    """initialize() and close() do not raise and require no setup."""
    await cache.initialize()
    await cache.close()


async def test_set_and_get_round_trip(cache: DummyCache) -> None:
    """A value stored via set() is returned unchanged by get()."""
    await cache.set("greeting", {"text": "hello"})
    assert await cache.get("greeting") == {"text": "hello"}


async def test_get_returns_default_when_missing(cache: DummyCache) -> None:
    """get() returns the provided default when the key doesn't exist."""
    assert await cache.get("missing", default="fallback") == "fallback"
    assert await cache.get("missing") is None


async def test_get_returns_none_for_expired_entry(cache: DummyCache) -> None:
    """get() returns None once a TTL'd entry has expired."""
    await cache.set("short-lived", "value", ttl=1)
    assert await cache.get("short-lived") == "value"
    await asyncio.sleep(1.2)
    assert await cache.get("short-lived") is None


async def test_set_with_no_ttl_uses_instance_default() -> None:
    """set(ttl=None) falls back to the instance default_ttl and expires accordingly."""
    cache = DummyCache(default_ttl=1)
    await cache.set("k", "v")
    assert await cache.get("k") == "v"
    await asyncio.sleep(1.2)
    assert await cache.get("k") is None


async def test_set_ttl_zero_deletes_existing_and_does_not_store(cache: DummyCache) -> None:
    """set(key, value, ttl=0) deletes any existing entry and does not store the new value."""
    await cache.set("key", "original")
    assert await cache.get("key") == "original"

    await cache.set("key", "new-value", ttl=0)
    assert await cache.get("key") is None


async def test_delete_removes_entry(cache: DummyCache) -> None:
    """delete() removes the entry so a subsequent get() returns None."""
    await cache.set("key", "value")
    await cache.delete("key")
    assert await cache.get("key") is None


async def test_get_or_set_calls_creator_on_miss(cache: DummyCache) -> None:
    """get_or_set() awaits the creator on a cache miss and stores the result."""
    calls = 0

    async def creator() -> str:
        nonlocal calls
        calls += 1
        return "computed"

    result = await cache.get_or_set("key", creator)
    assert result == "computed"
    assert calls == 1
    assert await cache.get("key") == "computed"


async def test_get_or_set_does_not_call_creator_on_hit(cache: DummyCache) -> None:
    """get_or_set() returns the cached value without invoking creator when present."""
    await cache.set("key", "already-cached")

    async def creator() -> str:
        raise AssertionError("creator should not be called on a cache hit")

    result = await cache.get_or_set("key", creator)
    assert result == "already-cached"


async def test_get_or_set_does_not_call_creator_on_cached_none(cache: DummyCache) -> None:
    """get_or_set() treats a cached ``None`` as a hit, not a miss.

    Regression test: ``get()`` returns ``None`` for both a missing key and a
    legitimately-stored ``None`` value, so ``get_or_set()`` must not use ``is not None``
    to detect a hit -- doing so would re-invoke creator and overwrite the cache on
    every call.
    """
    await cache.set("flag", None)

    async def creator() -> str:
        raise AssertionError("creator should not be called when None is the cached value")

    result = await cache.get_or_set("flag", creator)
    assert result is None


def test_dummy_sync_cache_get_or_set_does_not_call_creator_on_cached_none(cache: DummyCache) -> None:
    """DummySyncCache.get_or_set() treats a cached ``None`` as a hit, not a miss."""
    cache.sync.set("flag", None)

    def creator() -> str:
        raise AssertionError("creator should not be called when None is the cached value")

    result = cache.sync.get_or_set("flag", creator)
    assert result is None


async def test_clear_removes_all_entries(cache: DummyCache) -> None:
    """clear() deletes all stored entries."""
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


async def test_invalidate_deletes_multiple_keys(cache: DummyCache) -> None:
    """invalidate() deletes every listed key in one operation."""
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)

    await cache.invalidate("a", "b")

    assert await cache.get("a") is None
    assert await cache.get("b") is None
    assert await cache.get("c") == 3


def test_sync_accessor_returns_dummy_sync_cache(cache: DummyCache) -> None:
    """cache.sync returns a DummySyncCache sharing the same backing store.

    Uses asyncio.run() rather than an async test function so the .sync call below
    runs outside a running event loop -- it must succeed, not trip the loop guard.
    """
    assert isinstance(cache.sync, DummySyncCache)

    asyncio.run(cache.set("key", "from-async"))
    assert cache.sync.get("key") == "from-async"


def test_dummy_sync_cache_set_and_get_round_trip() -> None:
    """DummySyncCache set()/get() work directly (sync, no running loop)."""
    store: dict[str, tuple[object, float | None]] = {}
    sync_cache = DummySyncCache(store)
    sync_cache.set("key", "value")
    assert sync_cache.get("key") == "value"


def test_dummy_sync_cache_ttl_zero_deletes(cache: DummyCache) -> None:
    """DummySyncCache set(ttl=0) deletes any existing entry and does not store."""
    cache.sync.set("key", "original")
    assert cache.sync.get("key") == "original"

    cache.sync.set("key", "new-value", ttl=0)
    assert cache.sync.get("key") is None


async def test_dummy_sync_cache_get_raises_runtime_error_from_event_loop(cache: DummyCache) -> None:
    """DummySyncCache enforces the same event-loop guard as production SyncCache."""
    with pytest.raises(RuntimeError, match="event loop"):
        cache.sync.get("key")


async def test_dummy_sync_cache_set_raises_runtime_error_from_event_loop(cache: DummyCache) -> None:
    """DummySyncCache.set() raises RuntimeError when called from inside a running event loop."""
    with pytest.raises(RuntimeError, match="event loop"):
        cache.sync.set("key", "value")
