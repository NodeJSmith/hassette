---
proposal: "Redesign Resource.cache from raw diskcache.Cache to a typed, instance-scoped CacheWrapper with TTL, DummyCache, async safety, and startup health checks."
date: 2026-07-16
status: Draft
flexibility: Leaning
motivation: "Raw diskcache.Cache is about to become frozen public API at v1.0.0; need typed wrapper before API freeze."
constraints: "Clean break — no backwards compatibility shims. Must land before v1.0.0 API freeze (at minimum the typed interface)."
non-goals: "Anti-stampede locking, in-memory LRU layer, replacing diskcache."
depth: normal
---

# Research Brief: Redesign Resource.cache

**Initiated by**: Issue #595 — Redesign Resource.cache with instance-scoped directories, typed wrapper, TTL, test isolation, async safety, and startup health checks.

## Context

### What prompted this

The `release:v1.0.0` label on this issue carries a specific urgency: `Resource.cache` currently returns a raw `diskcache.Cache` object. Once the v1.0.0 API freeze lands, that raw object and its directory layout become part of the frozen public contract. Wrapping it afterward would be a breaking change. The typed interface must land before the freeze; the other requirements (TTL, instance-scoping, DummyCache, corruption handling) can follow in any later release, though shipping them together is preferable.

### Current state

**The property** (`src/hassette/resources/base.py:220-230`): A `@cached_property` that lazily creates a `diskcache.Cache(directory, size_limit=config.default_cache_size)`. The `_cache` attribute starts as `None`; the property checks it first, allowing test injection via `resource._cache = fake`.

**Directory scoping**: `{data_dir}/{class_name}/cache/`. Keyed by `self.class_name` (a `ClassVar[str]` set to `cls.__name__` in `__init_subclass__`). The docstring is explicit: "All instances of the same resource class share a cache directory." This means two instances of `WeatherApp` with different configs silently share one SQLite database. The docs even acknowledge this and suggest manual key-prefixing with instance name as a workaround (`docs/pages/core-concepts/cache/index.md:19-24`, `snippets/cache_instance_prefix.py`).

**Config**: Two fields in `HassetteConfig` — `data_dir: Path` (base directory) and `default_cache_size: int` (100 MiB default, passed as `size_limit`). No TTL, eviction policy, or per-resource config.

**Cleanup**: `Resource.cleanup()` calls `self.cache.close()` synchronously (not wrapped in `asyncio.to_thread`) inside a try/except that logs and swallows errors. Only runs if `_cache is not None`, so resources that never touch `.cache` incur no cost.

**Framework usage**: The framework itself calls only the `Cache()` constructor and `.close()`. No `get`, `set`, `delete`, or any data method is called anywhere in `src/hassette/`. Cache is purely user-facing infrastructure.

**User-facing usage** (docs examples + `examples/cover_scheduler.py`): `self.cache.get(key, default)`, `self.cache.set(key, value, expire=N)`, `self.cache[key] = value`, `self.cache[key]`, `key in self.cache`. The docs page at `docs/pages/core-concepts/cache/index.md` explicitly states "The full diskcache API is available directly."

**unique_id**: Every `Resource` gets a `unique_id = uuid.uuid4().hex[:8]` in `__init__`. It is available immediately at construction time. It is not deterministic across restarts. It is currently used only in `unique_name` for top-level (parentless) resources. It is not used in cache path construction at all.

### Key constraints

- Clean break — no backwards compat shims, no migration path needed (confirmed by user).
- At minimum, the typed interface must land before v1.0.0 API freeze.
- Anti-stampede locking, in-memory LRU, and replacing diskcache are explicit non-goals.
- This is a `size:large` issue tagged `area:core`, `topic:architecture`.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| CacheWrapper + DummyCache (new) | 1-2 new files in `src/hassette/cache/` | Med | Low — new code, no existing callers to break |
| Resource.cache property | `src/hassette/resources/base.py` | Low | Low — property return type changes, cleanup logic moves |
| Config | `src/hassette/config/config.py` | Low | Low — add TTL field(s) |
| Tests (cache property) | `tests/unit/resources/test_resource_properties.py` | Low | Low — 3 tests to update |
| Tests (shutdown) | `tests/unit/resources/test_shutdown_edge_cases.py` | Low | Low — 2 tests with local fakes to update |
| Test utils | `src/hassette/test_utils/` | Low | Low — add DummyCache fixture |
| Docs (cache pages) | `docs/pages/core-concepts/cache/index.md`, `patterns.md`, all snippets | Med | Low — rewrite examples for new API |
| Example apps | `examples/cover_scheduler.py` | Low | Low — 3 cache call sites |

### What already supports this

1. **Lazy init with `_cache` injection**. The existing `if self._cache is not None: return self._cache` pattern in the property already supports test injection. A DummyCache can slot in via `resource._cache = DummyCache()` with zero changes to that injection path.

2. **`asyncio.to_thread` is an established pattern**. Four call sites in `database_service.py`, `logging_service.py`, and `sync_executor_service.py` all wrap sync I/O via `asyncio.to_thread`. The cache wrapper follows the same pattern. The project distinguishes between `to_thread` (framework-internal I/O on the loop-default executor) and `TaskBucket.run_in_thread` (user sync code on the dedicated executor). Cache is framework-internal, so `to_thread` is correct.

3. **`unique_id` is available at construction time**. No lifecycle timing issue — the cache directory can incorporate `unique_id` (or `unique_name`, or `app_key` from config) immediately in `__init__` or on first property access.

4. **Health check pattern exists**. `TelemetryQueryService.check_health()` runs `SELECT 1` against its SQLite database and raises `TelemetryUnavailableError` on failure. The cache `check()` can follow the same raise-on-failure pattern with graceful degradation.

5. **No framework-internal data method calls**. The framework never calls `get`/`set`/`delete` on the cache — it only constructs and closes it. This means the wrapper can change the entire data API surface without any framework-internal migration.

6. **Prior art research is thorough and validated**. The research document at `design/research/2026-04-25-disk-cache-layer-design/research.md` covers 7 patterns, 4 anti-patterns, and sources from 14 references. The issue owner's comment confirms 4 core design decisions. No additional research is needed.

### What works against this

1. **`unique_id` is not deterministic across restarts**. It is `uuid.uuid4().hex[:8]`, regenerated fresh on every instantiation. Using it as the cache directory path means each restart creates a new, empty cache directory — losing all previously cached data. The issue acceptance criteria suggest `{data_dir}/{app_name}/{resource_class}/cache/` using `app_name` (from config, deterministic) rather than `unique_id`. This needs careful design: the identity token must be stable across restarts but unique across concurrent instances.

2. **Docs explicitly promise raw diskcache access**. `docs/pages/core-concepts/cache/index.md:3` says "The full diskcache API is available directly." The docs examples use dict-style access (`self.cache["key"]`, `"key" in self.cache`, `del self.cache["key"]`). The typed wrapper will break all documented patterns. This is acceptable (clean break), but the docs rewrite is non-trivial — 2 docs pages, 7 snippet files, and 1 example app.

3. **Dict-style access is ergonomic**. The current `self.cache["key"] = value` is arguably more ergonomic than `await self.cache.set("key", value)`. The async wrapper adds `await` to every cache access. This is a real usability regression in exchange for correctness (non-blocking I/O). The docs patterns page will need to demonstrate the new async patterns clearly.

4. **`cache.check()` on startup must not block initialization**. diskcache's `Cache.check()` is a synchronous call that reads the entire SQLite database. For large caches, this could be slow. It must run via `asyncio.to_thread` and should degrade gracefully (log a warning, optionally clear corrupt cache) rather than failing startup.

## Options Evaluated

### Option A: Full CacheWrapper with all 6 requirements

**How it works**: Create a new `src/hassette/cache/` package with a `CacheWrapper` class and a `DummyCache` class, both implementing a `CacheProtocol`. `CacheWrapper` holds a `diskcache.Cache` instance internally and exposes only the typed interface (`get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`). All methods are `async def` and wrap diskcache calls in `asyncio.to_thread`. A per-resource default TTL is configurable via class attribute or config, with per-key override. `DummyCache` implements the same protocol as no-ops.

The `Resource.cache` property changes its return type from `diskcache.Cache` to `CacheWrapper` (or `CacheProtocol`). Directory construction moves from `{data_dir}/{class_name}/cache/` to `{data_dir}/{app_key}/cache/` where `app_key` comes from the app's configuration (stable across restarts, unique per configured app instance).

Startup runs `await asyncio.to_thread(cache.check)` in `on_initialize` or on first access, with graceful degradation on corruption. Shutdown wraps `cache.close()` in `asyncio.to_thread`.

**Concrete file changes**:
- **New**: `src/hassette/cache/__init__.py` — exports `CacheWrapper`, `DummyCache`, `CacheProtocol`
- **New**: `src/hassette/cache/wrapper.py` — `CacheWrapper` class with async methods wrapping `diskcache.Cache`
- **New**: `src/hassette/cache/dummy.py` — `DummyCache` no-op implementation
- **New**: `src/hassette/cache/protocol.py` — `CacheProtocol` (runtime-checkable Protocol or ABC)
- **Modify**: `src/hassette/resources/base.py` — change `cache` property return type, update `cleanup()` to use `await asyncio.to_thread(self.cache.close)`
- **Modify**: `src/hassette/config/config.py` — add `default_cache_ttl: int | None` field
- **Modify**: `src/hassette/test_utils/` — add `DummyCache` fixture or `make_dummy_cache()` factory
- **Modify**: `tests/unit/resources/test_resource_properties.py` — update 3 tests for new return type
- **Modify**: `tests/unit/resources/test_shutdown_edge_cases.py` — update 2 tests
- **New**: `tests/unit/cache/` — unit tests for `CacheWrapper`, `DummyCache`
- **Modify**: `docs/pages/core-concepts/cache/index.md` — rewrite for new API
- **Modify**: `docs/pages/core-concepts/cache/patterns.md` — rewrite all patterns for async API
- **Modify**: All 7 snippet files in `docs/pages/core-concepts/cache/snippets/`
- **Modify**: `examples/cover_scheduler.py` — update 3 cache call sites

**Instance identity for directory scoping**: The issue suggests `{data_dir}/{app_name}/{resource_class}/cache/`. For `App` subclasses, `app_key` (from `AppConfig`) is the natural stable identifier — it is user-configured, deterministic across restarts, and unique per app instance. For non-App Resources (framework services like `BusService`, `SchedulerService`), `class_name` remains appropriate since there is only one instance per type. The `Resource` base class would need a hook (overridable property or method) that returns the identity token for cache scoping — `App` overrides it to return `app_key`, other Resources default to `class_name`.

**TTL semantics**: `ttl=None` on `set()` uses the resource's default TTL. If the resource's default TTL is also `None`, the value persists indefinitely (matching diskcache's current behavior). `ttl=0` means "don't cache" (the `set()` call is a no-op). Negative TTL is an error.

**Periodic culling**: diskcache only removes expired items lazily during eviction or explicit `cull()`/`expire()` calls. The wrapper should schedule periodic `expire()` calls (via `asyncio.to_thread`) — either on a timer or piggy-backed on `get()` calls after some interval. The `Scheduler` is available on the owning `App`, so a `run_every` for culling is straightforward.

**Pros**:
- Ships the complete redesign in one coherent change
- Eliminates all identified problems (cross-contamination, contention, no TTL, raw API exposure, test pollution, blocking I/O)
- Clean API surface for the v1.0.0 freeze — no diskcache leakage
- DummyCache simplifies test infrastructure immediately

**Cons**:
- Largest scope — touches docs, examples, tests, config, and core framework
- Async API is less ergonomic than dict-style access (`await self.cache.set("k", v)` vs `self.cache["k"] = v`)
- Periodic culling adds a background task per app instance
- Directory identity design needs care to handle both App resources (app_key) and non-App resources (class_name)

**Effort estimate**: Medium-Large. The wrapper itself is straightforward (thin async layer over diskcache). The bulk of the effort is docs rewrite (7 snippet files, 2 docs pages), test updates, and getting the instance-identity scoping right for both App and non-App resources.

**Dependencies**: No new libraries. `diskcache>=5.6.3` (already a dependency) provides all needed functionality. `asyncio.to_thread` is stdlib.

### Option B: Typed wrapper only (defer instance-scoping, TTL config, and culling)

**How it works**: Ship the minimum needed before API freeze: a `CacheWrapper` that wraps `diskcache.Cache` with typed methods and `asyncio.to_thread`. Keep the current class-scoped directory layout. No TTL configuration, no periodic culling, no `cache.check()` on startup. DummyCache included because it is cheap and immediately useful for tests.

This addresses the core freeze concern (raw diskcache.Cache no longer in public API) while deferring the behavioral improvements to post-freeze work. The wrapper's method signatures include `ttl=None` parameters from day one so the interface is forward-compatible, but TTL is simply passed through to `diskcache.Cache.set(expire=...)` without a default-TTL mechanism.

**Pros**:
- Smallest scope that satisfies the API freeze requirement
- Lower risk — no directory layout change, no config changes
- DummyCache still ships, improving test ergonomics immediately
- Forward-compatible interface — `ttl` parameters are in the signatures, just unused for defaults

**Cons**:
- Does not fix instance-scoping (the documented design mistake)
- Does not add default TTL (the "forgot to set expire" unbounded growth problem)
- Does not add startup health checks
- Requires a follow-up PR for each deferred requirement
- Two rounds of docs changes (now for API shape, later for behavioral changes)

**Effort estimate**: Small-Medium. Wrapper + DummyCache + tests + docs rewrite. No config changes, no directory layout changes.

**Dependencies**: Same as Option A (none new).

## Concerns

### Technical risks

1. **Instance identity for cache directories**. `unique_id` is random per restart — using it directly would orphan cache data on every restart. `app_key` (from `AppConfig`) is the right identity token for `App` subclasses, but `Resource` does not have direct access to `app_key` — it would need to be threaded through (or the Resource would need a `cache_identity` hook that `App` overrides). Non-App Resources (framework services) do not have an `app_key` equivalent. The design must handle both cases cleanly.

2. **Synchronous `on_initialize` / `on_shutdown` cache access**. Some documented patterns (e.g., `cache_performance.py` "Load Once, Write on Shutdown") read from cache in `on_initialize` and write in `on_shutdown`. If all cache methods become `async`, these lifecycle hooks (which are already `async def`) accommodate this naturally. But if any user has sync helper code that calls `self.cache.get()` synchronously, it will break. Since this is a clean break, this is acceptable — but the migration docs should call it out.

3. **`cache.check()` cost on large caches**. diskcache's `Cache.check()` reads the entire SQLite database to verify integrity. For a 100 MiB cache, this is non-trivial I/O. It must run via `asyncio.to_thread` and should have a timeout. A corrupt cache should log a warning and optionally `clear()` rather than preventing startup.

### Complexity risks

1. **Two kinds of Resources with different identity models**. App resources have `app_key` (deterministic, user-configured). Non-App resources have only `class_name` (already used today). The cache scoping logic must branch on this or provide an overridable hook. This is a small amount of complexity but must be tested for both paths.

2. **Periodic culling lifecycle**. If the wrapper schedules periodic `expire()` calls via `Scheduler.run_every`, it adds a background task per app instance. The task must be cancelled on shutdown, and the scheduler must be available (it might not be if cache is accessed before scheduler initialization). An alternative is to piggyback culling on `get()` calls (cull every N accesses or every T seconds since last cull), which avoids the scheduler dependency.

### Maintenance risks

1. **Docs maintenance burden**. The cache docs page and patterns page are substantial (7 snippet files, 2 prose pages). Every cache API change now requires updating these artifacts. This is a one-time cost for the redesign, but ongoing for future cache changes.

2. **diskcache version coupling**. The wrapper hides `diskcache.Cache` but still depends on its behavior. If diskcache changes its `expire` semantics, `check()` behavior, or SQLite usage, the wrapper must be updated. The `diskcache>=5.6.3` floor with no ceiling is a risk if a future major version breaks assumptions.

## Open Questions

- [ ] **What identity token should scope App cache directories?** `app_key` from `AppConfig` is the natural choice, but is it guaranteed unique across all configured apps? If two apps have the same `app_key`, they should probably share a cache — but this needs explicit confirmation. Also: is `app_key` available on the `Resource` base class, or does it need to be threaded through?

- [ ] **Should dict-style access be preserved on the wrapper?** `self.cache["key"]` is ergonomic and used in all current examples. The wrapper could implement `__getitem__`/`__setitem__`/`__contains__`/`__delitem__` as synchronous convenience methods that call the underlying diskcache directly (without `to_thread`). This would preserve ergonomics for non-critical paths at the cost of inconsistency (some methods async, some sync). The issue's API sketch (`await cache.get(...)`) suggests async-only, but this is worth confirming.

- [ ] **Should the CacheWrapper expose `type=` on `get()` for typed deserialization?** The issue owner's comment includes `value: MyModel | None = await cache.get("key", type=MyModel, ttl=3600)` with a `type=` parameter. This implies runtime type checking or deserialization on read. diskcache uses pickle, which already returns the original type — `type=` would add an `isinstance` check or Pydantic validation. This is a convenience but adds complexity. Clarify whether this is desired for v1 or can be deferred.

- [ ] **Should existing cache data be migrated when directory layout changes?** The issue says "migration path documented or confirmed unnecessary." If `app_key`-scoped directories are used, existing class-scoped cache data at `{data_dir}/{ClassName}/cache/` becomes orphaned. For most users this is a cache warm-up cost, not data loss. Confirm no migration is needed.

- [ ] **Should periodic culling be a framework responsibility or left to the user?** diskcache's lazy expiration means expired data consumes disk until explicitly culled. The framework could schedule periodic `Cache.expire()` calls, or document it as user responsibility. The issue lists "Periodic culling of expired items" in acceptance criteria, suggesting framework responsibility — but the implementation approach (scheduler task vs. piggyback on access) is unspecified.

## Recommendation

The prior art research is thorough, the issue acceptance criteria are well-specified, and the codebase supports all six requirements without structural obstacles. The main risk is scope, not feasibility.

**Recommended approach**: Option A (full redesign), but with phased implementation within a single PR or a short PR chain:

1. **Phase 1 (must-ship before freeze)**: `CacheWrapper`, `DummyCache`, `CacheProtocol`, async methods with `asyncio.to_thread`, `Resource.cache` return type change. This is the API surface that gets frozen.

2. **Phase 2 (same PR or immediate follow-up)**: Instance-scoped directories, per-resource TTL config, `cache.check()` on startup, periodic culling. These are behavioral improvements behind the frozen interface — they can ship at any time without breaking the public API.

This phasing lets the team prioritize the freeze-critical work (interface narrowing) while keeping the behavioral improvements in scope. If timeline pressure hits, Phase 2 can slip to a follow-up without compromising the v1.0.0 freeze.

The main open question that needs resolution before implementation is the instance identity token — `app_key` availability on `Resource` and its uniqueness guarantees. This is a design decision, not a research question.

### Suggested next steps

1. **Resolve the identity question** — confirm `app_key` as the cache directory identity token for App resources, and how it flows to the `Resource` base class (overridable property vs. constructor parameter).
2. **Write a design doc via `/mine-define`** — the research and issue provide enough context to specify the full API surface, directory layout, and TTL semantics.
3. **Implement Phase 1 first** — `CacheWrapper`, `DummyCache`, property change, docs rewrite. Ship or stage this before the API freeze.
