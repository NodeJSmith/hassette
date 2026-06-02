# App Cache: Patterns & Examples

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (patterns/recipes hybrid)
**Reader's job:** Find a proven pattern for a specific caching problem — rate limiting, counters, expiry, complex data — and adapt it.

## What was cut (and where it goes)

- **"Best Practices — What to Cache"** — cut. The overview page already states what the cache is for vs what `self.states` is for. Repeating it here as a "good uses / avoid caching" list is padding.
- **"Best Practices — Cache vs StateManager"** — cut. Same content as the overview page's "not for entity state" note plus a comparison table that restates the obvious.
- **"Best Practices — Performance"** — folded into the "Load Once, Write on Shutdown" pattern where it naturally belongs.
- **"Troubleshooting — Debugging Cache Operations"** — tightened. The advice to set `log_level = "DEBUG"` and check the cache directory is two sentences, not a section.

## Outline

### (Opening)
Practical patterns for `self.cache`. Each pattern solves a specific problem with a complete, runnable example. The overview page covers setup and basic usage.

### H2: Rate-Limiting Notifications
Problem: prevent notification spam. Store a timestamp, check cooldown before sending. Show per-entity variant (entity ID in the cache key).

### H2: Persistent Counters
Problem: track events across restarts. Load from cache at init, write back on every increment.

### H2: API Response Caching
Problem: avoid hitting external rate limits. Store response with timestamp, check freshness before re-fetching.

### H2: Expiring Entries
Two approaches, simplest first:
- `self.cache.set(key, value, expire=seconds)` — diskcache handles TTL automatically.
- Store a timestamp alongside the value for custom staleness logic or "last fetched" display.

### H2: Storing Complex Data
Dataclasses, Pydantic models, dicts. Note: use `dataclasses.replace()` for immutability.

### H2: Load Once, Write on Shutdown
Load into an instance variable at init, write back at shutdown. Avoids disk I/O on every access. Note: cache is thread-safe for concurrent async access.

### H2: Troubleshooting

#### H3: Cache Not Persisting
Checklist: writing to `self.cache` not a local var, app completes init without exception, directory has write permissions, value is picklable.

#### H3: Cache Size Exceeded
LRU eviction is automatic and silent. Increase `default_cache_size`, implement TTL expiry, or store large objects externally.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `cache_rate_limit.py` | Keep | H2: Rate-Limiting |
| `cache_counter.py` | Keep | H2: Persistent Counters |
| `cache_api_response.py` | Keep | H2: API Response Caching |
| `cache_expire.py` | Keep | H2: Expiring Entries (TTL) |
| `cache_expiring.py` | Keep | H2: Expiring Entries (timestamp) |
| `cache_complex_data.py` | Keep | H2: Storing Complex Data |
| `cache_performance.py` | Keep | H2: Load Once, Write on Shutdown |

## Cross-Links

- **Links to:** Cache overview, States overview (cache vs StateManager), Configuration
- **Linked from:** Cache overview, Recipes
