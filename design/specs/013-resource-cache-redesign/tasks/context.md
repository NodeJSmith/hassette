# Context: Redesign Resource.cache

## Problem & Motivation

`Resource.cache` returns a raw `diskcache.Cache` object with a class-scoped directory (`{data_dir}/{ClassName}/cache/`). All instances of the same Resource subclass share one SQLite database, causing silent data cross-contamination between app instances, SQLite write contention under concurrent access, test pollution from shared state, and no TTL support. The raw `diskcache.Cache` type is about to become frozen public API at v1.0.0 — wrapping it afterward would be a breaking change. Prior art research found that hassette uses ~5% of diskcache's surface area (get/set/delete/close) while `aiosqlite` is already a project dependency with proven patterns in `database_service.py`. A hand-rolled async cache eliminates the need for `to_thread` wrapping and removes a dependency.

## Visual Artifacts

None.

## Key Decisions

1. **aiosqlite/sqlite3 backend instead of diskcache** — hassette uses only get/set/delete/close of diskcache. aiosqlite is already a dependency with proven patterns in database_service.py. Eliminates `to_thread` wrapping and thread-pool contention.
2. **Hand-written SyncCache using stdlib sqlite3** — a sync version using stdlib sqlite3 is equally valid and avoids two unnecessary thread hops per call (`worker thread → event loop → aiosqlite thread → SQLite` vs `worker thread → sqlite3 → SQLite`). Opens a fresh connection per call for trivial thread-safety.
3. **Free functions in _helpers.py instead of a shared base class** — AsyncCache and SyncCache share DDL/TTL/pickle/validation logic via module-level free functions, not inheritance. async/sync makes direct inheritance awkward.
4. **Instance-scoped cache directories** — default `cache_key` is `{app_key}/{index}`, giving each app instance its own SQLite database. Eliminates cross-instance contamination.
5. **Cache is App-only, not on Resource** — framework Resources use the database service for persistent state. Cache moves from the Resource base to App exclusively.
6. **DummyCache injection via constructor parameter** — `App.__init__` accepts `cache: CacheProtocol | None = None` for test isolation. When provided, App uses it directly.
7. **Corruption recovery with single retry** — initialize() wraps connect + DDL + integrity_check in try/except. On failure, deletes the file and sidecars, retries once. If retry fails, the exception propagates (filesystem/permissions problem, not recoverable corruption).

## Constraints & Anti-Patterns

- Do NOT use `diskcache` — the cache is backed by aiosqlite/sqlite3 directly
- Do NOT use `unique_id` for cache directory scoping — it is random per restart and would orphan data
- Do NOT add `__getitem__`/`__setitem__`/`__contains__` — clean break removes dict-style access
- Do NOT add anti-stampede locking, in-memory LRU layer, periodic sweep, or backwards compatibility — all explicit Non-goals
- SyncCache must NOT use `run_sync` through the event loop — uses stdlib sqlite3 directly
- SyncCache methods must include an `asyncio.get_running_loop()` guard that raises RuntimeError if called from async code
- No cache class is a Resource subclass — all are plain classes with explicit lifecycle management
- Framework Resources must not gain a `.cache` accessor — cache is App-only

## Design Doc References

- `## Problem` — what's broken with the current diskcache approach
- `## Functional Requirements` — FR#1–FR#15 defining the cache interface, TTL, injection, lifecycle
- `## Edge Cases` — corruption handling, lifecycle ordering, concurrent access, cache_key collision
- `## Architecture` — new cache package structure, changes to App/Resource/Config
- `## Convention Examples` — aiosqlite connection pair, health check, sync facade guard patterns
- `## Replacement Targets` — what gets removed (Resource.cache, diskcache dep, old docs)
- `## Test Strategy` — existing tests to adapt, new coverage, tests to remove, pyright probes
- `## Documentation Updates` — cache docs rewrite, snippet changes

## Convention Examples

### aiosqlite connection pair (WAL mode)

**Source:** `src/hassette/core/database_service.py:224-229`

```python
self._db = await _connect_daemon(self._db_path, isolation_level=None)
self._db.row_factory = aiosqlite.Row
self._read_db = await _connect_daemon(self._db_path, isolation_level=None)
```

### Sync facade loop-safety guard

**Adapted from:** `src/hassette/task_bucket/task_bucket.py:306-315`

```python
try:
    asyncio.get_running_loop()
except RuntimeError:
    pass
else:
    raise RuntimeError(
        f"This sync method ({label}) was called from within an event loop. "
        "Use the async method instead."
    )
```

### DummyCache injection for tests

Tests inject `DummyCache` via test infrastructure so `app.cache` returns an in-memory implementation. This replaces the old `resource._cache = preset` pattern (which relied on `_cache` on `Resource` — now removed).
