# Cache — Overview

**Status:** Exists (104 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: When to Use the Cache
Persistent key-value storage for data that survives restarts. Not for entity state (use StateManager) or temporary data.

### H2: Basic Usage
`self.cache.get()`, `self.cache.set()`, `self.cache.delete()`.

### H2: How It Works
#### H3: Storage Location — DiskCache on filesystem
#### H3: Shared Cache — all app instances share one cache, keyed by app
#### H3: Lazy Initialization — cache dir created on first access
#### H3: Automatic Cleanup — TTL expiry

### H2: Configuration
Cache-related settings in hassette.toml.

### H2: Lifecycle
When cache is available during app lifecycle.

### H2: Data Types
What can be cached (JSON-serializable types).

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 9 files in `cache/snippets/` | Keep | Basic cache operations |

## Cross-Links

- **Links to:** Patterns & Examples, Configuration/Global (cache settings)
- **Linked from:** Architecture, Apps overview
