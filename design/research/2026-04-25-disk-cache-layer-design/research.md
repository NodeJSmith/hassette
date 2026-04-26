---
topic: "Disk cache layer design for hassette's Resource base class"
date: 2026-04-25
status: Draft
---

# Prior Art: Disk Cache Layer Design

## The Problem

Hassette's `Resource` base class provides a `cache` property that gives every resource access to a `diskcache.Cache` instance. The cache directory is derived from the class name (`data_dir/ClassName/cache/`), meaning all instances of the same Resource subclass share the same SQLite-backed cache — class-scoped, not instance-scoped.

This scoping creates several problems: multiple instances of the same resource type silently share cached data (cross-contamination), concurrent writes from different app tasks can trigger SQLite "database is locked" errors, and test isolation requires careful directory management. Beyond scoping, the current implementation has no TTL support, no eviction policy configuration, no explicit invalidation API, and exposes the raw `diskcache.Cache` object directly to consumers.

## How We Do It Today

`Resource.cache` is a `@cached_property` that lazily creates a `diskcache.Cache(directory, size_limit=config.default_cache_size)` on first access (`base.py:178-188`). The directory is `{data_dir}/{class_name}/cache/`, so two instances of `LightManager` share one SQLite database. Configuration is a single global value: `default_cache_size = 100 MiB`. Cleanup calls `cache.close()` on shutdown (`base.py:523-527`). The raw Cache object is exposed directly — consumers call `self.cache[key]`, `self.cache.get(key)`, etc.

## Patterns Found

### Pattern 1: Instance-Scoped Cache Directories

**Used by**: cachier (per-function pickle files), HA integrations (per-integration Store), diskcache best practices (separate directories per concern)

**How it works**: Each resource instance gets its own isolated cache directory incorporating instance identity (e.g., `{base_dir}/{app_name}/{resource_class}/{instance_id}/`). Each instance operates on its own SQLite database, eliminating key collision and write contention entirely.

cachier takes this to the extreme: it raises `TypeError` when decorating instance methods by default, explicitly preventing cross-instance cache sharing unless opted into. Home Assistant's `helpers.storage.Store` scopes storage per-integration with no shared-cache pattern. The Bite Code blog (by a diskcache expert) recommends "creating multiple specialized cache instances — one for general caching, another for a queue, a last one for a poor man's DB."

The tradeoff is filesystem overhead — each cache directory creates ~3 SQLite files (~12KB empty). For a framework with many resources this means dozens of small databases, but SQLite handles this efficiently.

**Strengths**: Complete isolation, no key collision risk, no write contention, simple mental model, easy cleanup (delete directory), trivial test isolation (use temp directories)

**Weaknesses**: More filesystem objects, slightly more memory (one SQLite connection per instance), cache sharing between instances requires explicit coordination, directory proliferation if instances are short-lived

**Example**: https://github.com/python-cachier/cachier, https://community.home-assistant.io/t/best-practices-on-how-and-where-to-store-integration-data-cache/631713

### Pattern 2: Namespace-Prefixed Keys in Shared Cache

**Used by**: Django (KEY_PREFIX + VERSION), aiocache (namespace parameter), Flask-Caching (CACHE_KEY_PREFIX), dogpile.cache (namespace in key generator)

**How it works**: All instances share a single cache backend but prefix their keys with a unique namespace string. aiocache's `namespace="myapp.lights"` makes key `"state"` become `"myapp.lights:state"`. Django combines KEY_PREFIX + VERSION + key.

This achieves logical isolation without physical separation. It's the standard approach for distributed caches (Redis, Memcached) where creating separate instances has real infrastructure cost. For diskcache, it means all resources share one SQLite database — simpler lifecycle but shared eviction pool and write contention.

**Strengths**: Single database to manage, lower filesystem overhead, enables cross-resource queries, simpler configuration

**Weaknesses**: Key collision if namespace generation has bugs, shared eviction pool (one resource's large values evict another's), SQLite write contention, test isolation requires prefix management or `cache.clear()`, no per-resource size limits

**Example**: https://docs.djangoproject.com/en/6.0/topics/cache/, https://aiocache.aio-libs.org/en/latest/caches.html

### Pattern 3: Region-Based Cache Configuration (dogpile.cache)

**Used by**: dogpile.cache (CacheRegion), SQLAlchemy (query cache regions)

**How it works**: A "region" is a named, pre-configured cache scope with its own backend, expiration policy, and key generation strategy. Regions are created at module import time with `make_region()` and configured later at application startup with `configure()`. This two-phase initialization allows decorators to reference regions before the backend is chosen.

Each region encapsulates: which backend to use, default expiration time, key generation, key mangling, and anti-stampede locking. Functions decorated with `@region.cache_on_arguments()` automatically generate keys from arguments.

This maps well to hassette's Resource model — each Resource subclass could define a cache region at class definition time (via `__init_subclass__`), and the framework configures the region's backend when the resource is instantiated.

**Strengths**: Clean separation of cache policy from cache usage, supports heterogeneous backends per region, built-in anti-stampede locking, two-phase init avoids import-time side effects

**Weaknesses**: More complex than raw cache access, region proliferation, configuration management overhead

**Example**: https://dogpilecache.sqlalchemy.org/en/latest/usage.html

### Pattern 4: Anti-Stampede / Single-Flight Patterns

**Used by**: dogpile.cache (core feature), diskcache (`memoize_stampede` recipe), Django + Redis (`cache.lock`)

**How it works**: When a cached value expires and multiple concurrent readers request it, only one reader acquires a lock and regenerates the value. Others either serve stale data or block until regeneration completes. This prevents the "thundering herd" where N concurrent requests all hit the backend.

diskcache implements this via `memoize_stampede()` using probabilistic early expiration — before TTL expires, a random chance triggers regeneration, spreading load. dogpile.cache uses explicit locking. The "single-flight" pattern (common in Go) coalesces concurrent requests for the same key into one computation.

For hassette, this matters when cached HA API responses expire and multiple event handlers try to refresh simultaneously.

**Strengths**: Prevents backend overload, serves stale data during regeneration, well-understood pattern with mature implementations

**Weaknesses**: Adds complexity, stale data window during regeneration, lock management overhead, potential deadlocks if writer crashes

**Example**: https://dogpilecache.sqlalchemy.org/en/latest/usage.html, https://www.bitecode.dev/p/diskcache-more-than-caching

### Pattern 5: DummyCache / Null Backend for Testing

**Used by**: Django (DummyCache), Flask-Caching (NullCache)

**How it works**: A cache backend that implements the full API but never stores anything. `set()` is a no-op, `get()` always returns the default. This allows test suites to run without cache side effects while exercising all cache-using code paths.

Django's approach: swap the backend in test settings without changing application code. The DummyCache has the same interface as any other backend.

For hassette, the `Resource.cache` property could return a null implementation during testing, avoiding temp directories or explicit cleanup in teardown.

**Strengths**: Zero test pollution, no filesystem cleanup needed, exercises all code paths, trivial to configure

**Weaknesses**: Can't test cache-dependent behavior (e.g., persistence across restarts), may mask performance issues visible only with real caching

**Example**: https://docs.djangoproject.com/en/6.0/topics/cache/

### Pattern 6: Per-Key TTL with Global Default

**Used by**: Django (TIMEOUT + per-key override), aiocache (ttl on cache and per-call), cachetools (TTLCache with global TTL)

**How it works**: A global default TTL is set at the cache/region level, but individual `set()` calls can override it. Django's `cache.set("key", value, timeout=60)` overrides the CACHES TIMEOUT. Special values: `timeout=None` means "cache forever", `timeout=0` means "don't cache".

diskcache is notable for having **no global TTL** — every key's expiration is set individually via the `expire` parameter on `set()`. If you forget to pass `expire`, the value persists indefinitely. This is a common source of unbounded cache growth.

**Critical diskcache gotcha**: expired items are only removed lazily during culling. `expire()` or `cull()` must be called explicitly or scheduled to reclaim disk space. Items past their TTL still return `None` on `get()` but consume disk until culled.

**Strengths**: Flexible per-use-case, sensible defaults reduce boilerplate

**Weaknesses**: Easy to forget TTL on individual sets (especially with diskcache's no-global-default), lazy expiration means expired data consumes disk, inconsistent TTLs across codebase if not centralized

**Example**: https://docs.djangoproject.com/en/6.0/topics/cache/, https://grantjenks.com/docs/diskcache/tutorial.html

### Pattern 7: Cache Lifecycle Tied to Component Lifecycle

**Used by**: HA integrations (Store scoped to integration lifecycle), Django (`cache.close()` on shutdown), diskcache (context manager support)

**How it works**: The cache instance is created when its owning component starts and closed when the component shuts down. diskcache's `Cache` objects should be `close()`d to release SQLite connections. The `check()` method can run on startup to detect corruption from previous unclean shutdowns.

For hassette, this means opening in `on_initialize` (or lazily on first access) and closing in `on_shutdown` — which hassette already does. The gap is corruption detection: there's no `cache.check()` call on startup.

**Strengths**: Clean resource management, no leaked connections, corruption detection on startup

**Weaknesses**: Lazy initialization adds complexity, must handle cache unavailability during early lifecycle

**Example**: https://community.home-assistant.io/t/best-practices-on-how-and-where-to-store-integration-data-cache/631713

## Anti-Patterns

- **Class-Scoped Cache Without Instance Discrimination**: Multiple instances sharing a cache directory without key namespacing causes silent data cross-contamination. cachier explicitly raises `TypeError` on instance method caching to prevent this. Django warns: "If two users can receive different responses from the same endpoint, your cache key must encode that context." — https://github.com/python-cachier/cachier, https://dev.to/topunix/django-redis-caching-patterns-pitfalls-and-real-world-lessons-m7o

- **TTL-Only Invalidation (No Explicit Invalidation Path)**: Relying solely on TTL without explicit invalidation on state changes leads to stale data. If HA fires `state_changed` but the cache has 25s remaining, the app serves stale state. "If you cannot reliably identify all mutation paths, caching that data is unsafe." — https://dev.to/topunix/django-redis-caching-patterns-pitfalls-and-real-world-lessons-m7o

- **Forgetting to Clear Caches in Tests**: Disk-backed caches persist across test runs by default. Without temp directories or DummyCache, cached values from one test influence another, causing flaky tests. — https://docs.djangoproject.com/en/6.0/topics/cache/

- **Unbounded Disk Cache Growth**: diskcache defaults to 1GB, but expired items are only removed lazily during culling. Without explicit `expire()` or `cull()` calls, the directory grows with mostly-expired data. Combined with `eviction_policy='none'`, growth is unbounded. — https://grantjenks.com/docs/diskcache/tutorial.html

## Emerging Trends

- **Async-First Cache APIs**: aiocache and Django 5.x (`aget`, `aset`, `adelete`) reflect the shift toward async Python. For async-native frameworks like hassette, wrapping synchronous diskcache calls in `asyncio.to_thread()` avoids blocking the event loop on SQLite I/O.

- **Layered Caching (In-Memory + Disk)**: Two-tier caching — fast in-memory LRU in front of persistent disk cache — handles hot-path reads with zero deserialization overhead while the disk layer provides persistence across restarts. Invalidation must propagate through both layers.

- **Probabilistic Early Expiration**: Instead of hard TTL boundaries causing stampedes, each request gets a small random chance of refreshing before TTL expires. diskcache's `memoize_stampede` and cachier's `stale_after` + `next_time` implement this. Probability increases as TTL approaches expiration (XFetch algorithm).

## Relevance to Us

**Instance scoping is the clear winner.** The ecosystem overwhelmingly favors instance-scoped isolation — HA itself scopes storage per-integration, cachier refuses to cache instance methods by default, the diskcache author recommends separate directories per concern, and the documented failure mode of class-scoped caching (silent cross-contamination, SQLite locking under concurrent writes) matches exactly what hassette risks today.

**The interface should be wrapped, not raw.** Every mature framework (Django, dogpile, aiocache) provides a `get/set/delete` API with TTL on set, not a raw backend object. Exposing `diskcache.Cache` directly couples consumers to the backend and prevents the framework from enforcing TTL defaults, adding namespacing, or swapping in a DummyCache for tests.

**TTL with a per-resource default is table stakes.** diskcache's "no global TTL" design is the biggest usability gap — consumers must remember to pass `expire` on every `set()` or values persist forever. A thin wrapper with a configurable default TTL (overridable per-key) prevents unbounded growth.

**DummyCache for testing would solve test isolation cheaply.** Today, test isolation requires temp directories and explicit cleanup. A null backend behind the same interface eliminates this entirely.

**Anti-stampede is relevant but not urgent.** The stampede/single-flight patterns matter when multiple handlers cache expensive HA API calls, but hassette's current usage is lightweight. Worth designing the interface to support it later (via `get_or_set(key, creator_fn, ttl)`) without implementing full locking now.

**Async wrapping is a gap.** diskcache is synchronous (SQLite). Since hassette is async-first, cache access on hot paths should be wrapped in `asyncio.to_thread()` to avoid blocking the event loop. This could be transparent in the wrapper.

## Recommendation

1. **Switch to instance-scoped directories** — incorporate instance identity (e.g., app name) into the cache directory path. This eliminates cross-contamination and SQLite contention.

2. **Wrap diskcache in a thin typed interface** — `get(key, default) -> T`, `set(key, value, ttl=None)`, `delete(key)`, `get_or_set(key, creator, ttl=None)`, `clear()`, `invalidate(*keys)`. The wrapper holds a default TTL configurable per resource.

3. **Add per-resource TTL configuration** — default TTL on the wrapper, overridable per-key. This prevents the "forgot to set expire" unbounded growth problem.

4. **Add a DummyCache backend** — same interface, no-op implementation. Configure via test fixtures for zero-cost test isolation.

5. **Consider async wrapping** — `asyncio.to_thread()` around diskcache calls for non-blocking access in the async event loop.

6. **Defer anti-stampede** — design the `get_or_set` interface to support it later but don't implement locking now.

## Sources

### Reference implementations
- https://github.com/python-cachier/cachier — Per-function file caching, raises TypeError on instance methods
- https://cachetools.readthedocs.io/ — In-memory caches with per-instance accessor pattern
- https://dogpilecache.sqlalchemy.org/en/latest/usage.html — Region-based caching with anti-stampede locking

### Documentation & standards
- https://grantjenks.com/docs/diskcache/tutorial.html — diskcache official tutorial (eviction, TTL, FanoutCache)
- https://docs.djangoproject.com/en/6.0/topics/cache/ — Django cache framework (gold standard for Python cache design)
- https://aiocache.aio-libs.org/en/latest/caches.html — Async-first cache with namespace isolation
- https://flask-caching.readthedocs.io/ — Flask cache integration patterns
- https://community.home-assistant.io/t/best-practices-on-how-and-where-to-store-integration-data-cache/631713 — HA integration storage patterns

### Blog posts & experience reports
- https://www.bitecode.dev/p/diskcache-more-than-caching — Practical diskcache patterns and recommendations
- https://medium.com/@dynamicy/the-practical-guide-to-python-caching-from-pycache-to-lru-ttl-single-flight-redis-and-http-28b51d4063ac — Caching anti-patterns and single-flight pattern
- https://dev.to/topunix/django-redis-caching-patterns-pitfalls-and-real-world-lessons-m7o — Cache key design failures and invalidation lessons

### Bug reports & discussions
- https://github.com/grantjenks/python-diskcache/issues/85 — SQLite "database is locked" with shared directories
- https://github.com/grantjenks/python-diskcache/issues/325 — Fork corruption with shared Cache instances
- https://talkpython.fm/episodes/show/534/diskcache-your-secret-python-perf-weapon — diskcache author interview on design philosophy
