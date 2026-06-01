# Cache — Overview

**Status:** Exists (104 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: When to Use the Cache
Persistent key-value storage for data that survives restarts. Not for entity state (use StateManager) or temporary data.

### H2: Basic Usage
`self.cache` is a raw `diskcache.Cache` instance — the full diskcache API is available directly (`.get()`, `.set()`, `.delete()`, `.pop()`, `.expire()`, etc.).

### H2: How It Works
#### H3: Storage Location — `diskcache.Cache` backed by filesystem
#### H3: Shared Cache — instances of the same class share one cache (keyed by class name, path: `data_dir/<ClassName>/cache`)
#### H3: Lazy Initialization — cache dir created on first access via `cached_property`
#### H3: Automatic Cleanup — TTL expiry, silent eviction when `size_limit` reached

### H2: Configuration
Only setting: `default_cache_size` (default 100 MiB) in root `HassetteConfig`. No `[hassette.cache]` section. Cache path is derived automatically.

### H2: Lifecycle
When cache is available during app lifecycle.

### H2: Data Types
What can be cached (anything picklable — diskcache uses `pickle` as its default serializer). Includes dataclasses, Pydantic models, sets, custom objects. Not limited to JSON-serializable types.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 9 files in `cache/snippets/` | Keep | Basic cache operations |

## Cross-Links

- **Links to:** Patterns & Examples, Configuration/Global (cache settings)
- **Linked from:** Architecture, Apps overview
