---
topic: "Async-native persistent disk cache alternatives to diskcache"
date: 2026-07-16
status: Draft
---

# Prior Art: Async-Native Persistent Disk Cache Alternatives

## The Problem

Hassette wraps `diskcache.Cache` (synchronous `sqlite3` under the hood) for persistent per-app caching with TTL. Every cache operation must be wrapped in `asyncio.to_thread` to avoid blocking the event loop. Before freezing this as the v1.0 API, the question is whether diskcache is the right foundation — or whether a simpler, async-native alternative would eliminate the thread-pool wrapping entirely.

## How We Do It Today

`Resource.cache` lazily constructs a `diskcache.Cache(directory, size_limit=...)`. The framework calls only `Cache()` and `.close()` — no `get`, `set`, `delete`, or any data method appears in framework source. User-facing usage is limited to `get`, `set`, dict-style access, `expire=`, and `del`. None of diskcache's advanced features (tags, FanoutCache sharding, Deque/Index structures, memoization decorators, multi-process locking, eviction policies) are used anywhere. `aiosqlite>=0.20` is already a project dependency (used by `database_service.py` and telemetry).

## Patterns Found

### Pattern 1: Sync SQLite Cache Wrapped in a Thread-Pool Executor

**Used by**: diskcache (official recommendation), cashews' `disk://` backend
**How it works**: Keep synchronous `sqlite3`-based diskcache, wrap every call in `run_in_executor` or `to_thread`. Libraries like cashews do this wrapping behind an async decorator API. The storage engine's data guarantees (ACID, size limits, eviction) stay intact.
**Strengths**: Zero risk of reinventing SQLite locking; inherits diskcache's mature feature set for free; minimal code to write.
**Weaknesses**: Every cache op consumes a thread-pool worker; transactions serialize writes to the same cache under concurrent fan-out; adds a dependency whose surface area is ~5% used.
**Example**: https://grantjenks.com/docs/diskcache/tutorial.html (executor pattern); https://github.com/Krukov/cashews

### Pattern 2: True Async I/O via `aiosqlite`

**Used by**: aiohttp-client-cache (`backends/sqlite.py`), Privex `AsyncSqliteCache`, the unimplemented diskcache `AsyncCache` proposal (issue #282)
**How it works**: Replace stdlib `sqlite3` with `aiosqlite`. Schema: `(key TEXT PRIMARY KEY, value BLOB, expires_at REAL)`. `get` does `SELECT` with expiry check, `set` does `INSERT OR REPLACE`, `delete` does `DELETE`. TTL enforced lazily (check-on-read) or via periodic sweep. `aiosqlite` itself runs one background thread per connection, but calling code never blocks the event loop.
**Strengths**: No thread-pool contention from the caller's perspective; simple auditable schema; single file, single process, no external services.
**Weaknesses**: No polished general-purpose library ships this exact pattern — aiohttp-client-cache is HTTP-response-shaped, Privex is niche. Vacuuming/growth management is left to the implementer.
**Example**: https://aiohttp-client-cache.readthedocs.io/en/v0.3/modules/aiohttp_client_cache.backends.sqlite.html

### Pattern 3: Hand-Rolled Minimal aiosqlite Cache

**Used by**: Implied by diskcache issue #282's design; LiteCache (sync, Python); cache-sqlite-lru-ttl (TypeScript, TTL+LRU combo)
**How it works**: Purpose-built module: one SQLite file, one table, three verbs (`get`, `set`, `delete`), each `async def` using `aiosqlite`. TTL stored as absolute expiry timestamp, checked at read time. Optional periodic sweep and LRU/size cap.
**Strengths**: Smallest surface area — no unused features. Single dependency (`aiosqlite`, already in the project). Fully auditable. No thread pool needed at all.
**Weaknesses**: You own correctness for concurrent-writer races, schema migrations, and vacuuming. No mature library ships this shape for Python.
**Example**: https://github.com/grantjenks/python-diskcache/issues/282 (design, never built); https://github.com/colingrady/LiteCache (sync Python reference)

### Pattern 4: JSON-File-Backed Store (Home Assistant idiom)

**Used by**: Home Assistant core (`helpers.storage.Store`)
**How it works**: One JSON file per logical store, atomic writes, debounced coalesced saves. No TTL — expiry is modeled by storing timestamps and checking in application code.
**Strengths**: Zero SQLite dependency, trivially inspectable, battle-tested at HA scale.
**Weaknesses**: No built-in TTL. One-file-per-key doesn't compose for many small entries. Not a cache — it's a settings/registry primitive.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/storage.py

## Anti-Patterns

- **Treating diskcache as async-safe without a wrapper.** Core is synchronous `sqlite3` — blocks the event loop if called directly from a coroutine. Both diskcache issues #116 and #282 confirm this.
- **Assuming aiocache gives disk persistence.** aiocache ships memory/Redis/Memcached only — no SQLite/disk backend without writing a custom plugin.
- **Ignoring the single-writer-transaction bottleneck.** diskcache transactions block other writes to the same cache during the transaction — relevant under concurrent async fan-out.

## Relevance to Us

The match between hassette's actual needs and what exists in the ecosystem is striking:

- **What hassette uses from diskcache**: constructor, close, get, set, delete, expire. That's it — ~5% of diskcache's surface area.
- **What hassette already has**: `aiosqlite` as a dependency, extensive `aiosqlite` usage patterns in `database_service.py`, connection management, WAL mode, migrations.
- **What the hand-rolled approach costs**: ~100-150 lines of code (one table schema, get/set/delete/clear/close, expiry column checked on read). The project already has all the patterns needed — `aiosqlite` connection management, async lifecycle hooks, try/except error handling around SQLite.
- **What diskcache costs going forward**: `to_thread` wrapping on every operation, a dependency whose 95% unused surface area becomes frozen public API baggage, thread-pool contention sharing a pool with logging/database (a finding the challenge already surfaced).

The thread-pool executor wrapping pattern (Pattern 1) is the ecosystem's pragmatic default, but it exists because most projects don't already have `aiosqlite` and async SQLite expertise in-house. Hassette does.

## Recommendation

**Pattern 3 (hand-rolled aiosqlite cache) is the strongest fit.** The arguments:

1. **Zero new dependencies** — `aiosqlite` is already imported in 4 files across the project
2. **Eliminates the entire `to_thread` wrapping layer** — every async cache method becomes a direct `await` on `aiosqlite`, matching how `database_service.py` already works
3. **Eliminates the thread-pool contention finding** from the challenge — no shared executor concern at all
4. **The implementation is small** — one table (`key TEXT PK, value BLOB, expires_at REAL`), get/set/delete/clear/close, plus `check()` via `PRAGMA integrity_check`. ~100-150 lines, all following patterns already established in `database_service.py`
5. **Removes `diskcache` as a dependency entirely** — one less thing to maintain, no unused surface area frozen into the API
6. **The `CacheWrapper(Resource)` design from the design doc still applies** — the wrapper just holds an `aiosqlite` connection instead of a `diskcache.Cache`. The public API (`get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`), the `DummyCache`, the `CacheSyncFacade`, the `cache_key` configuration, the corruption handling — all stay the same

The risk is owning correctness for concurrent-writer handling and vacuuming, but hassette already manages this for its telemetry database via `database_service.py` — the patterns (WAL mode, connection lifecycle, error handling) are proven in the codebase.

**If this feels like too much to own**: Pattern 1 (keep diskcache, wrap in executor) is the safe default. The design doc as written works for either backend — the wrapper abstracts it.

## Sources

### Reference implementations
- https://github.com/grantjenks/python-diskcache — diskcache itself
- https://github.com/Krukov/cashews — async cache framework with diskcache backend
- https://github.com/aio-libs/aiocache — async cache (no disk backend)
- https://github.com/colingrady/LiteCache — minimal sync SQLite TTL cache
- https://github.com/jkelin/cache-sqlite-lru-ttl — TypeScript SQLite TTL+LRU cache
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/storage.py — HA's Store

### Discussions & issues
- https://github.com/grantjenks/python-diskcache/issues/282 — async diskcache proposal (closed, never built)
- https://github.com/grantjenks/python-diskcache/issues/116 — asyncio compatibility discussion

### Blog posts & documentation
- https://grantjenks.com/docs/diskcache/tutorial.html — official diskcache tutorial (async section)
- https://www.bitecode.dev/p/diskcache-more-than-caching — deep dive on diskcache capabilities
- https://aiohttp-client-cache.readthedocs.io/en/v0.3/modules/aiohttp_client_cache.backends.sqlite.html — async SQLite cache backend
- https://python-helpers.readthedocs.io/en/latest/helpers/privex.helpers.cache.html — Privex AsyncSqliteCache
