# App Cache

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Store app data that survives restarts — counters, timestamps, API responses — using `self.cache`.

## What was cut (and where it goes)

- **"When to Use the Cache" bullet list** — replaced with a one-sentence functional definition in the opening, then a brief "not for entity state" note. The existing bullet list front-loads four use cases before the reader sees any code. The patterns page already shows each use case with full examples.
- **"How It Works" sub-sections** (Storage Location, Shared Cache, Lazy Initialization, Automatic Cleanup) — kept but reordered. "Shared Cache" moves up because it is the most common surprise (multi-instance key collisions). Storage location and lazy init are implementation details that go after basic usage.

## Outline

### (Opening)
`self.cache` provides persistent key-value storage on every app. Data written to the cache survives restarts and is available immediately at the next startup. The cache is a `diskcache.Cache` instance — the full diskcache API is available directly.

For real-time HA entity state, use `self.states`. The cache is for app data: counters, timestamps, API responses, preferences.

### H2: Basic Usage
Dictionary-like API: `get`, `set`, `delete`, check membership. Show a minimal code example. Emphasize: no open, flush, or close needed.

### H2: Shared Cache and Multi-Instance Apps
All instances of the same class share one cache directory (keyed by class name). For multi-instance apps, prefix keys with `self.app_config.instance_name` to avoid collisions.

### H2: What Can Be Cached
Anything picklable: primitives, collections, `whenever` timestamps, Pydantic models, dataclasses. Not limited to JSON-serializable types.

!!! tip on `self.now()` for timestamps.

### H2: Configuration
`default_cache_size` (100 MiB default) in root `HassetteConfig`. Cache path derived from `data_dir`. Brief TOML example.

### H2: How It Works
- **Storage Location** — `{data_dir}/{ClassName}/cache/`
- **Lazy Initialization** — cache dir created on first access
- **Lifecycle** — available from first access, flushed at shutdown
- **Automatic Cleanup** — TTL expiry, silent LRU eviction at `size_limit`

### H2: See Also
Patterns & Examples, Configuration, States, diskcache docs.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `cache_basic_usage.py` | Keep | H2: Basic Usage |
| `cache_instance_prefix.py` | Keep | H2: Shared Cache |

Remaining 7 snippets (`cache_api_response.py`, `cache_rate_limit.py`, `cache_counter.py`, `cache_complex_data.py`, `cache_expire.py`, `cache_expiring.py`, `cache_performance.py`) belong to the Patterns page.

## Cross-Links

- **Links to:** Patterns & Examples, Configuration (cache settings), diskcache docs
- **Linked from:** Architecture, Apps overview, States overview
