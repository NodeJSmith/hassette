# Cache — Patterns & Examples

**Status:** Exists (141 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Pattern: API Response Caching
Cache expensive HA API calls.

### H2: Pattern: Rate-Limiting Notifications
Use cache timestamps to prevent notification spam.

### H2: Pattern: Persistent Counters
Counters that survive restarts.

### H2: Pattern: Storing Complex Data
Dataclasses/dicts in cache.

### H2: Pattern: Expiring Cache Entries
TTL-based expiry.

### H2: Pattern: Load Once, Write on Shutdown
Batch cache operations for performance.

### H2: Best Practices
#### H3: What to Cache
#### H3: Cache vs StateManager
#### H3: Performance

### H2: Troubleshooting
#### H3: Cache Not Persisting
#### H3: Cache Size Exceeded
#### H3: Debugging Cache Operations

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 9 files in `cache/snippets/` | Keep | Pattern examples (shared with overview — assign per-page) |

## Cross-Links

- **Links to:** Cache overview, States overview (cache vs StateManager)
- **Linked from:** Cache overview, Recipes
