"""Unit tests for hassette.cache.sync.SyncCache."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from hassette.cache.sync import SyncCache
from hassette.cache.wrapper import AsyncCache


@pytest.fixture
async def async_cache(tmp_path: Path) -> AsyncIterator[AsyncCache]:
    """A real AsyncCache, initialized so the cache_entries schema exists on disk.

    SyncCache does not create schema itself (that's AsyncCache.initialize()'s job) --
    tests exercise it via the .sync accessor of an initialized AsyncCache.
    """
    db_path = tmp_path / "cache.db"
    instance = AsyncCache(db_path, default_ttl=None)
    await instance.initialize()
    try:
        yield instance
    finally:
        await instance.close()


@pytest.fixture
def sync_cache(async_cache: AsyncCache) -> SyncCache:
    """The SyncCache facade of an initialized AsyncCache."""
    assert async_cache.sync is not None
    return async_cache.sync


def test_set_and_get_round_trip(sync_cache: SyncCache) -> None:
    """A value stored via set() is returned unchanged by get()."""
    sync_cache.set("greeting", {"text": "hello"})
    assert sync_cache.get("greeting") == {"text": "hello"}


def test_get_returns_default_when_missing(sync_cache: SyncCache) -> None:
    """get() returns the provided default when the key doesn't exist."""
    assert sync_cache.get("missing", default="fallback") == "fallback"
    assert sync_cache.get("missing") is None


def test_get_returns_stored_none_without_deleting_entry(sync_cache: SyncCache) -> None:
    """A cached ``None`` value round-trips as ``None``, not the default, and isn't evicted.

    Regression test: deserialize() must distinguish a legitimately-stored ``None`` from
    a failed unpickle -- otherwise get() would mistake the former for corruption and
    delete a perfectly valid entry.
    """
    sync_cache.set("flag", None)
    assert sync_cache.get("flag", default="fallback") is None
    # A second get() confirms the first call did not delete the row as if it were corrupt.
    assert sync_cache.get("flag", default="fallback") is None


def test_set_ttl_zero_deletes_existing_and_does_not_store(sync_cache: SyncCache) -> None:
    """set(key, value, ttl=0) deletes any existing entry and does not store the new value."""
    sync_cache.set("key", "original")
    assert sync_cache.get("key") == "original"

    sync_cache.set("key", "new-value", ttl=0)
    assert sync_cache.get("key") is None


def test_delete_removes_entry(sync_cache: SyncCache) -> None:
    """delete() removes the entry so a subsequent get() returns None."""
    sync_cache.set("key", "value")
    sync_cache.delete("key")
    assert sync_cache.get("key") is None


def test_get_or_set_calls_creator_on_miss(sync_cache: SyncCache) -> None:
    """get_or_set() calls the sync creator on a miss and stores the result."""
    calls = 0

    def creator() -> str:
        nonlocal calls
        calls += 1
        return "computed"

    result = sync_cache.get_or_set("key", creator)
    assert result == "computed"
    assert calls == 1
    assert sync_cache.get("key") == "computed"


def test_get_or_set_does_not_call_creator_on_hit(sync_cache: SyncCache) -> None:
    """get_or_set() returns the cached value without invoking creator when present."""
    sync_cache.set("key", "already-cached")

    def creator() -> str:
        raise AssertionError("creator should not be called on a cache hit")

    result = sync_cache.get_or_set("key", creator)
    assert result == "already-cached"


def test_get_or_set_does_not_call_creator_on_cached_none(sync_cache: SyncCache) -> None:
    """get_or_set() treats a cached ``None`` as a hit, not a miss.

    Regression test: ``get()`` returns ``None`` for both a missing key and a
    legitimately-stored ``None`` value, so ``get_or_set()`` must not use ``is not None``
    to detect a hit -- doing so would re-invoke creator and overwrite the cache on
    every call.
    """
    sync_cache.set("flag", None)

    def creator() -> str:
        raise AssertionError("creator should not be called when None is the cached value")

    result = sync_cache.get_or_set("flag", creator)
    assert result is None


def test_clear_removes_all_entries(sync_cache: SyncCache) -> None:
    """clear() deletes all stored entries."""
    sync_cache.set("a", 1)
    sync_cache.set("b", 2)
    sync_cache.clear()
    assert sync_cache.get("a") is None
    assert sync_cache.get("b") is None


def test_invalidate_deletes_multiple_keys(sync_cache: SyncCache) -> None:
    """invalidate() deletes every listed key in one operation."""
    sync_cache.set("a", 1)
    sync_cache.set("b", 2)
    sync_cache.set("c", 3)

    sync_cache.invalidate("a", "b")

    assert sync_cache.get("a") is None
    assert sync_cache.get("b") is None
    assert sync_cache.get("c") == 3


async def test_get_raises_runtime_error_from_event_loop(sync_cache: SyncCache) -> None:
    """Calling a SyncCache method from inside a running event loop raises RuntimeError."""
    with pytest.raises(RuntimeError, match="event loop"):
        sync_cache.get("key")


async def test_set_raises_runtime_error_from_event_loop(sync_cache: SyncCache) -> None:
    """set() raises RuntimeError when called from inside a running event loop."""
    with pytest.raises(RuntimeError, match="event loop"):
        sync_cache.set("key", "value")


async def test_delete_raises_runtime_error_from_event_loop(sync_cache: SyncCache) -> None:
    """delete() raises RuntimeError when called from inside a running event loop."""
    with pytest.raises(RuntimeError, match="event loop"):
        sync_cache.delete("key")


async def test_clear_raises_runtime_error_from_event_loop(sync_cache: SyncCache) -> None:
    """clear() raises RuntimeError when called from inside a running event loop."""
    with pytest.raises(RuntimeError, match="event loop"):
        sync_cache.clear()


async def test_invalidate_raises_runtime_error_from_event_loop(sync_cache: SyncCache) -> None:
    """invalidate() raises RuntimeError when called from inside a running event loop."""
    with pytest.raises(RuntimeError, match="event loop"):
        sync_cache.invalidate("key")


async def test_get_or_set_raises_runtime_error_from_event_loop(sync_cache: SyncCache) -> None:
    """get_or_set() raises RuntimeError when called from inside a running event loop."""
    with pytest.raises(RuntimeError, match="event loop"):
        sync_cache.get_or_set("key", lambda: "value")
