# Design: Redesign Resource.cache

**Date:** 2026-07-16
**Status:** approved
**Scope-mode:** hold
**Research:** `design/research/2026-07-16-resource-cache-redesign/research.md`, `design/research/2026-07-16-cache-prior-art/research.md`

## Problem

`Resource.cache` returns a raw `diskcache.Cache` object with a class-scoped directory (`{data_dir}/{ClassName}/cache/`). All instances of the same Resource subclass share one SQLite database. This causes silent data cross-contamination between app instances, SQLite write contention under concurrent access, test pollution from shared state, and no TTL support. The raw `diskcache.Cache` type is about to become frozen public API at v1.0.0 — wrapping it afterward would be a breaking change.

Prior art research found that hassette uses ~5% of diskcache's surface area (get/set/delete/close) while `aiosqlite` is already a project dependency with proven patterns in `database_service.py`. A hand-rolled async cache eliminates the need for `to_thread` wrapping and removes a dependency.

## Goals

- Replace the raw `diskcache.Cache` with a typed, framework-owned cache backed by `aiosqlite` before the v1.0.0 API freeze
- Eliminate cross-instance cache contamination via instance-scoped directories
- Provide per-entry and per-resource TTL defaults so values don't persist indefinitely
- Provide a `DummyCache` for test isolation without temp directory management
- Remove `diskcache` as a dependency
- Detect cache corruption on startup and degrade gracefully

## Non-Goals

- Anti-stampede locking — the `get_or_set` interface shape supports it later, but no locking now
- In-memory LRU layer in front of disk cache
- Periodic sweep — expired entries are cleaned lazily on read (`get`/`get_or_set` check `expires_at`). No background sweep job
- Backwards compatibility — this is a clean break

## User Scenarios

### App Author: Async automation developer

- **Goal:** Cache expensive data (API responses, computed state) with automatic expiration
- **Context:** Writing a hassette App subclass with async handlers

#### Cache an API response with TTL

1. **Fetch data from external API**
   - Sees: slow API response (~2s)
   - Decides: cache the result for 1 hour
   - Then: `await self.cache.set("weather", data, ttl=3600)`

2. **Read cached data on next event**
   - Sees: cache hit returns immediately
   - Then: `result = await self.cache.get("weather")` — returns `None` after TTL expires

3. **Use get_or_set for lazy population**
   - Then: `data = await self.cache.get_or_set("weather", fetch_weather, ttl=3600)`

### App Author: Sync automation developer (AppSync)

- **Goal:** Same caching needs, from synchronous handler code
- **Context:** Writing an AppSync subclass where handlers run in a worker thread

#### Cache sensor readings synchronously

1. **Store a reading from sync handler**
   - Then: `self.cache.sync.set("temp", reading, ttl=300)`

2. **Read it back**
   - Then: `val = self.cache.sync.get("temp")`

### Framework Operator: Deployer

- **Goal:** Preserve cache data across app renames
- **Context:** Renaming an app section in `hassette.toml`

#### Rename app without losing cache

1. **Rename `[apps.weather_v1]` to `[apps.weather]` in hassette.toml**
   - Sees: cache directory was `{data_dir}/weather_v1/0/cache/`
   - Decides: set `cache_key = "weather_v1/0"` on the new section to keep the old cache
   - Then: hassette uses the explicit `cache_key` instead of the default `{app_key}/{index}`

## Functional Requirements

- **FR#1** `App.cache` returns a `CacheProtocol`-typed instance (either `AsyncCache` or `DummyCache`), not a raw `diskcache.Cache`
- **FR#2** By default, two instances of the same App subclass (same `app_key`, different `index`) get separate cache directories and separate SQLite databases. An explicit `cache_key` override (FR#13) bypasses this — instances sharing a `cache_key` share a cache intentionally
- **FR#3** `AsyncCache` exposes async methods: `get(key, default=None)`, `set(key, value, ttl=None)`, `delete(key)`, `get_or_set(key, creator, ttl=None)`, `clear()`, `invalidate(*keys)` (`invalidate` is bulk `delete` — deletes all listed keys in one operation). `clear()` runs `PRAGMA incremental_vacuum` after deleting all rows so the on-disk file actually shrinks (requires `auto_vacuum = INCREMENTAL`, set at schema creation)
- **FR#4** `AsyncCache` exposes a `sync` accessor returning a `SyncCache` with the same method signatures as plain `def` — calls stdlib `sqlite3` directly on the same database file, no event-loop involvement
- **FR#5** When `ttl=None` on `set()`, the cache uses its instance `default_ttl`. When that is also `None`, the value persists indefinitely. The full resolution chain (app class attribute → global config → `None`) is resolved once by `App.__init__` and passed to the cache constructor — the cache itself only sees a pre-resolved `default_ttl`
- **FR#6** `ttl=0` on `set()` deletes any existing entry at that key and does not store the new value
- **FR#7** Each App subclass can declare a `default_cache_ttl` class attribute to set its own TTL default
- **FR#8** `HassetteConfig` gains a `default_cache_ttl` field that serves as the global fallback
- **FR#9** `DummyCache` implements the same interface backed by an in-memory dict with TTL semantics: `set` stores `(value, expires_at)` tuples, `get` checks expiry. Constructor accepts `default_ttl: int | None = None` (same as `AsyncCache`) so test code exercises the same default-resolution behavior. Exposes a `.sync` accessor with hand-written sync methods. `initialize()` and `close()` are both no-ops
- **FR#10** `DummyCache` is injectable for test isolation — `App.__init__` accepts an optional `cache: CacheProtocol | None = None` parameter (a ready-made instance, not a factory type). When provided, `App` uses it directly instead of constructing an `AsyncCache`
- **FR#11** Async cache methods use native `aiosqlite` — no `to_thread` wrapping, no thread-pool contention
- **FR#12** During initialization, the cache detects corruption via `PRAGMA integrity_check`. On failure, it deletes the SQLite file and recreates fresh, logging a warning rather than failing the app
- **FR#13** `AppManifest` gains a `cache_key` field (default: empty string `""`). When empty, `App.cache_key` computes `{app_key}/{index}` at runtime. When set, the user's value is used as-is. The cache directory is `{data_dir}/{cache_key}/cache/`
- **FR#14** Cache shutdown is handled by `App.cleanup()` (`@final`) calling `AsyncCache.close()`, which closes all connections
- **FR#15** At config load time, the framework logs a WARNING when two manifests with different `app_key` values resolve to the same `cache_key`

## Edge Cases

- **Corrupt cache on startup**: Steps 1–3 of `AsyncCache.initialize()` (connection open, `CREATE TABLE`, `PRAGMA integrity_check`) are wrapped in a single try/except for `sqlite3.Error`. On any failure, connections are closed, the SQLite file and its `-wal`/`-shm` sidecars are deleted, and the sequence retries once from step 1 with a warning log. If the retry also fails, the exception propagates and the app fails to initialize — a second failure on a freshly-created database indicates a filesystem or permissions problem, not recoverable corruption. This covers the realistic corruption case where `sqlite3_open()` succeeds lazily but the first statement touching a b-tree page (`CREATE TABLE`) raises — not just the rare case where the file won't open at all.
- **Cache lifecycle ordering**: `App.before_initialize()` calls `await self.cache.initialize()`. This hook runs before the user's `on_initialize` code in the Resource lifecycle (`before_initialize` → `on_initialize` → `after_initialize`). The corruption check runs during `initialize()`. `AppSync.before_initialize` (currently `@final`, no `super()` call) must be updated to call `await super().before_initialize()` before its sync wrapper, so cache init fires for sync apps too.
- **`get_or_set` with async creator**: The `creator` parameter must be an async callable. The cache awaits it on miss, stores the result, and returns it. The sync `get_or_set` takes a sync callable.
- **`cache_key` collision**: Two apps can set the same `cache_key` to share a cache intentionally. A config-time WARNING alerts on unintentional collisions (different `app_key`, same resolved `cache_key`). Write contention on a shared file is the users' responsibility.
- **Multi-instance with explicit `cache_key`**: When a multi-instance app sets an explicit `cache_key`, all instances share that cache (the index is not appended). This is the user's explicit choice — FR#2's instance-scoping guarantee only applies to the default (unset `cache_key`) case.
- **Multi-instance default `cache_key` and list reorder**: The default `cache_key` (`{app_key}/{index}`) derives `index` from list position in `app_config` (`enumerate()`). Reordering, inserting, or removing entries in a multi-instance app's config list reassigns indices — and therefore cache directories — on the next restart. This is a warm-up cost (stale cache, not data loss). Set an explicit `cache_key` per instance if list order isn't stable.
- **No framework resource cache**: Cache is App-only. Framework resources (BusService, SchedulerService, etc.) do not have a `.cache` accessor. Framework services that need persistent state use the database service.
- **Concurrent async + sync access**: WAL mode allows the async (aiosqlite) and sync (sqlite3) connections to read concurrently. Writes serialize through SQLite's built-in locking with `PRAGMA busy_timeout = 5000` on all connections (matching `database_service.py`'s convention). This is the same model used by the rest of the framework.

## Acceptance Criteria

- **AC#1** (FR#1) `isinstance(app.cache, CacheProtocol)` — the attribute returns a protocol-conforming instance, not raw diskcache
- **AC#2** (FR#2) Two instances of a test App subclass with different indices produce different cache directory paths
- **AC#3** (FR#3) All async interface methods (`get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`) exist and are callable
- **AC#4** (FR#4) `cache.sync` accessor returns a `SyncCache` with matching method signatures. Calling `.sync.get()` from inside a running event loop raises `RuntimeError` (loop-safety guard matching other sync facades)
- **AC#5** (FR#5, FR#6) `set(key, value, ttl=None)` falls back to the instance's pre-resolved `default_ttl`; `set(key, value, ttl=0)` deletes any existing entry and does not store
- **AC#6** (FR#9, FR#10) `DummyCache` injected via test infrastructure makes `app.cache` return it — `set` stores in-memory with TTL, `get` returns `None` for expired entries, `.sync` accessor works
- **AC#7** (FR#12) An app with a corrupt cache directory initializes successfully — integrity check detects corruption, file is recreated, warning logged
- **AC#8** (FR#13) An `AppManifest` with `cache_key = "custom"` produces cache directory `{data_dir}/custom/cache/`
- **AC#9** (FR#13) An `AppManifest` without `cache_key` defaults to `{app_key}/{index}` — e.g., `{data_dir}/weather/0/cache/`
- **AC#10** (FR#14) `AsyncCache.close()` closes all connections — App calls it during shutdown (verifiable via unit test)
- **AC#11** Existing unit tests in `test_resource_properties.py` and `test_shutdown_edge_cases.py` are updated and pass
- **AC#12** `prek -a && prek pyright -a --stage pre-push` (ruff + pyright) passes with no new errors
- **AC#13** Cache docs pages rewritten for the new async API
- **AC#14** Example app `examples/cover_scheduler.py` updated to use the new cache API
- **AC#15** (FR#15) Config-time WARNING logged when two manifests resolve to the same `cache_key` with different `app_key` values
- **AC#16** `diskcache` removed from `pyproject.toml` dependencies
- **AC#17** (FR#7) An App subclass with `default_cache_ttl = 60` uses that value as the default TTL when no per-call `ttl` is specified
- **AC#18** (FR#8) `HassetteConfig.default_cache_ttl = 120` is used as the fallback when the App subclass does not declare `default_cache_ttl`
- **AC#19** (FR#11) `AsyncCache` data methods use native `aiosqlite` — no `to_thread` calls in the cache package
- **AC#20** `Resource` base class no longer exposes a `cache` property or `_cache` attribute — `hasattr(resource, 'cache')` is `False` for non-App Resources
- **AC#21** (FR#13) `AppManifest.cache_key` rejects framework-reserved prefixes via `is_framework_key()` validator — setting `cache_key` to `__hassette__` or a `__hassette__.`-prefixed value raises a validation error. Note: `is_framework_key()` uses dot-prefixed matching; cache keys use `/` separators, so `__hassette__/foo` would not be caught — this is acceptable since the exact key `__hassette__` and dotted prefixes cover the real reservation

## Key Constraints

- Do not use `diskcache` — the cache is backed by `aiosqlite`/`sqlite3` directly. Remove `diskcache` as a dependency.
- Do not use `unique_id` for cache directory scoping — it is random per restart and would orphan data
- Do not add `__getitem__`/`__setitem__`/`__contains__` — the clean break removes dict-style access in favor of explicit async/sync methods
- `SyncCache` is hand-written (not codegen-generated) — it uses stdlib `sqlite3` directly, not `run_sync` through the event loop. Opens a fresh connection per method call (no shared connection, trivially thread-safe for the multi-worker `AppSync` thread pool). Include an `asyncio.get_running_loop()` guard that raises `RuntimeError` if called from async code, matching the safety contract of other sync facades.

## Dependencies and Assumptions

- `aiosqlite>=0.20` (already a dependency — used by `database_service.py` and telemetry)
- `diskcache` is **removed** as a dependency
- Assumes `cache_key` on `AppManifest` flows to `App.__init__` and is accessible on the `App` instance for cache directory construction

## Architecture

### New package: `src/hassette/cache/`

**`protocol.py`** — Runtime-checkable `CacheProtocol` defining the async cache interface (`async def initialize`, `async def get`, `async def set`, `async def close`, etc.). Satisfied by `AsyncCache` and `DummyCache`. `SyncCache` and `DummySyncCache` do not satisfy it — they expose sync methods and are accessed via `.sync`, never used polymorphically. Uses `@runtime_checkable` for `isinstance()` checks in tests.

**`_helpers.py`** — Module-level free functions and constants shared by `AsyncCache` and `SyncCache`. Neither class inherits from a shared base — they import and call these directly:
- `SCHEMA_DDL` — `PRAGMA auto_vacuum = INCREMENTAL` (before table creation) + `CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires_at REAL)`
- `resolve_ttl(ttl, default_ttl)` — per-call `ttl` → instance `default_ttl` → `None` (persist indefinitely). Does not reference `hassette.config` — the class-attribute/global-config chain is resolved by `App.__init__` and passed as a single `default_ttl` to the constructor
- `serialize(value)` / `deserialize(blob, key)` — Pickle serialization/deserialization. `deserialize()` catches `pickle.UnpicklingError`, `AttributeError`, `ModuleNotFoundError`, and `EOFError` — logs a warning with the key name and returns `None` (caller treats as miss, deletes the stale row). This extends FR#12's "degrade gracefully" philosophy to the per-entry level: a cached class that was renamed, moved, or had its fields changed between restarts produces a miss, not a crash
- `validate_key(key)` — key validation

**`wrapper.py`** — `AsyncCache`. The primary async implementation. A plain class (not a `Resource`) — App creates it and manages its lifecycle explicitly. Constructor: `AsyncCache(db_path: Path, default_ttl: int | None = None)`. `App.__init__` passes `db_path` (built from `{data_dir}/{cache_key}/cache/cache.db`) and `default_ttl` (resolved from `cls.default_cache_ttl` or `hassette.config.default_cache_ttl`). Uses two `aiosqlite` connections (read/write pair) in WAL mode, matching the pattern in `database_service.py`.

`async initialize()`:
1. Opens read and write `aiosqlite` connections in WAL mode, sets `PRAGMA busy_timeout = 5000` on each (matching `database_service.py`'s `_BUSY_TIMEOUT_MS` convention)
2. Runs `CREATE TABLE IF NOT EXISTS`
3. Runs `PRAGMA integrity_check`
4. Creates `self.sync = SyncCache(self.db_path, self.default_ttl)` — a `SyncCache` pointing at the same file

Steps 1–3 are wrapped in a single try/except for `sqlite3.Error`. On any failure (whether at connect, schema creation, or integrity check), connections are closed, the SQLite file and its `-wal`/`-shm` sidecars are deleted, and the sequence retries once from step 1 with a warning log. If the retry also fails, the exception propagates — the app fails to initialize. This is the correct behavior: a second failure on a freshly-created database indicates a filesystem or permissions problem, not recoverable corruption. This covers the realistic corruption case where `sqlite3_open()` succeeds lazily but the first DDL statement raises.

All data methods (`get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`) are native `async def` using `aiosqlite`. No `to_thread`.

`async close()` closes both `aiosqlite` connections. `SyncCache` has no long-lived connection to close.

**`sync.py`** — `SyncCache`. Hand-written sync implementation using stdlib `sqlite3`. Opens a fresh `sqlite3` connection per method call (connect → execute → close) — no shared connection, trivially thread-safe without locks. Each connection sets WAL mode and `PRAGMA busy_timeout = 5000` (matching `database_service.py`'s convention). The per-call connection cost is negligible for a local-file cache that isn't a hot path. Every public method starts with an `asyncio.get_running_loop()` guard that raises `RuntimeError` if called from inside an event loop — matching the safety contract of `ApiSyncFacade`/`BusSyncFacade`/`SchedulerSyncFacade`.

Not a `Resource` — it's a plain object owned by `AsyncCache`, created during `initialize()`. Callers access it via `self.cache.sync.get(key)`. No `close()` needed since there is no long-lived connection to clean up.

**`dummy.py`** — `DummyCache`. In-memory dict-backed implementation for tests. Stores `(value, expires_at)` tuples so TTL semantics match production — `get` returns `None` for expired entries. `close()` is a no-op. Exposes `.sync` as a hand-written `DummySyncCache` with the same dict-backed behavior (trivial — no codegen, no thread-hop). `DummySyncCache` enforces the same `asyncio.get_running_loop()` guard as production `SyncCache` — test code calling `.sync` from async context raises `RuntimeError` in both real and dummy implementations.

**`__init__.py`** — Exports `AsyncCache`, `SyncCache`, `DummyCache`, `DummySyncCache`, `CacheProtocol`. None of these are `Resource` subclasses — they are all plain classes.

### Cache directory layout

```
{data_dir}/
├── weather/0/cache/cache.db    # App "weather", instance 0
├── weather/1/cache/cache.db    # App "weather", instance 1
├── shared-weather/cache/cache.db  # App with cache_key="shared-weather" (user override)
```

The directory is `{data_dir}/{cache_key}/cache/`. The SQLite file is `cache.db` within that directory. Cache is App-only — framework Resources do not have a `.cache` accessor. The `cache_key` defaults to `{app_key}/{index}`. Overridable via `cache_key` field on `AppManifest` — when set, the user's value is used as-is (no index appended).

### Changes to `Resource` (base.py)

Remove the `cache` property, `_cache` attribute, `diskcache` import, and the cache-close logic from `cleanup()`. Cache moves to `App` only.

### Changes to `App` (app.py)

Add `self.cache` in `App.__init__`. The constructor accepts an optional `cache: CacheProtocol | None = None` parameter (FR#10). When provided (test injection), `App` uses it directly — no `AsyncCache` is constructed and `before_initialize` skips cache initialization. When `None` (default/production), `App` constructs `AsyncCache(db_path, default_ttl)`. Unlike `api`, `bus`, `scheduler`, `states` (which are Resource children via `add_child`), cache is a plain object — App manages its lifecycle explicitly:
- **Init:** `App.before_initialize()` calls `await self.cache.initialize()` when `self.cache` is an `AsyncCache` (not injected). When a `DummyCache` was injected via the constructor (FR#10), `before_initialize` skips initialization — `DummyCache.initialize()` is a no-op, but the guard avoids the call entirely for clarity. This runs before the user's `on_initialize` hook, so cache is ready when user code runs. `before_initialize` is not `@final`, but it is the framework's setup slot (docstring: "prepare to accept new work, allocate sockets, queues, temp files") — users override `on_initialize`, not `before_initialize`. `AppSync.before_initialize` (currently `@final`, calls `run_in_thread(self.before_initialize_sync)` without `super()`) must be updated to call `await super().before_initialize()` first, so cache init fires for sync apps.
- **Close:** `App.cleanup()` (`@final`, not overridable by subclasses) calls `await super().cleanup()` first (which cancels the task bucket and awaits in-flight tasks), then `await self.cache.close()`. This ordering ensures no in-flight app task hits a closed database during shutdown — matching `DatabaseService.on_shutdown()`'s convention of drain-first, close-connections-last.

New class attribute: `default_cache_ttl: ClassVar[int | None] = None`. App subclasses can set this to override the global default.

New property: `cache_key` — returns `self.app_manifest.cache_key` if the manifest exists and `cache_key` is explicitly set, otherwise `f"{self.app_key}/{self.index}"`. When `app_manifest is None` (e.g., test-constructed App instances), the fallback applies.

### Changes to `AppManifest` (config/classes.py)

New field: `cache_key: str = ""`. When empty, the `App.cache_key` property computes the default as `f"{self.app_key}/{self.index}"`. Validated: a new `field_validator` using `is_framework_key()` rejects framework-reserved prefixes.

### Changes to `HassetteConfig` (config/config.py)

New field: `default_cache_ttl: int | None = None`. Global fallback TTL in seconds. `None` means persist indefinitely.

Remove field: `default_cache_size` and its backing constant `DEFAULT_CACHE_SIZE_BYTES` — no longer applicable. The old field sized the `diskcache.Cache`; the new cache has no size limit. Cache grows unbounded; users call `clear()` to reclaim disk space.

Config-load-time duplicate `cache_key` check: after assembling all manifests, compute resolved `cache_key` for each and log WARNING when different `app_key` values collide on the same `cache_key`.

### `get_or_set` design

```python
async def get_or_set(
    self, key: str, creator: Callable[[], Awaitable[T]], ttl: int | None = None
) -> T:
```

The async `creator` is awaited on cache miss. The sync variant on `SyncCache` takes a sync callable. Both store the result and return it.

### Cleanup

`App.cleanup()` (`@final`) calls `await super().cleanup()` first (task-bucket cancellation, child resource shutdown), then `await self.cache.close()`, which closes both `aiosqlite` connections. `SyncCache` has no long-lived connection to close. This ordering ensures in-flight tasks complete before the cache connections close. The try/except error-swallowing pattern is preserved. `cleanup()` is used instead of `on_shutdown` because it is `@final` — subclass overrides cannot skip it.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions. Use `@runtime_checkable Protocol` (not ABC) for the cache interface.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `Resource.cache` property + `_cache` attribute + diskcache import (base.py) | `App.cache` (`AsyncCache`, plain class) | Remove from base.py |
| `Resource.cleanup()` cache-close logic (base.py:567-571) | `AsyncCache.close()` handles its own connections | Remove from Resource.cleanup() |
| `diskcache` dependency (pyproject.toml) | Hand-rolled aiosqlite/sqlite3 backend | Remove from dependencies |
| Cache docs promising "full diskcache API" (index.md, patterns.md, all snippets) | New docs for typed async/sync API | Full rewrite |
| Example app dict-style cache access (cover_scheduler.py) | Async cache method calls | Update call sites |

## Migration

No data migration required. Existing cache data at `{data_dir}/{ClassName}/cache/` (diskcache format) is incompatible with the new aiosqlite schema and becomes orphaned. This is acceptable for a cache — warm-up cost, not data loss. Users who need to preserve state across the upgrade should export values before upgrading.

## Convention Examples

### aiosqlite connection pair (WAL mode)

**Source:** `src/hassette/core/database_service.py:224-229`

```python
self._db = await _connect_daemon(self._db_path, isolation_level=None)
self._db.row_factory = aiosqlite.Row
self._read_db = await _connect_daemon(self._db_path, isolation_level=None)
```

### Health check pattern

**Source:** `src/hassette/core/telemetry/query_service.py:83-86`

```python
async def check_health(self) -> None:
    async with self.execute("SELECT 1") as cursor:
        await cursor.fetchone()
```

### DummyCache injection for tests

Tests inject `DummyCache` via test infrastructure so `app.cache` returns an in-memory implementation. This replaces the old `resource._cache = preset` pattern (which relied on `_cache` on `Resource` — now removed).

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

## Alternatives Considered

**Keep diskcache, wrap in `to_thread`.** The ecosystem's pragmatic default. Rejected because hassette uses ~5% of diskcache's surface area, `aiosqlite` is already a dependency with proven patterns, and `to_thread` wrapping adds thread-pool contention.

**Single async class + codegen sync facade.** Generate `CacheSyncFacade` via codegen like api/bus/scheduler. Rejected because cache I/O is pure disk — a sync version using stdlib `sqlite3` is equally valid and avoids two unnecessary thread hops per call (`worker thread → event loop → aiosqlite thread → SQLite` vs `worker thread → sqlite3 → SQLite`).

**cashews with `disk://` backend.** Async cache framework wrapping diskcache. Rejected — same thread-pool issues as raw diskcache, plus an additional dependency.

**Namespace-prefixed keys in shared cache.** All instances share one SQLite database but prefix keys. Rejected — shared eviction pool, no per-resource size limits, write contention remains.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/resources/test_resource_properties.py` — `TestCache` class (3 tests): remove entirely (cache no longer on Resource base) or move to a new test file for App.cache
- `tests/unit/resources/test_shutdown_edge_cases.py` — `test_cleanup_closes_present_cache` and `test_cleanup_swallows_cache_close_exception` (2 tests): remove cache-close tests from Resource shutdown (cache cleanup is now AsyncCache's own responsibility)

### New Test Coverage

- **Unit: cache helpers** — TTL resolution, pickle round-trip (including deserialization failure → warning + miss), key validation. New file: `tests/unit/cache/test_helpers.py`
- **Unit: AsyncCache** (FR#3, FR#11) — async get/set/delete/get_or_set/clear/invalidate, native aiosqlite calls. New file: `tests/unit/cache/test_async_cache.py`
- **Unit: SyncCache** (FR#4) — sync get/set/delete, loop-safety guard raises RuntimeError from async context. New file: `tests/unit/cache/test_sync_cache.py`
- **Unit: DummyCache** (FR#9) — set stores with TTL, get returns None for expired, .sync accessor works. New file: `tests/unit/cache/test_dummy.py`
- **Unit: Instance-scoped directories** (FR#2) — two App instances with different indices get different directories
- **Unit: cache_key from manifest** (FR#13) — AppManifest with/without explicit `cache_key`, verify directory path
- **Unit: Corruption handling** (FR#12) — corrupt SQLite file, verify warning logged and file recreated
- **Unit: ttl=0 semantics** (FR#6) — set with ttl=0 deletes existing entry
- **Unit: Cache key collision warning** (FR#15) — two manifests with same resolved cache_key, different app_key
- **Unit: cache_key framework prefix rejection** (FR#13) — AppManifest with a framework-reserved `cache_key` prefix raises ValidationError

### Pyright Probes

- `tests/pyright_probes/forgotten_await_probe.py` — extend with `AsyncCache` method calls (`cache.get()`, `cache.set()`, `cache.get_or_set()`) to verify pyright catches un-awaited cache operations. The probe's `pyrightconfig.json` already enables `reportUnusedCoroutine: error` — no config changes needed

### Tests to Remove

- Cache-related tests from `test_resource_properties.py` and `test_shutdown_edge_cases.py` (cache is no longer on Resource base)

## Documentation Updates

- `docs/pages/core-concepts/cache/index.md` — full rewrite: document AsyncCache/SyncCache API, instance-scoped directories, TTL configuration, DummyCache
- `docs/pages/core-concepts/cache/patterns.md` — full rewrite: all patterns updated for async/sync API
- `docs/pages/core-concepts/cache/snippets/cache_basic_usage.py` — async get/set examples
- `docs/pages/core-concepts/cache/snippets/cache_expire.py` — rewrite for TTL semantics
- `docs/pages/core-concepts/cache/snippets/cache_expiring.py` — TTL with app default
- **Delete** `docs/pages/core-concepts/cache/snippets/cache_instance_prefix.py` — no longer needed
- `docs/pages/core-concepts/cache/snippets/cache_api_response.py` — async API caching
- `docs/pages/core-concepts/cache/snippets/cache_complex_data.py` — async with Pydantic models
- `docs/pages/core-concepts/cache/snippets/cache_counter.py` — async counter pattern
- `docs/pages/core-concepts/cache/snippets/cache_performance.py` — async load-once/write-on-shutdown
- `docs/pages/core-concepts/cache/snippets/cache_rate_limit.py` — async rate limiting
- `examples/cover_scheduler.py` — update cache call sites to async API

## Impact

### Changed Files

- **Create** `src/hassette/cache/__init__.py` — package exports
- **Create** `src/hassette/cache/protocol.py` — CacheProtocol
- **Create** `src/hassette/cache/_helpers.py` — shared free functions (resolve_ttl, serialize, deserialize, validate_key) and SCHEMA_DDL constant
- **Create** `src/hassette/cache/wrapper.py` — AsyncCache
- **Create** `src/hassette/cache/sync.py` — SyncCache (fresh connection per call, no shared state)
- **Create** `src/hassette/cache/dummy.py` — DummyCache + DummySyncCache
- **Modify** `src/hassette/resources/base.py` — remove cache property, _cache attribute, diskcache import, cache-close in cleanup()
- **Modify** `src/hassette/app/app.py` — create AsyncCache in __init__ (with optional `cache` injection parameter), manage lifecycle in before_initialize/cleanup, add cache_key property, default_cache_ttl class attribute; update `AppSync.before_initialize` to call `super()` so cache init fires for sync apps; update `cleanup()` docstring (currently references cache-closing in pre-existing sense)
- **Modify** `src/hassette/config/classes.py` — add cache_key field to AppManifest with field_validator
- **Modify** `src/hassette/config/config.py` — add default_cache_ttl field, remove default_cache_size field, cache_key collision check
- **Modify** `pyproject.toml` — remove `diskcache>=5.6.3` from dependencies
- **Modify** `src/hassette/test_utils/` — add DummyCache fixture or factory
- **Modify** `src/hassette/test_utils/mock_hassette.py` — remove `default_cache_size` kwarg from `make_ws_hassette_stub()` (the removed config field is passed to `make_mock_hassette()` inside this function; `HassetteConfig` has `extra="allow"` so deletion would silently absorb the kwarg without error)
- **Create** `tests/unit/cache/__init__.py`
- **Create** `tests/unit/cache/test_helpers.py`
- **Create** `tests/unit/cache/test_async_cache.py`
- **Create** `tests/unit/cache/test_sync_cache.py`
- **Create** `tests/unit/cache/test_dummy.py`
- **Modify** `tests/unit/resources/test_resource_properties.py` — remove TestCache
- **Modify** `tests/unit/resources/test_shutdown_edge_cases.py` — remove cache-close tests
- **Modify** `tests/pyright_probes/forgotten_await_probe.py` — add AsyncCache probe cases for un-awaited cache method calls
- **Modify** `docs/pages/core-concepts/cache/index.md` — full rewrite
- **Modify** `docs/pages/core-concepts/cache/patterns.md` — full rewrite
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_basic_usage.py` — async get/set examples
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_expire.py` — TTL semantics
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_expiring.py` — TTL with app default
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_api_response.py` — async API caching
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_complex_data.py` — async with Pydantic models
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_counter.py` — async counter pattern
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_performance.py` — async load-once/write-on-shutdown
- **Modify** `docs/pages/core-concepts/cache/snippets/cache_rate_limit.py` — async rate limiting
- **Delete** `docs/pages/core-concepts/cache/snippets/cache_instance_prefix.py` — no longer needed
- **Modify** `examples/cover_scheduler.py` — async cache calls

### Behavioral Invariants

- Framework Resources (BusService, SchedulerService, etc.) must not gain a `.cache` accessor — cache is App-only
- `AsyncCache.close()` must swallow connection close exceptions and log them
- No cache class is a `Resource` subclass — all are plain classes with explicit lifecycle management
- DummyCache injection must work via test fixtures for App instances that need cache isolation

### Blast Radius

- All user apps that use `self.cache` — their code changes (dict-style access removed, async required). Intentional clean break.
- Example apps in `examples/` — must be updated
- Docs cache pages — full rewrite
- No framework services use cache data methods — framework internals are unaffected
- `diskcache` removed as a dependency — any user code importing diskcache directly would break, but framework code never does

<!-- Gap check 2026-07-16: 2 gaps included — docs/pages/core-concepts/apps/index.md:3,148 (cache description) → T04 Focus, docs/pages/migration/concepts.md:37 (cache concepts row) → T04 Focus -->

## Open Questions

None — all design questions resolved during discovery and challenge.
